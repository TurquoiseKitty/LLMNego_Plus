"""
exp_runner_0413.py — Multi-buyer-type negotiation experiments.

Changes from 0412:
  - Templates randomly selected each round (fixes the round-template confound)
  - Five buyer types: random, wild, persistent, concession, anchor_drag
  - Organized output by buyer_type / seller_strategy
  - build_transitions records buyer_type and template_id
"""

from __future__ import annotations

import datetime
import json
import random
import re
from pathlib import Path

from NegoLib.Entities.Agents import Supplier
from NegoLib.Entities.products import Product
from NegoLib.Entities.strategies import ALL_SUPPLIER_STRATEGIES
from NegoLib.prompt_ensemble import (
    format_history,
    _is_gpt_model,
    _extract_think_tags,
    _GPT_THINKING_INSTRUCTION,
)


# ======================================================================
# Message templates (randomly selected, not cycling)
# ======================================================================

_BUYER_TEMPLATES = [
    "I'd like to purchase {qty} units of {product} at ${price:.2f} per unit.",
    "My offer: {product}: ${price:.2f} per unit, {qty} units.",
    "How about ${price:.2f} per unit for {qty} units of {product}?",
    "I'm willing to pay ${price:.2f} per unit for {product}, {qty} units total.",
    "For {product}, I propose ${price:.2f} per unit, {qty} units.",
    "Could you do ${price:.2f} per unit on {product}? I need {qty} units.",
    "I'll take {qty} units of {product} if you can do ${price:.2f} per unit.",
    "Would ${price:.2f} per unit work for {qty} units of {product}?",
]


def _buyer_message(product: Product, price: float, quantity: int, rng: random.Random) -> tuple[str, int]:
    """Generate a buyer message with a RANDOMLY chosen template. Returns (message, template_id)."""
    tid = rng.randint(0, len(_BUYER_TEMPLATES) - 1)
    msg = _BUYER_TEMPLATES[tid].format(product=product.name, price=price, qty=quantity)
    return msg, tid


# ======================================================================
# Buyer types
# ======================================================================

class BuyerType:
    """Base class for buyer price generators."""
    name: str = ""
    description: str = ""

    def sample_price(self, product: Product, round_num: int, n_rounds: int,
                     rng: random.Random, history_prices: list[float]) -> float:
        raise NotImplementedError

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description}


class RandomBuyer(BuyerType):
    """Draws price ~ Uniform(cost, market_price) each round."""
    name = "random"
    description = "Uniform random price in [production_cost, market_price]"

    def sample_price(self, product, round_num, n_rounds, rng, history_prices):
        return round(rng.uniform(product.cost, product.market_price), 2)

class BudgetBuyer(BuyerType):
    """Draws price ~ Uniform(0.5*cost, 0.8*cost) each round."""
    name = "budget"
    description = "Uniform random price in [0.5*cost, 0.8*cost]"

    def sample_price(self, product, round_num, n_rounds, rng, history_prices):
        low = max(0.01, 0.8 * product.cost)
        high = max(low + 0.01, 0.8 * product.market_price)
        return round(rng.uniform(low, high), 2)


class WildBuyer(BuyerType):
    """Draws price ~ Uniform(0, 2 * market_price) each round."""
    name = "wild"
    description = "Uniform random price in [0, 1.2 *market_price]"

    def sample_price(self, product, round_num, n_rounds, rng, history_prices):
        return round(rng.uniform(0.0, 1.2 * product.market_price), 2)


class PersistentBuyer(BuyerType):
    """Always proposes a fixed price (with tiny noise ±$0.01)."""

    def __init__(self, fixed_price: float):
        self.fixed_price = fixed_price
        self.name = f"persistent_{fixed_price:.2f}"
        self.description = f"Fixed price at ${fixed_price:.2f} (±$0.01 noise)"

    def sample_price(self, product, round_num, n_rounds, rng, history_prices):
        noise = rng.uniform(-0.01, 0.01)
        return round(max(0.01, self.fixed_price + noise), 2)

    def to_dict(self):
        return {"name": self.name, "description": self.description,
                "fixed_price": self.fixed_price}


class ConcessionBuyer(BuyerType):
    """
    Classic concession strategy: starts at `start_frac` of the negotiation
    zone [cost, market] and linearly increases toward `end_frac` over rounds.
    Small random jitter added each round.

    start_frac=0.1, end_frac=0.6 means:
      Round 1: ~10% above cost
      Round N: ~60% above cost
    """
    name = "concession"
    description = ("Starts low, linearly concedes upward. "
                   "start_frac=0.1, end_frac=0.6 of [cost, market]")

    def __init__(self, start_frac: float = 0.1, end_frac: float = 0.6):
        self.start_frac = start_frac
        self.end_frac = end_frac

    def sample_price(self, product, round_num, n_rounds, rng, history_prices):
        progress = (round_num - 1) / max(n_rounds - 1, 1)
        frac = self.start_frac + (self.end_frac - self.start_frac) * progress
        zone = product.market_price - product.cost
        price = product.cost + frac * zone
        jitter = rng.uniform(-0.03, 0.03) * zone
        return round(max(product.cost * 0.5, price + jitter), 2)

    def to_dict(self):
        return {"name": self.name, "description": self.description,
                "start_frac": self.start_frac, "end_frac": self.end_frac}


class AnchorDragBuyer(BuyerType):
    """
    Anchoring strategy: opens with a very low anchor (anchor_frac of zone),
    then makes tiny concessions (step_frac per round). Designed to drag
    the seller's price down by persistent low anchoring.

    anchor_frac=0.05, step_frac=0.03 means:
      Round 1: 5% above cost
      Round 2: 8% above cost
      Round 12: 38% above cost
    """
    name = "anchor_drag"
    description = ("Low anchor, tiny upward steps. "
                   "anchor_frac=0.05, step_frac=0.03 of [cost, market]")

    def __init__(self, anchor_frac: float = 0.05, step_frac: float = 0.03):
        self.anchor_frac = anchor_frac
        self.step_frac = step_frac

    def sample_price(self, product, round_num, n_rounds, rng, history_prices):
        frac = self.anchor_frac + self.step_frac * (round_num - 1)
        zone = product.market_price - product.cost
        price = product.cost + frac * zone
        jitter = rng.uniform(-0.02, 0.02) * zone
        return round(max(product.cost * 0.5, price + jitter), 2)

    def to_dict(self):
        return {"name": self.name, "description": self.description,
                "anchor_frac": self.anchor_frac, "step_frac": self.step_frac}


# ======================================================================
# Supplier prompt (same as 0412)
# ======================================================================

def build_supplier_prompt_v2(
    supplier: Supplier, product: Product, quantity: int,
    strategy: str, current_round: int, max_rounds: int,
) -> str:
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
# Price extraction (same as 0412)
# ======================================================================

def extract_supplier_price(answer: str, product_name: str) -> float | None:
    # Strategy 1: [PRICE] tag with product name
    tag_pattern = (
        r"\[PRICE\]\s*" + re.escape(product_name)
        + r"\s*:\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)"
    )
    m = re.search(tag_pattern, answer, flags=re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))

    # Strategy 1b: [PRICE] tag without product name
    m = re.search(r"\[PRICE\].*?\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)", answer, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))

    # Strategy 2: product name + price (last occurrence)
    named = re.escape(product_name) + r"\s*:?\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)"
    matches = list(re.finditer(named, answer, re.IGNORECASE))
    if matches:
        return float(matches[-1].group(1).replace(",", ""))

    # Strategy 3: any "$X.XX per unit" — last
    matches = list(re.finditer(r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)", answer, re.IGNORECASE))
    if matches:
        return float(matches[-1].group(1).replace(",", ""))

    # Strategy 4: bare "$X.XX" — last
    matches = list(re.finditer(r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)", answer, re.IGNORECASE))
    if matches:
        return float(matches[-1].group(1).replace(",", ""))

    return None


# ======================================================================
# Supplier API call
# ======================================================================

def _supplier_call(client, model, system, history, opening=False):
    gpt_mode = _is_gpt_model(model)

    if opening:
        effective_system = system
        user_content = "The negotiation is starting.  The merchant has made their opening offer above.  Provide your counter-offer."
    else:
        effective_system = system
        user_content = "Given the conversation history and your instructions, provide your next negotiation response."

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
        api_kwargs = dict(model=model, messages=messages, max_completion_tokens=8192)
    else:
        api_kwargs = dict(model=model, messages=messages, max_tokens=4096,
                          extra_body={"enable_thinking": True, "thinking_budget": 8192})

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
# Single run
# ======================================================================

def run_single(
    client, model: str, product: Product, quantity: int,
    supplier: Supplier, strategy: str,
    buyer: BuyerType,
    n_rounds: int = 12, rng_seed: int = 0,
    verbose: bool = False,
) -> dict:
    rng = random.Random(rng_seed)
    internal_cost = supplier.internal_costs.for_category(product.category)
    v = product.cost + internal_cost

    history = []
    rounds_log = []
    buyer_prices_so_far = []

    for round_num in range(1, n_rounds + 1):
        # ── Buyer turn ──
        buyer_price = buyer.sample_price(product, round_num, n_rounds, rng, buyer_prices_so_far)
        buyer_msg, template_id = _buyer_message(product, buyer_price, quantity, rng)
        history.append({"speaker": "MERCHANT", "content": buyer_msg})
        buyer_prices_so_far.append(buyer_price)

        if verbose:
            print(f"  R{round_num:>2} BUY ${buyer_price:.2f} T{template_id}", end="")

        # ── Seller turn ──
        s_system = build_supplier_prompt_v2(
            supplier, product, quantity, strategy, round_num, n_rounds)
        s_answer, s_reasoning = _supplier_call(client, model, s_system, history, opening=(round_num == 1))
        history.append({"speaker": "SUPPLIER", "content": s_answer})

        supplier_price = extract_supplier_price(s_answer, product.name)

        if verbose:
            sp = f"${supplier_price:.2f}" if supplier_price else "FAIL"
            ans_short = s_answer.replace("\n", " ")[:80]
            print(f"  SEL {sp}  \"{ans_short}...\"")

        rounds_log.append({
            "round": round_num,
            "buyer_price": buyer_price,
            "buyer_message": buyer_msg,
            "template_id": template_id,
            "supplier_answer": s_answer,
            "supplier_reasoning": s_reasoning,
            "supplier_price": supplier_price,
            "supplier_system_prompt": s_system if round_num == 1 else None,
        })

    return {
        "metadata": {
            "model": model,
            "product": {"name": product.name, "category": product.category,
                        "cost": product.cost, "market_price": product.market_price},
            "supplier": {"id": supplier.id, "name": supplier.name,
                         "internal_cost": internal_cost},
            "v": v, "quantity": quantity,
            "strategy": strategy,
            "buyer_type": buyer.to_dict(),
            "n_rounds": n_rounds, "rng_seed": rng_seed,
            "timestamp": datetime.datetime.now().isoformat(),
        },
        "rounds": rounds_log,
    }


# ======================================================================
# Batch runner for one condition
# ======================================================================

def run_condition(
    client, model: str, product: Product, quantity: int,
    supplier: Supplier, strategy: str,
    buyer: BuyerType,
    n_runs: int = 5, n_rounds: int = 12, base_seed: int = 5000,
    verbose: bool = False,
) -> dict:
    runs = []
    for i in range(n_runs):
        seed = base_seed + i
        if verbose:
            print(f"\n  --- Run {i+1}/{n_runs} (seed={seed}) ---")
        run = run_single(client, model, product, quantity, supplier, strategy,
                         buyer, n_rounds, seed, verbose)
        runs.append(run)
    return {
        "condition": {
            "model": model, "product": product.name,
            "supplier_id": supplier.id, "strategy": strategy,
            "buyer_type": buyer.name,
            "n_runs": n_runs, "n_rounds": n_rounds,
        },
        "runs": runs,
    }


# ======================================================================
# Transition builder (same logic as 0412, with buyer_type + template_id)
# ======================================================================

def build_transitions(experiment: dict) -> list[dict]:
    transitions = []
    for run_idx, run in enumerate(experiment["runs"]):
        meta = run["metadata"]
        v = meta["v"]
        cost = meta["product"]["cost"]
        market = meta["product"]["market_price"]
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
                "strategy": meta["strategy"],
                "model": meta["model"],
                "supplier_id": meta["supplier"]["id"],
                "product": meta["product"]["name"],
                "buyer_type": meta["buyer_type"]["name"],
                "template_id": curr.get("template_id", -1),
            })
    return transitions


# ======================================================================
# Save / inspect helpers
# ======================================================================

def save_json(obj, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    print(f"Saved: {path}")


def inspect_run(run, max_chars=300):
    meta = run["metadata"]
    print(f"  Product: {meta['product']['name']}  Supplier: {meta['supplier']['name']}"
          f"  v={meta['v']:.2f}  strategy={meta['strategy']}")
    print(f"  Buyer: {meta['buyer_type']['name']}  Model: {meta['model']}")
    print()
    for r in run["rounds"]:
        bp = r["buyer_price"]
        sp = r["supplier_price"]
        sp_str = f"${sp:.2f}" if sp else "FAIL"
        ans = r["supplier_answer"]
        ans_show = ans[:max_chars] + "..." if len(ans) > max_chars else ans
        print(f"  R{r['round']:>2} BUY ${bp:.2f} (T{r.get('template_id','?')})  SEL {sp_str}")
        print(f"       {ans_show}")
        print()
