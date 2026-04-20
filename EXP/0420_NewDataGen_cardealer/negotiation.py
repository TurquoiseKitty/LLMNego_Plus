"""
negotiation.py — One negotiation trajectory for one car.

Responsibilities:

  1. Buyer price sampler: uniform(0, upper) where
         upper = market_price_new                           (round 1)
         upper = min(market_price_new, prev_seller) - $0.01 (round >= 2)
     The $0.01 offset enforces a strict buyer < prev_seller inequality so the
     buyer can never "accept" the previous seller quote by coincidence.

  2. Buyer message generator: plain-English prose plus a mandatory
         [PRICE] <car_name>: $X.XX
     line at the end, matching the CONVERSATION HISTORY FORMAT specified in
     seller_prompt_ensemble.py.

  3. Seller price extractor: regex against the same [PRICE] line format.

  4. Seller LLM call: deepseek-reasoner style call as used in the 0416b
     runner --
         max_tokens = 4096
         extra_body = {"enable_thinking": True, "thinking_budget": 8192}
     The returned message's `reasoning_content` attribute holds the model's
     chain-of-thought and `content` holds the final answer.  A small GPT
     fallback path handles `<think>...</think>`-style reasoning if the
     caller points the runner at an OpenAI model instead.

  5. History formatting: `[buyer]` / `[seller]` lowercase labels inside
     square brackets, matching the previous rar's `format_history` pattern
     but with the new role names.

  6. Retry wrapper: transient API errors get exponential-backoff retries
     (RETRY_MAX_ATTEMPTS from config.py).

  7. run_single_negotiation(...): runs n_rounds of buyer -> seller alternation
     for one car and returns a structured log.
"""

from __future__ import annotations

import random
import re
import time
from typing import Iterable

from seller_prompt_ensemble import VehicleSpec, build_prompt
from seller_schedule import SellerSchedule

import config


# ----------------------------------------------------------------------
# Buyer
# ----------------------------------------------------------------------

_BUYER_TEMPLATES: list[str] = [
    "I'd be willing to pay ${price:,.2f} for the {car}.",
    "My offer on the {car} is ${price:,.2f}.",
    "How about ${price:,.2f} for the {car}?",
    "I can do ${price:,.2f} on the {car}.",
    "For the {car}, I'll offer ${price:,.2f}.",
    "What if I paid ${price:,.2f} for the {car}?",
    "${price:,.2f} is what I'm thinking on the {car}.",
    "I'd like to propose ${price:,.2f} for the {car}.",
]

_EPSILON = 0.01  # strict buyer < prev_seller gap, in dollars


def buyer_next_price(
    market_price_new: float,
    prev_seller_price: float | None,
    rng: random.Random,
) -> float:
    """Sample the buyer's next bid per the project spec:
        uniform(0, min(market_price_new, prev_seller_price) - EPSILON)
    with market_price_new only as the upper bound when there is no prior seller quote.
    """
    if prev_seller_price is None:
        upper = float(market_price_new)
    else:
        upper = min(float(market_price_new), float(prev_seller_price)) - _EPSILON

    # Hard floor so we never get a negative / zero range.
    upper = max(upper, _EPSILON)
    raw = rng.uniform(0.0, upper)
    return round(raw, 2)


def make_buyer_message(
    car_name: str,
    price: float,
    rng: random.Random,
) -> tuple[str, int]:
    """Pick a template, fill it in, and append the mandatory [PRICE] line."""
    tid = rng.randint(0, len(_BUYER_TEMPLATES) - 1)
    prose = _BUYER_TEMPLATES[tid].format(car=car_name, price=price)
    msg = f"{prose}\n\n[PRICE] {car_name}: ${price:.2f}"
    return msg, tid


# ----------------------------------------------------------------------
# History formatting + seller price extraction
# ----------------------------------------------------------------------
# The previous rar's `format_history` used bracketed-label turns like
# "[MERCHANT]\n<content>\n\n[SUPPLIER]\n<content>".  The new setup uses
# `[buyer]` / `[seller]` lowercase labels (exactly as requested).
# ----------------------------------------------------------------------

_SPEAKER_LABEL = {"BUYER": "[buyer]", "SELLER": "[seller]"}


def format_history(history: list[dict]) -> str:
    """Flat text format: alternating [buyer] / [seller] blocks."""
    parts: list[str] = []
    for t in history:
        label = _SPEAKER_LABEL.get(t["speaker"], f"[{t['speaker'].lower()}]")
        parts.append(f"{label}\n{t['content']}")
    return "\n\n".join(parts)


def extract_seller_price(answer: str, car_name: str) -> float | None:
    """Parse a price from the seller's answer.

    Preferred format (strict):
        [PRICE] <car_name>: $X.XX

    Falls back progressively to looser patterns if the strict form is absent.
    Returns None only if no dollar amount can be found anywhere.
    """
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


# ----------------------------------------------------------------------
# Model-type detection + <think>-tag extraction for GPT fallback
# ----------------------------------------------------------------------

def _is_gpt_model(model: str) -> bool:
    m = (model or "").lower()
    return m.startswith("gpt") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4")


_GPT_THINKING_INSTRUCTION = (
    "\n\nBefore your final answer you MAY reason privately inside "
    "<think>...</think> tags.  Whatever you put between those tags will not "
    "be shown to the buyer.  After the closing </think>, give your final "
    "seller response, ending with the required [PRICE] line."
)


def _extract_think_tags(content: str) -> tuple[str, str | None]:
    """Split a GPT-style response with <think>...</think> into (answer, reasoning)."""
    if not content:
        return "", None
    m = re.search(r"<think>(.*?)</think>", content, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return content.strip(), None
    reasoning = m.group(1).strip()
    answer = (content[: m.start()] + content[m.end():]).strip()
    return answer, reasoning


# ----------------------------------------------------------------------
# Seller LLM call  --  DeepSeek reasoner primary, GPT fallback
# ----------------------------------------------------------------------

def _one_seller_call(
    client,
    model: str,
    system_prompt: str,
    history: list[dict],
    opening: bool,
) -> tuple[str, str | None]:
    """One attempt at a seller turn.  Raises on API errors (caller retries)."""
    gpt_mode = _is_gpt_model(model)

    # Bake the conversation history into the system prompt, same as the
    # previous runner.  This keeps the messages array tiny and stateless.
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

    if opening:
        user_content = (
            "The buyer has just made their opening offer above.  "
            "Provide your counter-offer, staying fully in character and "
            "ending with the required [PRICE] line."
        )
    else:
        user_content = (
            "Given the conversation history above and your instructions, "
            "provide your next seller response, ending with the required "
            "[PRICE] line."
        )

    messages = [
        {"role": "system", "content": effective_system},
        {"role": "user",   "content": user_content},
    ]

    # --- call params: mirror the 0416b runner exactly ---
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
        # DeepSeek reasoner exposes the chain-of-thought separately.
        reasoning = getattr(msg, "reasoning_content", None)
        answer = (msg.content or "").strip()
        reasoning = reasoning.strip() if reasoning else None

    return answer, reasoning


def call_seller_llm(
    client,
    model: str,
    system_prompt: str,
    history: list[dict],
    opening: bool,
) -> tuple[str, str | None]:
    """One seller turn with bounded exponential-backoff retry on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(1, config.RETRY_MAX_ATTEMPTS + 1):
        try:
            return _one_seller_call(client, model, system_prompt, history, opening)
        except Exception as e:  # noqa: BLE001  (retry is by design)
            last_exc = e
            if attempt == config.RETRY_MAX_ATTEMPTS:
                break
            delay = config.RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            print(
                f"    !! API error (attempt {attempt}/{config.RETRY_MAX_ATTEMPTS}): "
                f"{type(e).__name__}: {e}  -- sleeping {delay:.0f}s",
                flush=True,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


# ----------------------------------------------------------------------
# Single negotiation loop
# ----------------------------------------------------------------------

def run_single_negotiation(
    client,
    model: str,
    active_car: VehicleSpec,
    fleet: Iterable[VehicleSpec],
    seller_schedule: SellerSchedule,
    n_rounds: int,
    rng_seed: int,
    verbose: bool = True,
) -> dict:
    """Run one negotiation trajectory over `n_rounds` rounds on `active_car`.

    Each round:
        1. Buyer picks a price (random, clipped) and emits a message with a
           [PRICE] line.  The message is appended to the shared history.
        2. Seller strategy for this round is resolved from `seller_schedule`.
           The seller's system prompt is rebuilt (so adaptive schedules do
           change persona mid-negotiation).  The LLM is called with the
           history-augmented system prompt.  The reply is parsed for a price
           and appended to the history.

    Returns a dict with per-round logs and all metadata needed to reconstruct
    the run.  The full system prompt is stored only on rounds where the
    active strategy actually changes, to keep file sizes manageable.
    """
    fleet_list = list(fleet)
    rng = random.Random(rng_seed)
    market_new = float(active_car.market_price_new)
    car_name = active_car.car_name

    history: list[dict] = []
    rounds_log: list[dict] = []
    last_seller_price: float | None = None
    last_strategy: str | None = None

    for round_num in range(1, n_rounds + 1):
        # ---- Buyer turn ----
        buyer_price = buyer_next_price(market_new, last_seller_price, rng)
        buyer_msg, template_id = make_buyer_message(car_name, buyer_price, rng)
        history.append({"speaker": "BUYER", "content": buyer_msg})

        # ---- Seller turn ----
        strat = seller_schedule.strategy_for_round(round_num)
        strategy_changed = (strat != last_strategy)
        system_prompt = build_prompt(
            strategy_key=strat,
            fleet=fleet_list,
            active_car_name=car_name,
        )

        seller_answer, seller_reasoning = call_seller_llm(
            client=client,
            model=model,
            system_prompt=system_prompt,
            history=history,
            opening=(round_num == 1),
        )
        seller_price = extract_seller_price(seller_answer, car_name)
        history.append({"speaker": "SELLER", "content": seller_answer})

        rounds_log.append({
            "round": round_num,
            "buyer_price": buyer_price,
            "buyer_message": buyer_msg,
            "buyer_template_id": template_id,
            "seller_active_strategy": strat,
            "seller_strategy_changed": strategy_changed,
            "seller_system_prompt": system_prompt if strategy_changed else None,
            "seller_answer": seller_answer,
            "seller_reasoning": seller_reasoning,
            "seller_price": seller_price,
        })

        if verbose:
            sp = f"${seller_price:,.2f}" if seller_price is not None else "PARSE-FAIL"
            print(
                f"      R{round_num:>2}  buy ${buyer_price:>10,.2f}   "
                f"sel {sp:>14}   [strat={strat}]"
                + (" *" if strategy_changed else ""),
                flush=True,
            )

        if seller_price is not None:
            last_seller_price = seller_price
        last_strategy = strat

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
        "model": model,
        "rounds": rounds_log,
    }
