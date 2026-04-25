"""
negotiation.py -- One negotiation trajectory for one (policy, scheme, vehicle)
combination.

Differences from the 0421 version:

  * The buyer is not a single U[0, S_{t-1}] sampler anymore.  Instead, the
    run is parameterized by a BuyerScheme object (A/B/C/D from the paper),
    which supplies its own per-run state and per-turn sampling callable.
    See buyer_schemes.py.

  * The seller schedule is FIXED (one strategy for the whole negotiation),
    so the SellerSchedule indirection from the 0421 code is gone.  Every
    round uses the same system prompt.

  * T = 12 turns (was 16).

Unchanged:

  * [PRICE] line extraction (strict -> loose fallback regexes).
  * DeepSeek-reasoner call path with exponential backoff retry.
  * [buyer] / [seller] history format baked into the system prompt.
  * 8 buyer-message templates for natural-language phrasing.
"""

from __future__ import annotations

import random
import re
import time

from seller_prompt_ensemble import VehicleSpec, build_prompt
from buyer_schemes import BuyerScheme

import config


# ----------------------------------------------------------------------
# Agreement threshold
# ----------------------------------------------------------------------
# A round counts as an agreement if the seller's ask is within this
# multiple of the buyer's bid, i.e.  S_t <= AGREEMENT_MULT * B_t.
# When agreement is reached at turn t, generation stops after that turn
# (no further buyer/seller calls), saving API cost.  The agreement turn
# itself is kept in the output so the downstream analysis can observe it.
# NOTE: paper Appendix B.1 previously specified 1.01; the tighter 1.005
# keeps slightly more near-agreement turns in the analysis window.  If
# you change this number, update the paper text accordingly.
AGREEMENT_MULT: float = 1.005
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# Buyer message templates (unchanged from 0421)
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


def make_buyer_message(car_name: str, price: float, rng: random.Random) -> tuple[str, int]:
    """Pick a template, fill it in, and append the mandatory [PRICE] line."""
    tid = rng.randint(0, len(_BUYER_TEMPLATES) - 1)
    prose = _BUYER_TEMPLATES[tid].format(car=car_name, price=price)
    msg = f"{prose}\n\n[PRICE] {car_name}: ${price:.2f}"
    return msg, tid


# ----------------------------------------------------------------------
# History formatting
# ----------------------------------------------------------------------

_SPEAKER_LABEL = {"BUYER": "[buyer]", "SELLER": "[seller]"}


def format_history(history: list[dict]) -> str:
    parts: list[str] = []
    for t in history:
        label = _SPEAKER_LABEL.get(t["speaker"], f"[{t['speaker'].lower()}]")
        parts.append(f"{label}\n{t['content']}")
    return "\n\n".join(parts)


# ----------------------------------------------------------------------
# Seller-price extractor
# ----------------------------------------------------------------------

def extract_seller_price(answer: str, car_name: str) -> float | None:
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
# Seller LLM call
# ----------------------------------------------------------------------

def _one_seller_call(
    client,
    model: str,
    system_prompt: str,
    history: list[dict],
    opening: bool,
) -> tuple[str, str | None]:
    """One attempt at a seller turn.  Raises on API errors (caller retries)."""

    # Bake the conversation history into the system prompt, same as the
    # 0421 runner.  Keeps the messages array tiny and stateless.
    if history:
        hist_block = (
            "CONVERSATION HISTORY SO FAR:\n\n"
            + format_history(history)
            + "\n\n--- END OF CONVERSATION HISTORY ---\n\n"
        )
        effective_system = hist_block + system_prompt
    else:
        effective_system = system_prompt

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

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=config.MAX_TOKENS,
        extra_body=dict(config.THINKING_EXTRA_BODY),
    )
    msg = resp.choices[0].message
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
    """Bounded exponential-backoff retry on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(1, config.RETRY_MAX_ATTEMPTS + 1):
        try:
            return _one_seller_call(client, model, system_prompt, history, opening)
        except Exception as e:  # noqa: BLE001
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
    fleet,
    policy_key: str,
    buyer_scheme: BuyerScheme,
    n_rounds: int,
    rng_seed: int,
    verbose: bool = True,
) -> dict:
    """Run one negotiation trajectory over `n_rounds` rounds on `active_car`.

    The seller system prompt is built once at the start (fixed policy, no
    scheduling).  Each round:

      1. Buyer samples B_t via buyer_scheme.sample_bid(state, rng, t,
         B_prev, S_prev).  S_prev comes from the previous seller turn
         (or None on round 1).
      2. Buyer message built from a random one of 8 templates.
      3. Seller LLM called with full history + the fixed system prompt.
      4. Seller price extracted via regex.

    Returns a dict with per-round logs and all metadata needed to reconstruct
    the run.  The full system prompt is stored once on round 1 only (it's
    constant across the whole run, so storing it every round would be a waste).
    """
    rng = random.Random(rng_seed)
    car_name = active_car.car_name

    # One-time setup
    system_prompt = build_prompt(
        strategy_key=policy_key,
        fleet=list(fleet),
        active_car_name=car_name,
    )
    buyer_state = buyer_scheme.init_state(
        rng,
        vehicle={
            "market_price_new": float(active_car.market_price_new),
            "dealer_cost":      float(active_car.dealer_cost),
        },
        T=n_rounds,
    )

    history: list[dict]   = []
    rounds_log: list[dict] = []
    last_seller_price: float | None = None
    last_buyer_price:  float | None = None
    agreed:            bool         = False
    agreement_round:   int | None   = None

    for round_num in range(1, n_rounds + 1):
        # ---- Buyer turn ----
        B_raw = buyer_scheme.sample_bid(
            state=buyer_state,
            rng=rng,
            t=round_num,
            B_prev=last_buyer_price,
            S_prev=last_seller_price,
        )
        buyer_price = round(float(B_raw), 2)
        buyer_msg, template_id = make_buyer_message(car_name, buyer_price, rng)
        history.append({"speaker": "BUYER", "content": buyer_msg})

        # ---- Seller turn ----
        seller_answer, seller_reasoning = call_seller_llm(
            client=client,
            model=model,
            system_prompt=system_prompt,
            history=history,
            opening=(round_num == 1),
        )
        seller_price = extract_seller_price(seller_answer, car_name)
        history.append({"speaker": "SELLER", "content": seller_answer})

        # ---- Agreement check ----
        # Agreement is defined on the seller's current ask relative to the
        # buyer's current bid, at this same turn.  We only declare agreement
        # when the seller price parses cleanly AND both prices are positive.
        is_agreement = (
            seller_price is not None
            and seller_price > 0
            and buyer_price > 0
            and seller_price <= AGREEMENT_MULT * buyer_price
        )

        rounds_log.append({
            "round":                 round_num,
            "buyer_price":           buyer_price,
            "buyer_message":         buyer_msg,
            "buyer_template_id":     template_id,
            "seller_system_prompt":  system_prompt if round_num == 1 else None,
            "seller_answer":         seller_answer,
            "seller_reasoning":      seller_reasoning,
            "seller_price":          seller_price,
            "is_agreement":          is_agreement,
        })

        if verbose:
            sp = f"${seller_price:,.2f}" if seller_price is not None else "PARSE-FAIL"
            flag = "  <-- AGREED" if is_agreement else ""
            print(
                f"      R{round_num:>2}  buy ${buyer_price:>10,.2f}   "
                f"sel {sp:>14}   [scheme={buyer_scheme.key} policy={policy_key}]"
                f"{flag}",
                flush=True,
            )

        # Advance lags
        last_buyer_price = buyer_price
        if seller_price is not None:
            last_seller_price = seller_price
        # else: keep the previous seller price (buyer upper bound stays sensible)

        # ---- Early-termination on agreement ----
        # Stop after the first turn at which S_t <= AGREEMENT_MULT * B_t.
        # The agreement turn itself has already been recorded above, so
        # downstream analysis sees it; what we skip is all subsequent turns.
        if is_agreement:
            agreed          = True
            agreement_round = round_num
            break

    return {
        "car": {
            "car_name":         active_car.car_name,
            "public_description": active_car.public_description,
            "market_price_new": float(active_car.market_price_new),
            "dealer_cost":      float(active_car.dealer_cost),
        },
        "rng_seed":           rng_seed,
        "n_rounds_planned":   n_rounds,
        "n_rounds_generated": len(rounds_log),
        "agreed":             agreed,
        "agreement_round":    agreement_round,
        "agreement_mult":     AGREEMENT_MULT,
        "policy":             policy_key,
        "buyer_scheme":       buyer_scheme.key,
        "buyer_scheme_name":  buyer_scheme.name,
        "buyer_state":        {k: (v if not callable(v) else None) for k, v in buyer_state.items()},
        "model":              model,
        "rounds":             rounds_log,
    }
