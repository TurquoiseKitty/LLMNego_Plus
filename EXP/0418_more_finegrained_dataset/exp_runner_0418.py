"""
exp_runner_0418.py — follow-up negotiation sweep, v0418.

Changes from 0416b:
  1. 16 rounds per run (up from 15).
  2. Product sampling: c, v-c, M-v all iid Uniform(0, 5) per run.  This
     gives continuous coverage of (cost, break-even, market) space and
     satisfies c < v < M by construction.
  3. Exactly ONE buyer strategy:  random.propose in [cost, s_prev) each
     round (the upper bound uses the seller's *last* quote rather than a
     fixed market price).  No buyer-type variation.
  4. Exactly THREE seller strategies: cooperative, tit_for_tat_matcher,
     anchor_high.
  5. Adaptive switching rule (used in nb4–nb12): a *single* deterministic
     function of (prev_strategy, m_t, s_prev).  See `switching_rule`.
"""

from __future__ import annotations

import datetime
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from NegoLib.Entities.Agents import Supplier         # kept for typing compat
from NegoLib.Entities.products import Product        # kept for typing compat
from NegoLib.prompt_ensemble import (
    format_history, _is_gpt_model, _extract_think_tags,
    _GPT_THINKING_INSTRUCTION,
)


# ======================================================================
# The three seller strategies (carried over verbatim from 0416b)
# ======================================================================

SUPPLIER_STRATEGY_TEXTS: dict[str, str] = {
    "anchor_high": (
        "Anchor high and hold.  Open at or above the market price and make "
        "only very small downward adjustments, regardless of the merchant's "
        "pressure.  Your counter-offer should move by only a few percent per "
        "turn.  Never drop into the lower half of the [production cost, "
        "market price] range."
    ),
    "cooperative": (
        "Aim for a fair deal that splits the surplus between the production "
        "cost and the market price roughly in half.  When the merchant makes "
        "a reasonable offer, meet them partway with a moderate concession.  "
        "When they offer something unreasonable, push back gently but keep "
        "signalling willingness to find middle ground."
    ),
    "tit_for_tat_matcher": (
        "Mirror the merchant.  If they raised their last offer by $X, you "
        "lower yours by roughly $X.  If they barely moved, you barely move. "
        "If they make a very low offer, respond with a matchingly stiff "
        "counter-offer.  Your behaviour is reactive, not planned."
    ),
}

ALL_STRATEGIES = list(SUPPLIER_STRATEGY_TEXTS.keys())


# ======================================================================
# Product sampling — c, v-c, M-v iid Uniform(0, 5)
# ======================================================================

@dataclass
class ProductSpec:
    name: str
    category: str
    cost: float           # c
    market_price: float   # M
    internal_cost: float  # v - c
    quantity: int

    @property
    def v(self) -> float:
        return self.cost + self.internal_cost


def sample_product_spec(rng: random.Random) -> ProductSpec:
    """
    Sample c, v-c, M-v all iid Uniform(0, 5).

    This gives:
      cost          = c
      internal_cost = v - c
      market_price  = M = v + (M - v) = (c + (v-c)) + (M-v)
      break-even v  = c + (v-c)

    Quantity is sampled from [20, 80].  The product name is a generic
    "Product #<seed>" because we're deliberately making the economics
    continuous rather than tied to specific categories.
    """
    c      = rng.uniform(0.0, 5.0)
    v_c    = rng.uniform(0.0, 5.0)   # internal cost = v - c
    M_v    = rng.uniform(0.0, 5.0)   # market markup above break-even
    cost   = round(c,       3)
    internal_cost = round(v_c, 3)
    market = round(c + v_c + M_v, 3)
    quantity = rng.randint(20, 80)

    name = f"Item(c={cost:.2f}, v-c={internal_cost:.2f}, M-v={M_v:.2f})"
    return ProductSpec(
        name=name,
        category="Synthetic",
        cost=cost,
        market_price=market,
        internal_cost=internal_cost,
        quantity=quantity,
    )


# ======================================================================
# Buyer: random uniform in [cost, s_prev)
# ======================================================================

def sample_buyer_price(spec: ProductSpec, s_prev: float | None,
                        rng: random.Random) -> float:
    """
    Round-1 case: no previous seller price yet → sample from [cost, market).
    Round t>=2: sample from [cost, s_prev).

    If s_prev has drifted below cost (unusual — the seller is quoting below
    its own production cost), the interval [cost, s_prev) is empty.  We fall
    back to sampling from [0, s_prev) so the buyer can still respond with
    something below the seller's quote.
    """
    low = spec.cost
    high = s_prev if s_prev is not None else spec.market_price
    if high <= low + 1e-4:
        # s_prev is at or below cost — sample from [0, s_prev) instead.
        low = 0.0
    if high <= low + 1e-4:
        # still degenerate (s_prev essentially 0) — just return a tiny price.
        return round(max(high - 1e-3, 1e-3), 2)
    return round(rng.uniform(low, high), 2)


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

def _buyer_message(product_name: str, price: float, quantity: int,
                   rng: random.Random) -> tuple[str, int]:
    tid = rng.randint(0, len(_BUYER_TEMPLATES) - 1)
    return _BUYER_TEMPLATES[tid].format(
        product=product_name, price=price, qty=quantity), tid


# ======================================================================
# Adaptive switching rule — shared across all 9 switching notebooks
# ======================================================================

# Thresholds on the normalised offer-gap g = (s_prev - m_t) / s_prev.
#   small g  (merchant offers close to seller's last quote)  → reward: cooperative
#   large g  (merchant lowballs far below seller's last quote) → punish: anchor_high
#   middle g → keep the previous strategy ("stay the course")
#
# The rule is a function of (prev_strategy, m_t, s_prev).  prev_strategy
# enters through the "stay" branch when g is in the middle.

TAU_LOW  = 0.25    # below this, merchant is "close enough" → switch to cooperative
TAU_HIGH = 0.60    # above this, merchant is "lowballing"   → switch to anchor_high


def switching_rule(prev_strategy: str, m_t: float, s_prev: float) -> str:
    """
    Pick next-round seller strategy as a function of
    (previous strategy, current buyer price, previous seller price).

    g = (s_prev - m_t) / s_prev  measures how far below the seller's last
    quote the merchant's offer sits, as a fraction of that quote.  It is
    always in [0, 1) because the buyer is constrained to m_t < s_prev.

    Rule:
      g < TAU_LOW   : cooperative
      g > TAU_HIGH  : anchor_high
      otherwise     : keep prev_strategy  (tit_for_tat_matcher by default
                      if prev_strategy is missing)
    """
    if s_prev is None or s_prev <= 1e-6:
        return prev_strategy if prev_strategy else "tit_for_tat_matcher"
    g = (s_prev - m_t) / s_prev
    if g < TAU_LOW:
        return "cooperative"
    if g > TAU_HIGH:
        return "anchor_high"
    return prev_strategy if prev_strategy in ALL_STRATEGIES else "tit_for_tat_matcher"


# ======================================================================
# Supplier system prompt  (deadline-free, identical to 0416b)
# ======================================================================

def build_supplier_prompt(spec: ProductSpec, strategy: str) -> str:
    v = spec.cost + spec.internal_cost
    strategy_text = SUPPLIER_STRATEGY_TEXTS.get(strategy, strategy)
    return f"""\
You are a product supplier (the Supplier) negotiating to sell a product to \
a vending machine operator (the Merchant).

PRODUCT:
  {spec.name}
  Production cost : ${spec.cost:.2f} per unit   (public — both sides know)
  Market price    : ${spec.market_price:.2f} per unit   (public — both sides know)

YOUR PRIVATE INFORMATION (the merchant does NOT know this):
  Internal fulfilment cost : ${spec.internal_cost:.2f} per unit
  Your break-even floor    : ${v:.2f} per unit  (= production cost + fulfilment cost)

  !! CRITICAL — INFORMATION SECRECY !!
  NEVER reveal your internal fulfilment cost or your break-even floor.
  Do not hint at these numbers.

UTILITY:
  Your profit per unit = deal_price − ${v:.2f}
  Total profit = profit_per_unit × quantity
  You want to maximise total profit.  Any deal below ${v:.2f}/unit loses money.

YOUR STRATEGY:
  {strategy_text}

CONVERSATION FORMAT:
  The transcript uses [MERCHANT] and [SUPPLIER] labels.
  You are [SUPPLIER].  Write only your message — do not include the label.

  Your message should read like a natural negotiation response.  You may
  include brief reasoning or justification.

  !! IMPORTANT — PRICE FORMAT !!
  At the VERY END of your message, on a NEW line, state your proposed price
  using EXACTLY this format:

  [PRICE] {spec.name}: $X.XX per unit

  This [PRICE] line MUST be the last line of your response.
  Example:
  [PRICE] {spec.name}: $1.25 per unit
"""


# ======================================================================
# Price extraction (carried over verbatim)
# ======================================================================

def extract_supplier_price(answer: str, product_name: str) -> float | None:
    tag_pattern = (
        r"\[PRICE\]\s*" + re.escape(product_name)
        + r"\s*:\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)"
    )
    m = re.search(tag_pattern, answer, flags=re.IGNORECASE)
    if m: return float(m.group(1).replace(",", ""))
    m = re.search(r"\[PRICE\].*?\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
                  answer, re.IGNORECASE)
    if m: return float(m.group(1).replace(",", ""))
    named = (re.escape(product_name)
             + r"\s*:?\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)")
    matches = list(re.finditer(named, answer, re.IGNORECASE))
    if matches: return float(matches[-1].group(1).replace(",", ""))
    matches = list(re.finditer(
        r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)",
        answer, re.IGNORECASE))
    if matches: return float(matches[-1].group(1).replace(",", ""))
    matches = list(re.finditer(
        r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)", answer, re.IGNORECASE))
    if matches: return float(matches[-1].group(1).replace(",", ""))
    return None


# ======================================================================
# Supplier API call (unchanged from 0416b)
# ======================================================================

def _supplier_call(client, model, system, history, opening=False):
    gpt_mode = _is_gpt_model(model)
    effective_system = system
    user_content = ("The negotiation is starting.  The merchant has made their "
                    "opening offer above.  Provide your counter-offer."
                    if opening else
                    "Given the conversation history and your instructions, "
                    "provide your next negotiation response.")
    if history:
        effective_system = (
            "CONVERSATION HISTORY SO FAR:\n\n" + format_history(history)
            + "\n\n--- END OF CONVERSATION HISTORY ---\n\n" + effective_system)
    if gpt_mode:
        effective_system += _GPT_THINKING_INSTRUCTION
    messages = [{"role": "system", "content": effective_system},
                {"role": "user",   "content": user_content}]
    if gpt_mode:
        api_kwargs = dict(model=model, messages=messages,
                          max_completion_tokens=8192)
    else:
        api_kwargs = dict(model=model, messages=messages, max_tokens=4096,
                          extra_body={"enable_thinking": True,
                                      "thinking_budget": 8192})
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
# Single run (supports both fixed-strategy and switching-rule modes)
# ======================================================================

def run_single(
    client, model: str,
    spec: ProductSpec,
    supplier_id: str, supplier_name: str,
    initial_strategy: str,
    adaptive: bool,
    n_rounds: int = 16,
    rng_seed: int = 0,
    verbose: bool = False,
) -> dict:
    """
    One negotiation trajectory.

    If `adaptive=False` the seller uses `initial_strategy` for every round.
    If `adaptive=True` the strategy for round t is chosen by
    `switching_rule(prev_strategy, m_t, s_prev)` based on round t's merchant
    offer and the seller's quote from round t-1.  Round 1 uses
    `initial_strategy`.
    """
    rng = random.Random(rng_seed)
    v = spec.cost + spec.internal_cost

    history = []
    rounds_log = []
    s_prev: float | None = None
    active_strategy = initial_strategy

    for round_num in range(1, n_rounds + 1):
        # ── Buyer sample (random in [cost, s_prev)) ──
        m_t = sample_buyer_price(spec, s_prev, rng)
        buyer_msg, template_id = _buyer_message(spec.name, m_t, spec.quantity, rng)
        history.append({"speaker": "MERCHANT", "content": buyer_msg})

        # ── Choose seller strategy for this round ──
        if round_num == 1:
            strat_t = initial_strategy
        elif adaptive:
            strat_t = switching_rule(active_strategy, m_t, s_prev)
        else:
            strat_t = initial_strategy

        # ── Seller turn ──
        s_system = build_supplier_prompt(spec, strat_t)
        s_answer, s_reasoning = _supplier_call(
            client, model, s_system, history, opening=(round_num == 1))
        history.append({"speaker": "SUPPLIER", "content": s_answer})
        s_t = extract_supplier_price(s_answer, spec.name)

        if verbose:
            sp_str = f"${s_t:.2f}" if s_t else "FAIL"
            short = s_answer.replace("\n", " ")[:55]
            print(f"  R{round_num:>2} BUY ${m_t:.2f}  "
                  f"SEL {sp_str} [strat={strat_t}]   \"{short}...\"")

        rounds_log.append({
            "round":                      round_num,
            "buyer_price":                m_t,
            "buyer_message":              buyer_msg,
            "template_id":                template_id,
            "buyer_active_strategy":      "random",
            "supplier_active_strategy":   strat_t,
            "supplier_answer":            s_answer,
            "supplier_reasoning":         s_reasoning,
            "supplier_price":             s_t,
            "supplier_system_prompt":     s_system if round_num == 1 else None,
        })

        # Update state for next round
        active_strategy = strat_t
        if s_t is not None:
            s_prev = s_t
        # if s_t fails to parse, keep previous s_prev (buyer will redraw from same bound)

    return {
        "metadata": {
            "model":   model,
            "product": {
                "name":         spec.name,
                "category":     spec.category,
                "cost":         spec.cost,
                "market_price": spec.market_price,
            },
            "supplier": {
                "id":            supplier_id,
                "name":          supplier_name,
                "internal_cost": spec.internal_cost,
            },
            "v":        v,
            "quantity": spec.quantity,
            "buyer_type": {"name": "random",
                           "description":
                               "uniform in [cost, s_prev) each round"},
            "seller_config": {
                "adaptive":         adaptive,
                "initial_strategy": initial_strategy,
                "switching_rule":   {
                    "name":     "gap_thresholds",
                    "formula":  "g=(s_prev-m_t)/s_prev; g<TAU_LOW→coop, g>TAU_HIGH→anchor, else keep",
                    "TAU_LOW":  TAU_LOW,
                    "TAU_HIGH": TAU_HIGH,
                } if adaptive else None,
            },
            "n_rounds":  n_rounds,
            "rng_seed":  rng_seed,
            "timestamp": datetime.datetime.now().isoformat(),
        },
        "rounds": rounds_log,
    }


# ======================================================================
# Batch runner
# ======================================================================

SUPPLIER_POOL = [
    ("S1", "Local distributor"),
    ("S2", "National distributor"),
    ("S3", "Regional wholesaler"),
]


def run_condition(
    client, model: str,
    initial_strategy: str,
    adaptive: bool,
    n_runs: int,
    n_rounds: int = 16,
    base_seed: int = 5000,
    verbose: bool = False,
) -> dict:
    """Run `n_runs` trajectories of a single configuration."""
    runs = []
    for i in range(n_runs):
        seed = base_seed + i
        rng = random.Random(seed)
        spec = sample_product_spec(rng)
        sid, sname = rng.choice(SUPPLIER_POOL)
        if verbose:
            print(f"\n--- Run {i+1}/{n_runs}  seed={seed}  "
                  f"{spec.name}  init={initial_strategy} adaptive={adaptive} ---")
        runs.append(run_single(
            client, model, spec, sid, sname,
            initial_strategy, adaptive, n_rounds, seed, verbose))
    return {
        "condition": {
            "model":            model,
            "initial_strategy": initial_strategy,
            "adaptive":         adaptive,
            "n_runs":           n_runs,
            "n_rounds":         n_rounds,
        },
        "runs": runs,
    }


# ======================================================================
# Save helper
# ======================================================================

def save_json(obj, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)
    print(f"Saved: {path}")
