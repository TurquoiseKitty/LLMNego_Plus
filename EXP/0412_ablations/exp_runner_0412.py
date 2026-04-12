"""
exp_runner_0412.py — Random-buyer single-issue negotiation experiment runner.

The buyer is PROGRAMMATIC (not an LLM).  Each round it draws a uniformly
random price from [production_cost, market_price] and sends a simple message.
Only the supplier is an LLM.

Key improvements over 0411:
  - Correct transition indexing: (m_t, s_{t-1}) → s_t
  - Robust price extraction with [PRICE] tag in supplier prompt
  - Single-issue only (no mean-price averaging)
  - Records v = cost + internal_cost per run
"""

from __future__ import annotations

import datetime
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from NegoLib.Entities.Agents import Supplier, InternalCostStructure
from NegoLib.Entities.products import Product
from NegoLib.Entities.scenarios import Scenario, ProductOrder
from NegoLib.Entities.utility import supplier_utility
from NegoLib.Entities.strategies import ALL_SUPPLIER_STRATEGIES
from NegoLib.prompt_ensemble import (
    format_history,
    _is_gpt_model,
    _extract_think_tags,
    _GPT_THINKING_INSTRUCTION,
)


# ======================================================================
# Random buyer
# ======================================================================

_BUYER_TEMPLATES = [
    "I'd like to purchase {qty} units of {product} at ${price:.2f} per unit.",
    "My offer: {product}: ${price:.2f} per unit, {qty} units.",
    "How about ${price:.2f} per unit for {qty} units of {product}?",
    "I'm willing to pay ${price:.2f} per unit for {product}, {qty} units total.",
    "For {product}, I propose ${price:.2f} per unit, {qty} units.",
]


def random_buyer_message(
    product: Product,
    price: float,
    quantity: int,
    round_num: int,
) -> str:
    """Generate a simple buyer message with the given price."""
    template = _BUYER_TEMPLATES[round_num % len(_BUYER_TEMPLATES)]
    return template.format(
        product=product.name,
        price=price,
        qty=quantity,
    )


def sample_buyer_price(
    product: Product,
    rng: random.Random,
) -> float:
    """Draw a uniformly random price in [cost, market_price], rounded to cents."""
    lo = product.cost
    hi = product.market_price
    return round(rng.uniform(lo, hi), 2)


# ======================================================================
# Supplier prompt (modified for better extraction)
# ======================================================================

def build_supplier_prompt_v2(
    supplier: Supplier,
    product: Product,
    quantity: int,
    strategy: str,
    current_round: int,
    max_rounds: int,
) -> str:
    """
    Build the supplier's system prompt for a single-product negotiation.

    Changes from v1:
      - Single-product only (no scenario object needed)
      - Adds explicit [PRICE] tag instruction for reliable extraction
      - Utility explanation is inline and concise
    """
    remaining = max_rounds - current_round + 1
    internal_cost = supplier.internal_costs.for_category(product.category)
    v = product.cost + internal_cost

    strategy_text = ALL_SUPPLIER_STRATEGIES.get(strategy, strategy)

    prompt = f"""\
You are a product supplier (the Supplier) negotiating to sell a product \
to a vending machine operator (the Merchant).

PRODUCT:
  {product.name}
  Category     : {product.category}
  Production cost : ${product.cost:.2f} per unit   (public — both sides know)
  Market price    : ${product.market_price:.2f} per unit   (public — both sides know)

YOUR PRIVATE INFORMATION (the merchant does NOT know this):
  Internal fulfilment cost : ${internal_cost:.2f} per unit
  Your break-even floor    : ${v:.2f} per unit  (= production cost + fulfilment cost)
  Maximum negotiation rounds: {max_rounds}

  !! CRITICAL — INFORMATION SECRECY !!
  NEVER reveal your internal fulfilment cost, break-even floor, or maximum
  number of rounds.  Do not hint at these numbers.

UTILITY:
  Your profit per unit = deal_price − ${v:.2f}
  Total profit = profit_per_unit × quantity
  You want to maximise total profit.  Any deal below ${v:.2f}/unit loses money.

YOUR STRATEGY:
  {strategy_text}

ROUND STATUS:
  Round {current_round} of {max_rounds}.  {remaining} round(s) remaining.\
"""

    if remaining == 1:
        prompt += "\n  This is your FINAL round.  Reach a conclusion now."
    elif remaining == 2:
        prompt += "\n  Only 2 rounds left.  Consider closing soon."

    prompt += f"""

CONVERSATION FORMAT:
  The transcript uses [MERCHANT] and [SUPPLIER] labels.
  You are [SUPPLIER].  Write only your message — do not include the label.

  Your message should read like a natural negotiation response.  You may
  include brief reasoning or justification.

  !! IMPORTANT — PRICE FORMAT !!
  At the VERY END of your message, on a NEW line, state your proposed price
  using EXACTLY this format:

  [PRICE] {product.name}: $X.XX per unit

  This [PRICE] line MUST be the last line of your response.
  Example:
  [PRICE] {product.name}: $1.25 per unit
"""
    return prompt


# ======================================================================
# Price extraction (robust)
# ======================================================================

def extract_supplier_price(answer: str, product_name: str) -> float | None:
    """
    Extract the supplier's proposed price from the response.

    Strategy:
      1. Look for [PRICE] tag (most reliable)
      2. Fall back to general "$X.XX per unit" pattern, prefer last occurrence
      3. Return None if nothing found
    """
    # --- Strategy 1: [PRICE] tag ---
    # Match: [PRICE] <product>: $X.XX per unit
    tag_pattern = (
        r"\[PRICE\]\s*"
        + re.escape(product_name)
        + r"\s*:\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)"
    )
    m = re.search(tag_pattern, answer, flags=re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))

    # --- Strategy 1b: [PRICE] tag without product name ---
    tag_simple = r"\[PRICE\].*?\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"
    m = re.search(tag_simple, answer, flags=re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))

    # --- Strategy 2: product name + $X.XX per unit (last occurrence) ---
    named_pattern = (
        re.escape(product_name)
        + r"\s*:?\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)"
    )
    matches = list(re.finditer(named_pattern, answer, flags=re.IGNORECASE))
    if matches:
        return float(matches[-1].group(1).replace(",", ""))

    # --- Strategy 3: any "$X.XX per unit" — take the LAST one ---
    generic = r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)"
    matches = list(re.finditer(generic, answer, flags=re.IGNORECASE))
    if matches:
        return float(matches[-1].group(1).replace(",", ""))

    # --- Strategy 4: any "$X.XX" — take the last one (least reliable) ---
    dollar = r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"
    matches = list(re.finditer(dollar, answer, flags=re.IGNORECASE))
    if matches:
        return float(matches[-1].group(1).replace(",", ""))

    return None


# ======================================================================
# Supplier API call
# ======================================================================

def _supplier_call(
    client,
    model: str,
    system: str,
    history: list[dict],
    opening: bool = False,
) -> tuple[str, str | None]:
    """Call the LLM for the supplier's turn."""
    gpt_mode = _is_gpt_model(model)

    if opening:
        effective_system = system
        user_content = "The negotiation is starting.  The merchant has made their opening offer above.  Provide your counter-offer."
    else:
        effective_system = system
        user_content = (
            "Given the conversation history and your instructions, "
            "provide your next negotiation response."
        )

    # Prepend conversation history to system prompt (history-first ordering)
    if history:
        history_block = (
            "CONVERSATION HISTORY SO FAR:\n\n"
            + format_history(history)
            + "\n\n--- END OF CONVERSATION HISTORY ---\n\n"
        )
        effective_system = history_block + effective_system

    if gpt_mode:
        effective_system += _GPT_THINKING_INSTRUCTION

    messages = [
        {"role": "system", "content": effective_system},
        {"role": "user", "content": user_content},
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
            max_tokens=4096,
            extra_body={"enable_thinking": True, "thinking_budget": 8192},
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


# ======================================================================
# Single-run experiment
# ======================================================================

def random_buyer_run(
    client,
    model: str,
    product: Product,
    quantity: int,
    supplier: Supplier,
    strategy: str,
    n_rounds: int = 8,
    rng_seed: int | None = None,
    verbose: bool = False,
) -> dict:
    """
    Run one single-issue negotiation with a programmatic random buyer.

    Returns a dict with all round-level data plus metadata.
    """
    rng = random.Random(rng_seed)
    internal_cost = supplier.internal_costs.for_category(product.category)
    v = product.cost + internal_cost

    history: list[dict] = []
    rounds_log: list[dict] = []

    for round_num in range(1, n_rounds + 1):
        # --- Buyer turn (programmatic) ---
        buyer_price = sample_buyer_price(product, rng)
        buyer_msg = random_buyer_message(product, buyer_price, quantity, round_num)
        history.append({"speaker": "MERCHANT", "content": buyer_msg})

        if verbose:
            print(f"  R{round_num} BUYER : ${buyer_price:.2f}  — {buyer_msg}")

        # --- Supplier turn (LLM) ---
        s_system = build_supplier_prompt_v2(
            supplier=supplier,
            product=product,
            quantity=quantity,
            strategy=strategy,
            current_round=round_num,
            max_rounds=n_rounds,
        )

        s_answer, s_reasoning = _supplier_call(
            client, model, s_system, history, opening=(round_num == 1)
        )
        history.append({"speaker": "SUPPLIER", "content": s_answer})

        supplier_price = extract_supplier_price(s_answer, product.name)

        if verbose:
            sp_str = f"${supplier_price:.2f}" if supplier_price else "PARSE_FAIL"
            # Show truncated response so you can verify the seller is reasoning
            answer_preview = s_answer.replace("\n", " ")
            if len(answer_preview) > 120:
                answer_preview = answer_preview[:120] + "..."
            print(f"  R{round_num} SELLER: {sp_str}  ← \"{answer_preview}\"")
            if s_reasoning:
                reasoning_preview = s_reasoning.replace("\n", " ")[:80]
                print(f"         [thinking]: \"{reasoning_preview}...\"")
            if supplier_price is None:
                print(f"         [PARSE FAIL — raw tail]: ...{s_answer[-300:]}")

        rounds_log.append({
            "round": round_num,
            "buyer_price": buyer_price,
            "buyer_message": buyer_msg,
            "supplier_answer": s_answer,
            "supplier_reasoning": s_reasoning,
            "supplier_price": supplier_price,
            "supplier_system_prompt": s_system if round_num == 1 else None,
        })

    return {
        "metadata": {
            "model": model,
            "product": {
                "name": product.name,
                "category": product.category,
                "cost": product.cost,
                "market_price": product.market_price,
            },
            "supplier": {
                "id": supplier.id,
                "name": supplier.name,
                "internal_cost": internal_cost,
            },
            "v": v,
            "quantity": quantity,
            "strategy": strategy,
            "n_rounds": n_rounds,
            "rng_seed": rng_seed,
            "timestamp": datetime.datetime.now().isoformat(),
        },
        "rounds": rounds_log,
    }


# ======================================================================
# Batch runner
# ======================================================================

def batch_random_buyer_exp(
    client,
    model: str,
    product: Product,
    quantity: int,
    supplier: Supplier,
    strategy: str,
    n_runs: int = 5,
    n_rounds: int = 8,
    base_seed: int = 1000,
    verbose: bool = False,
) -> dict:
    """Run n_runs experiments for one (product, supplier, strategy) condition."""
    runs = []
    for i in range(n_runs):
        seed = base_seed + i
        if verbose:
            print(f"\n--- Run {i+1}/{n_runs} (seed={seed}) ---")
        run = random_buyer_run(
            client=client,
            model=model,
            product=product,
            quantity=quantity,
            supplier=supplier,
            strategy=strategy,
            n_rounds=n_rounds,
            rng_seed=seed,
            verbose=verbose,
        )
        runs.append(run)
    return {
        "condition": {
            "model": model,
            "product": product.name,
            "supplier_id": supplier.id,
            "strategy": strategy,
            "n_runs": n_runs,
            "n_rounds": n_rounds,
        },
        "runs": runs,
    }


# ======================================================================
# Transition builder (correct indexing)
# ======================================================================

def build_transitions(experiment: dict) -> list[dict]:
    """
    Build transition rows from experiment results.

    Correct indexing: (m_t, s_{t-1}, v, t) → s_t
    i.e. the buyer's CURRENT-round price and the supplier's PREVIOUS-round
    price predict the supplier's CURRENT-round price.

    Round 1 has no s_{t-1}, so the first usable transition is round 2.
    """
    transitions = []

    for run_idx, run in enumerate(experiment["runs"]):
        v = run["metadata"]["v"]
        product_name = run["metadata"]["product"]["name"]
        cost = run["metadata"]["product"]["cost"]
        market = run["metadata"]["product"]["market_price"]
        strategy = run["metadata"]["strategy"]
        model = run["metadata"]["model"]
        supplier_id = run["metadata"]["supplier"]["id"]

        rounds = run["rounds"]
        for i in range(1, len(rounds)):
            prev = rounds[i - 1]
            curr = rounds[i]

            s_prev = prev["supplier_price"]
            m_curr = curr["buyer_price"]
            s_curr = curr["supplier_price"]

            if s_prev is None or s_curr is None:
                continue

            transitions.append({
                "run_idx": run_idx,
                "round_t": curr["round"],
                "m_t": m_curr,
                "s_prev": s_prev,
                "s_t": s_curr,
                "v": v,
                "cost": cost,
                "market": market,
                "strategy": strategy,
                "model": model,
                "supplier_id": supplier_id,
                "product": product_name,
            })

    return transitions


# ======================================================================
# Save helper
# ======================================================================

def save_json(obj: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    print(f"Saved: {path}")


# ======================================================================
# Inspection / debugging helper
# ======================================================================

def inspect_run(run: dict, max_answer_chars: int = 300) -> None:
    """
    Pretty-print a single run's conversation to verify the LLM is
    actually generating full negotiation responses (not just prices).

    Usage:
        data = json.load(open("results/sweep_A/A_Sparkling_S1.json"))
        inspect_run(data["runs"][0])
    """
    meta = run["metadata"]
    v = meta["v"]
    print(f"  Product: {meta['product']['name']}  |  Supplier: {meta['supplier']['name']}"
          f"  |  v={v:.2f}  |  strategy={meta['strategy']}")
    print(f"  Model: {meta['model']}  |  Rounds: {meta['n_rounds']}")
    print()

    for r in run["rounds"]:
        rn = r["round"]
        bp = r["buyer_price"]
        sp = r["supplier_price"]
        sp_str = f"${sp:.2f}" if sp else "PARSE_FAIL"

        print(f"  Round {rn}:")
        print(f"    BUYER  (${bp:.2f}): {r['buyer_message']}")

        # Show full supplier answer (truncated)
        ans = r["supplier_answer"]
        if len(ans) > max_answer_chars:
            ans_show = ans[:max_answer_chars] + f"... [{len(ans)} chars total]"
        else:
            ans_show = ans
        print(f"    SELLER (→{sp_str}): {ans_show}")

        # Show reasoning if present
        reasoning = r.get("supplier_reasoning")
        if reasoning:
            reas_show = reasoning[:150].replace("\n", " ")
            print(f"    [thinking]: {reas_show}...")
        print()