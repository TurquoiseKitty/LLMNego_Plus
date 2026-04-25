"""
negotiation.py -- One negotiation trajectory for one car (LLM buyer version).

This is the 0423 replacement for the 0421 `negotiation.py`. The seller side
is unchanged (same six strategies, same prompt, same DeepSeek-reasoner call
path). The buyer side is now an LLM agent with its own system prompt built
by buyer_prompt_ensemble.build_buyer_prompt(...).

Round structure (unchanged shape, just the buyer call is new):
    1. Buyer turn:
         system prompt = build_buyer_prompt(buyer_strategy, fleet, car)
         + conversation history so far
         The LLM produces a message that ends with a [PRICE] line.
         That [PRICE] value is the buyer's current bid.
    2. Seller turn:
         system prompt = build_prompt(seller_strategy_for_round, fleet, car)
         + conversation history (including the buyer turn we just got)
         The LLM produces a message that ends with a [PRICE] line.

Invariants preserved for the buyer (per the project spec):
    - Buyer does NOT know the dealer's true cost v.
    - Buyer does NOT walk away early.
    - Buyer is NOT informed of the round limit.

Price parsing and history formatting are shared between buyer and seller;
the only asymmetric piece is each side's system prompt.

Retry policy on transient API errors is the same as 0421 (bounded exponential
backoff; see config.RETRY_MAX_ATTEMPTS / config.RETRY_BASE_DELAY_SECONDS).

If the buyer LLM returns a response without a parseable [PRICE] line, we
re-prompt up to `_BUYER_PARSE_RETRIES` times with a terse correction
instruction; if it still fails, we record the un-parsed text, set
buyer_price = None, and move on so the sweep does not stall on one bad turn.
"""

from __future__ import annotations

import random
import re
import time
from typing import Iterable

from seller_prompt_ensemble import VehicleSpec, build_prompt
from buyer_prompt_ensemble import build_buyer_prompt
from seller_schedule import SellerSchedule
from buyer_schedule import BuyerSchedule

import config


# ======================================================================
# History formatting and price extraction (shared between buyer & seller).
# ======================================================================

_SPEAKER_LABEL = {"BUYER": "[buyer]", "SELLER": "[seller]"}


def format_history(history: list[dict]) -> str:
    """Flat text format: alternating [buyer] / [seller] blocks (same as 0421)."""
    parts: list[str] = []
    for t in history:
        label = _SPEAKER_LABEL.get(t["speaker"], f"[{t['speaker'].lower()}]")
        parts.append(f"{label}\n{t['content']}")
    return "\n\n".join(parts)


def extract_price(answer: str, car_name: str) -> float | None:
    """Parse a [PRICE] value from a message. Same logic used on both sides."""
    if not answer:
        return None

    num_re = r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"

    # 1. Strict: [PRICE] <car_name>: $X.XX
    pat1 = r"\[PRICE\]\s*" + re.escape(car_name) + r"\s*:\s*\$?\s*" + num_re
    m = re.search(pat1, answer, flags=re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))

    # 2. Any [PRICE] line with a dollar amount
    pat2 = r"\[PRICE\][^\n$]*\$\s*" + num_re
    m = re.search(pat2, answer, flags=re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))

    # 3. Last '$N' anywhere in the answer (best-effort fallback)
    matches = list(re.finditer(r"\$\s*" + num_re, answer))
    if matches:
        return float(matches[-1].group(1).replace(",", ""))

    return None


# Back-compat alias: some downstream code still imports extract_seller_price.
extract_seller_price = extract_price


# ======================================================================
# Model-type detection + <think>-tag extraction for GPT fallback.
# ======================================================================
# Same behavior as 0421; applies to both buyer and seller.

def _is_gpt_model(model: str) -> bool:
    m = (model or "").lower()
    return m.startswith("gpt") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4")


_GPT_THINKING_INSTRUCTION = (
    "\n\nBefore your final answer you MAY reason privately inside "
    "<think>...</think> tags.  Whatever you put between those tags will not "
    "be shown to the other side.  After the closing </think>, give your "
    "final response, ending with the required [PRICE] line."
)


def _extract_think_tags(content: str) -> tuple[str, str | None]:
    if not content:
        return "", None
    m = re.search(r"<think>(.*?)</think>", content, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return content.strip(), None
    reasoning = m.group(1).strip()
    answer = (content[: m.start()] + content[m.end():]).strip()
    return answer, reasoning


# ======================================================================
# One LLM call (buyer or seller). Same mechanics as the 0421 seller call.
# ======================================================================

def _one_llm_call(
    client,
    model: str,
    system_prompt: str,
    history: list[dict],
    user_content: str,
) -> tuple[str, str | None]:
    """Raw one-shot LLM call. Raises on API errors (caller retries)."""
    gpt_mode = _is_gpt_model(model)

    if history:
        hist_block = (
            "CONVERSATION HISTORY SO FAR:\n\n"
            + format_history(history)
            + "\n\n--- END OF CONVERSATION HISTORY ---\n\n"
        )
        effective_system = hist_block + system_prompt
    else:
        effective_system = system_prompt

    if gpt_mode:
        effective_system += _GPT_THINKING_INSTRUCTION

    messages = [
        {"role": "system", "content": effective_system},
        {"role": "user",   "content": user_content},
    ]

    if gpt_mode:
        api_kwargs = dict(
            model=model,
            messages=messages,
            max_completion_tokens=8192,
        )
    else:
        api_kwargs = dict(
            model=model,
            messages=messages,
            max_tokens=config.MAX_TOKENS,
            extra_body=dict(config.THINKING_EXTRA_BODY),
        )

    resp = client.chat.completions.create(**api_kwargs)
    msg = resp.choices[0].message

    if gpt_mode:
        answer, reasoning = _extract_think_tags(msg.content or "")
    else:
        reasoning = getattr(msg, "reasoning_content", None)
        answer = (msg.content or "").strip()
        reasoning = reasoning.strip() if reasoning else None

    return answer, reasoning


def _llm_call_with_retry(
    client,
    model: str,
    system_prompt: str,
    history: list[dict],
    user_content: str,
    role_label: str,
) -> tuple[str, str | None]:
    """One LLM turn with bounded exponential-backoff retry on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(1, config.RETRY_MAX_ATTEMPTS + 1):
        try:
            return _one_llm_call(client, model, system_prompt, history, user_content)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt == config.RETRY_MAX_ATTEMPTS:
                break
            delay = config.RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            print(
                f"    !! {role_label} API error "
                f"(attempt {attempt}/{config.RETRY_MAX_ATTEMPTS}): "
                f"{type(e).__name__}: {e}  -- sleeping {delay:.0f}s",
                flush=True,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


# ======================================================================
# Buyer turn: LLM call + [PRICE] extraction with a small re-prompt retry
# loop for format errors.
# ======================================================================

_BUYER_PARSE_RETRIES: int = 2  # beyond the first attempt


def _buyer_user_content(
    car_name: str,
    opening: bool,
) -> str:
    if opening:
        return (
            f"This is the start of the negotiation for the {car_name}. "
            f"The dealer has not yet quoted a price. "
            f"Send your opening message as the buyer, staying fully in character "
            f"and ending with a valid [PRICE] line stating your current opening bid."
        )
    return (
        "Given the conversation history above and your instructions, send your next "
        "buyer turn. Respond in character. End with a valid [PRICE] line stating your "
        "current bid."
    )


def _buyer_reprompt_user_content(car_name: str) -> str:
    return (
        "Your previous response did not end with a correctly formatted [PRICE] line. "
        "Re-send your buyer turn. The LAST line of your message MUST be exactly of the form:\n\n"
        f"  [PRICE] {car_name}: $X.XX\n\n"
        "Use two decimal places, a leading $, and put no text after this line."
    )


def buyer_turn(
    client,
    model: str,
    system_prompt: str,
    history: list[dict],
    car_name: str,
    opening: bool,
) -> tuple[str, str | None, float | None, int]:
    """Run one buyer turn. Returns (answer_text, reasoning, price_or_None, parse_attempts)."""
    user_content = _buyer_user_content(car_name, opening)
    answer, reasoning = _llm_call_with_retry(
        client=client,
        model=model,
        system_prompt=system_prompt,
        history=history,
        user_content=user_content,
        role_label="buyer",
    )
    price = extract_price(answer, car_name)
    attempts = 1

    # If parsing failed, re-prompt with a terse correction a few times.
    while price is None and attempts <= _BUYER_PARSE_RETRIES:
        attempts += 1
        print(
            f"    !! buyer parse failed on attempt {attempts - 1}; "
            f"re-prompting (attempt {attempts}/{1 + _BUYER_PARSE_RETRIES})",
            flush=True,
        )
        # Fold the malformed reply into history temporarily as an assistant note,
        # and send the correction as the user turn. We DO NOT append the bad
        # reply to the real `history` passed in; that is only populated on
        # success.
        temp_history = list(history)
        temp_history.append({"speaker": "BUYER", "content": answer})
        answer, reasoning = _llm_call_with_retry(
            client=client,
            model=model,
            system_prompt=system_prompt,
            history=temp_history,
            user_content=_buyer_reprompt_user_content(car_name),
            role_label="buyer",
        )
        price = extract_price(answer, car_name)

    return answer, reasoning, price, attempts


# ======================================================================
# Seller turn: same contract as 0421, thin wrapper around _llm_call_with_retry.
# ======================================================================

def _seller_user_content(opening: bool) -> str:
    if opening:
        return (
            "The buyer has just made their opening offer above.  "
            "Provide your counter-offer, staying fully in character and "
            "ending with the required [PRICE] line."
        )
    return (
        "Given the conversation history above and your instructions, "
        "provide your next seller response, ending with the required "
        "[PRICE] line."
    )


def seller_turn(
    client,
    model: str,
    system_prompt: str,
    history: list[dict],
    opening: bool,
) -> tuple[str, str | None]:
    """Run one seller turn (same API as 0421's call_seller_llm)."""
    return _llm_call_with_retry(
        client=client,
        model=model,
        system_prompt=system_prompt,
        history=history,
        user_content=_seller_user_content(opening),
        role_label="seller",
    )


# ======================================================================
# Single negotiation loop (LLM buyer, LLM seller).
# ======================================================================

def run_single_negotiation(
    client,
    model: str,
    active_car: VehicleSpec,
    fleet: Iterable[VehicleSpec],
    seller_schedule: SellerSchedule,
    buyer_schedule: BuyerSchedule,
    n_rounds: int,
    rng_seed: int,
    verbose: bool = True,
    buyer_model: str | None = None,
) -> dict:
    """Run one n_rounds-turn negotiation on `active_car`.

    `rng_seed` is still accepted and threaded through for downstream
    reproducibility bookkeeping, but since both sides are now LLMs there is
    no random buyer sampler that actually uses it. We log it anyway.

    `buyer_model` defaults to the same model as the seller (`model`) if
    unset; pass a separate model name to use different models for buyer
    vs seller.
    """
    fleet_list = list(fleet)
    rng = random.Random(rng_seed)  # kept for parity with 0421; not currently used
    market_new = float(active_car.market_price_new)
    car_name = active_car.car_name
    if buyer_model is None:
        buyer_model = model

    history: list[dict] = []
    rounds_log: list[dict] = []
    last_seller_price: float | None = None
    last_buyer_price: float | None = None
    last_seller_strategy: str | None = None
    last_buyer_strategy: str | None = None

    for round_num in range(1, n_rounds + 1):

        # ---------------- Buyer turn ----------------
        buyer_strategy = buyer_schedule.strategy_for_round(round_num)
        buyer_strategy_changed = (buyer_strategy != last_buyer_strategy)
        buyer_system_prompt = build_buyer_prompt(
            strategy_key=buyer_strategy,
            fleet=fleet_list,
            active_car_name=car_name,
        )

        buyer_answer, buyer_reasoning, buyer_price, buyer_parse_attempts = buyer_turn(
            client=client,
            model=buyer_model,
            system_prompt=buyer_system_prompt,
            history=history,
            car_name=car_name,
            opening=(round_num == 1),
        )
        history.append({"speaker": "BUYER", "content": buyer_answer})

        # ---------------- Seller turn ----------------
        seller_strategy = seller_schedule.strategy_for_round(round_num)
        seller_strategy_changed = (seller_strategy != last_seller_strategy)
        seller_system_prompt = build_prompt(
            strategy_key=seller_strategy,
            fleet=fleet_list,
            active_car_name=car_name,
        )

        seller_answer, seller_reasoning = seller_turn(
            client=client,
            model=model,
            system_prompt=seller_system_prompt,
            history=history,
            opening=(round_num == 1),
        )
        seller_price = extract_price(seller_answer, car_name)
        history.append({"speaker": "SELLER", "content": seller_answer})

        # ---------------- Per-round log ----------------
        rounds_log.append({
            "round": round_num,

            # Buyer
            "buyer_active_strategy":   buyer_strategy,
            "buyer_strategy_changed":  buyer_strategy_changed,
            "buyer_system_prompt":     buyer_system_prompt if buyer_strategy_changed else None,
            "buyer_message":           buyer_answer,
            "buyer_reasoning":         buyer_reasoning,
            "buyer_price":             buyer_price,
            "buyer_parse_attempts":    buyer_parse_attempts,

            # Seller
            "seller_active_strategy":  seller_strategy,
            "seller_strategy_changed": seller_strategy_changed,
            "seller_system_prompt":    seller_system_prompt if seller_strategy_changed else None,
            "seller_answer":           seller_answer,
            "seller_reasoning":        seller_reasoning,
            "seller_price":            seller_price,
        })

        if verbose:
            bp = f"${buyer_price:,.2f}"  if buyer_price  is not None else "PARSE-FAIL"
            sp = f"${seller_price:,.2f}" if seller_price is not None else "PARSE-FAIL"
            print(
                f"      R{round_num:>2}  buy {bp:>14}   "
                f"sel {sp:>14}   "
                f"[b={buyer_strategy}/s={seller_strategy}]"
                + (" *s" if seller_strategy_changed else "")
                + (" *b" if buyer_strategy_changed  else "")
                + (f"  parse={buyer_parse_attempts}" if buyer_parse_attempts > 1 else ""),
                flush=True,
            )

        if buyer_price  is not None: last_buyer_price  = buyer_price
        if seller_price is not None: last_seller_price = seller_price
        last_buyer_strategy  = buyer_strategy
        last_seller_strategy = seller_strategy

    return {
        "car": {
            "car_name": active_car.car_name,
            "public_description": active_car.public_description,
            "market_price_new": market_new,
            "dealer_cost": float(active_car.dealer_cost),
        },
        "rng_seed": rng_seed,
        "n_rounds": n_rounds,
        "seller_schedule": seller_schedule.to_dict(),
        "buyer_schedule":  buyer_schedule.to_dict(),
        "model":           model,
        "buyer_model":     buyer_model,
        "rounds": rounds_log,
    }
