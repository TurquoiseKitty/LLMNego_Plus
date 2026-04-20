"""
exp_runner_0416.py — Multi-buyer-type negotiation experiments, v0416b.

Key properties:
  1. CONTINUOUS product parameters: every run samples production_cost,
     market_price, and internal_cost from (product-category-conditioned)
     continuous distributions.
  2. BUYER PRICE CLIPPING: buyer-proposed price is always strictly below
     the seller's most recent quote (otherwise the buyer could just accept
     the previous quote).
  3. NO ROUND/DEADLINE LIMITS.  The supplier prompt does not mention a
     maximum number of rounds, a remaining-round count, or any deadline.
     Neither buyer nor seller uses deadline-aware tactics.  The experiment
     driver still stops after `n_rounds` rounds for logging purposes, but
     that number is NEVER communicated to the seller.
  4. 6 seller prompt strategies chosen to be maximally distinct and
     behaviourally identifiable:
         anchor_high, cooperative, boulware_seller, conceder_seller,
         tit_for_tat_matcher, relational.
  5. 10 buyer strategies (no deadline variant):
         random, budget, wild, concession, anchor_drag,
         boulware_buyer, conceder_buyer, tit_for_tat_buyer,
         persistent_f0.30, persistent_f0.55.
  6. ADAPTIVE strategies: both buyer and seller can switch strategies mid-
     trajectory.  Switches are triggered purely by round index; the seller
     is still never told how many rounds remain.  The active strategy per
     round is recorded for both sides.
"""

from __future__ import annotations

import datetime
import json
import random
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

from NegoLib.Entities.Agents import Supplier  # kept for typing compatibility
from NegoLib.Entities.products import Product  # kept for typing compatibility
from NegoLib.prompt_ensemble import (
    format_history,
    _is_gpt_model,
    _extract_think_tags,
    _GPT_THINKING_INSTRUCTION,
)


# ======================================================================
# Message templates (randomly selected per round)
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


def _buyer_message(product_name: str, price: float, quantity: int,
                   rng: random.Random) -> tuple[str, int]:
    tid = rng.randint(0, len(_BUYER_TEMPLATES) - 1)
    msg = _BUYER_TEMPLATES[tid].format(product=product_name, price=price, qty=quantity)
    return msg, tid


# ======================================================================
# Continuous product / supplier sampling
# ======================================================================
#
# Each category has plausible ranges for:
#   production_cost : wholesale unit cost to the manufacturer
#   markup          : multiplier that yields market_price from cost
#   internal_cost   : supplier's own fulfilment cost per unit
#
# All values are independently resampled per run.  The result is a
# continuous product+supplier scenario that keeps the economics realistic
# while spreading the data across a wide region of (cost, market, v)-space.
# ======================================================================

@dataclass
class ProductSpec:
    """A fully-specified product scenario for one run."""
    name: str
    category: str
    cost: float            # production cost (both sides know)
    market_price: float    # public market price
    internal_cost: float   # supplier's private fulfilment cost
    quantity: int

    @property
    def v(self) -> float:
        """Seller break-even (cost + internal_cost)."""
        return self.cost + self.internal_cost


# Wide, continuous product universe.  Each entry gives a category template
# and a distribution over (cost, markup, internal_cost_frac, quantity).
# We intentionally cover very-cheap-bulk through expensive-low-volume.

PRODUCT_CATEGORIES: list[dict] = [
    # --- Beverages (cheap, high-volume) ---
    {
        "names": ["Cola (330ml)", "Sparkling water (500ml)", "Iced tea (500ml)",
                  "Energy drink (250ml)", "Orange juice (330ml)", "Coffee drink (250ml)"],
        "category": "Beverage",
        "cost_range": (0.20, 0.80),
        "markup_range": (2.5, 6.0),
        "internal_frac_range": (0.8, 2.2),   # of cost
        "qty_range": (40, 120),
    },
    # --- Snacks (cheap, medium volume) ---
    {
        "names": ["Protein bar (60g)", "Chocolate bar (45g)", "Potato chips (50g)",
                  "Trail mix (80g)", "Mixed nuts (100g)", "Cookies (6-pack)"],
        "category": "Snack",
        "cost_range": (0.40, 1.80),
        "markup_range": (2.0, 4.5),
        "internal_frac_range": (0.3, 1.4),
        "qty_range": (30, 80),
    },
    # --- Personal care (mid-price, medium volume) ---
    {
        "names": ["Hand sanitizer (60ml)", "Lip balm", "Facial tissue (pack)",
                  "Face mask (single)", "Wet wipes (20-count)", "Mini deodorant"],
        "category": "PersonalCare",
        "cost_range": (0.50, 2.50),
        "markup_range": (2.2, 4.5),
        "internal_frac_range": (0.4, 1.3),
        "qty_range": (24, 60),
    },
    # --- Convenience electronics (mid-high price, low volume) ---
    {
        "names": ["Earphones (basic)", "Phone charger cable (1m)",
                  "Power bank (5000mAh)", "USB-C adapter", "Bluetooth earbuds",
                  "Portable fan"],
        "category": "Convenience",
        "cost_range": (1.50, 12.00),
        "markup_range": (2.5, 5.0),
        "internal_frac_range": (1.0, 2.5),
        "qty_range": (8, 30),
    },
    # --- OTC / health (mid price, low-medium volume) ---
    {
        "names": ["Pain-relief (blister pack)", "Vitamin C (10-tab)",
                  "Throat lozenges (pack)", "Allergy tabs (blister)",
                  "Bandages (10-count)"],
        "category": "Health",
        "cost_range": (0.80, 3.50),
        "markup_range": (2.5, 5.5),
        "internal_frac_range": (0.6, 1.8),
        "qty_range": (20, 60),
    },
    # --- Stationery / office sundries (cheap-mid, medium volume) ---
    {
        "names": ["Notebook (A5)", "Ballpoint pen (3-pack)",
                  "Sticky-note pad", "Mechanical pencil", "Highlighter (single)"],
        "category": "Stationery",
        "cost_range": (0.30, 2.00),
        "markup_range": (2.0, 4.5),
        "internal_frac_range": (0.4, 1.5),
        "qty_range": (30, 80),
    },
    # --- Fresh / perishable (mid price, short shelf-life = high internal cost) ---
    {
        "names": ["Sandwich (pre-packed)", "Salad bowl", "Fruit cup (200g)",
                  "Yogurt (150g)", "Sushi pack (small)"],
        "category": "Fresh",
        "cost_range": (1.20, 4.50),
        "markup_range": (1.8, 3.2),
        "internal_frac_range": (1.2, 2.8),   # refrigeration/waste pushes this up
        "qty_range": (15, 40),
    },
]


def sample_product_spec(rng: random.Random,
                        category_filter: str | None = None) -> ProductSpec:
    """
    Sample a fully-continuous product scenario.

    If category_filter is given, the category is fixed; otherwise a category
    is chosen uniformly at random.
    """
    if category_filter is None:
        cat = rng.choice(PRODUCT_CATEGORIES)
    else:
        matches = [c for c in PRODUCT_CATEGORIES if c["category"] == category_filter]
        if not matches:
            raise ValueError(f"Unknown category: {category_filter}")
        cat = matches[0]

    name = rng.choice(cat["names"])
    cost = round(rng.uniform(*cat["cost_range"]), 3)
    markup = rng.uniform(*cat["markup_range"])
    market_price = round(cost * markup, 3)
    internal_frac = rng.uniform(*cat["internal_frac_range"])
    internal_cost = round(cost * internal_frac, 3)
    quantity = rng.randint(*cat["qty_range"])

    # Safety: ensure market_price is strictly above break-even so a deal is
    # at least possible.  Resample markup once if needed.
    v = cost + internal_cost
    if market_price <= v * 1.05:
        needed = (v * 1.15) / cost
        markup = max(markup, needed)
        market_price = round(cost * markup, 3)

    return ProductSpec(
        name=name, category=cat["category"],
        cost=cost, market_price=market_price,
        internal_cost=internal_cost, quantity=quantity,
    )


# ======================================================================
# Buyer strategies
# ======================================================================
#
# Every buyer strategy implements `propose_raw` which returns the *intended*
# price for this round (ignoring the clipping rule).  The base class then
# clips against seller's last quote in `sample_price`, guaranteeing the
# buyer never offers ≥ seller's previous price (Requirement 2).
# ======================================================================

_CLIP_EPSILON = 0.01   # buyer's price must be at least this far below seller's


class BuyerStrategy:
    """Base class for buyer price generators."""
    name: str = ""
    description: str = ""

    def propose_raw(self, spec: ProductSpec, round_num: int, n_rounds: int,
                    rng: random.Random,
                    buyer_prices_so_far: list[float],
                    supplier_prices_so_far: list[float | None]) -> float:
        raise NotImplementedError

    def sample_price(self, spec: ProductSpec, round_num: int, n_rounds: int,
                     rng: random.Random,
                     buyer_prices_so_far: list[float],
                     supplier_prices_so_far: list[float | None]) -> float:
        """Returns the actual price proposed this round (post-clipping)."""
        raw = self.propose_raw(spec, round_num, n_rounds, rng,
                               buyer_prices_so_far, supplier_prices_so_far)
        raw = max(_CLIP_EPSILON, round(raw, 2))

        # Clip against the seller's most recent successfully-parsed quote.
        last_seller = None
        for sp in reversed(supplier_prices_so_far):
            if sp is not None:
                last_seller = sp
                break

        if last_seller is not None:
            max_allowed = round(last_seller - _CLIP_EPSILON, 2)
            if max_allowed < _CLIP_EPSILON:
                max_allowed = _CLIP_EPSILON
            if raw >= last_seller:
                raw = max_allowed
        return round(max(_CLIP_EPSILON, raw), 2)

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "type": type(self).__name__}


class RandomBuyer(BuyerStrategy):
    name = "random"
    description = "Uniform random price in [production_cost, market_price]."
    def propose_raw(self, spec, round_num, n_rounds, rng, bh, sh):
        return rng.uniform(spec.cost, spec.market_price)


class BudgetBuyer(BuyerStrategy):
    name = "budget"
    description = "Uniform random price in [0.5*cost, 0.8*market]; cash-constrained buyer."
    def propose_raw(self, spec, round_num, n_rounds, rng, bh, sh):
        low = max(0.01, 0.5 * spec.cost)
        high = max(low + 0.01, 0.8 * spec.market_price)
        return rng.uniform(low, high)


class WildBuyer(BuyerStrategy):
    name = "wild"
    description = "Uniform random in [0, 1.2*market_price] — highly inconsistent."
    def propose_raw(self, spec, round_num, n_rounds, rng, bh, sh):
        return rng.uniform(0.0, 1.2 * spec.market_price)


class PersistentBuyer(BuyerStrategy):
    """Fixed target price with small noise.  The target is expressed as a
    fraction of market_price (resolved at run time) so it generalises across
    the continuous product grid."""
    def __init__(self, price_frac: float):
        self.price_frac = price_frac
        self.name = f"persistent_f{price_frac:.2f}"
        self.description = (f"Fixed target at {price_frac:.0%} of market_price "
                            f"(±$0.02 noise).")

    def propose_raw(self, spec, round_num, n_rounds, rng, bh, sh):
        target = self.price_frac * spec.market_price
        return target + rng.uniform(-0.02, 0.02)

    def to_dict(self):
        d = super().to_dict()
        d["price_frac"] = self.price_frac
        return d


class ConcessionBuyer(BuyerStrategy):
    """Linear concession over [cost, market]: start_frac → end_frac."""
    name = "concession"
    description = "Linear concession from start_frac=0.10 to end_frac=0.60 of [cost, market]."
    def __init__(self, start_frac: float = 0.10, end_frac: float = 0.60):
        self.start_frac = start_frac
        self.end_frac = end_frac

    def propose_raw(self, spec, round_num, n_rounds, rng, bh, sh):
        progress = (round_num - 1) / max(n_rounds - 1, 1)
        frac = self.start_frac + (self.end_frac - self.start_frac) * progress
        zone = spec.market_price - spec.cost
        jitter = rng.uniform(-0.03, 0.03) * zone
        return spec.cost + frac * zone + jitter

    def to_dict(self):
        d = super().to_dict()
        d["start_frac"] = self.start_frac
        d["end_frac"] = self.end_frac
        return d


class AnchorDragBuyer(BuyerStrategy):
    """Very low anchor, tiny upward steps."""
    name = "anchor_drag"
    description = "Anchors 5% above cost; upward step of 3% of [cost,market] per round."
    def __init__(self, anchor_frac: float = 0.05, step_frac: float = 0.03):
        self.anchor_frac = anchor_frac
        self.step_frac = step_frac

    def propose_raw(self, spec, round_num, n_rounds, rng, bh, sh):
        frac = self.anchor_frac + self.step_frac * (round_num - 1)
        zone = spec.market_price - spec.cost
        jitter = rng.uniform(-0.02, 0.02) * zone
        return spec.cost + frac * zone + jitter

    def to_dict(self):
        d = super().to_dict()
        d["anchor_frac"] = self.anchor_frac
        d["step_frac"] = self.step_frac
        return d


class BoulwareBuyer(BuyerStrategy):
    """Concedes extremely slowly (Boulware, exponent >> 1) and only at the end.
    The concession curve is f(t) = start + (end-start) * progress**exponent."""
    name = "boulware_buyer"
    description = "Convex concession curve (exponent=4); most concession concentrated late in the trajectory."
    def __init__(self, start_frac: float = 0.10, end_frac: float = 0.65, exponent: float = 4.0):
        self.start_frac = start_frac
        self.end_frac = end_frac
        self.exponent = exponent

    def propose_raw(self, spec, round_num, n_rounds, rng, bh, sh):
        progress = (round_num - 1) / max(n_rounds - 1, 1)
        frac = self.start_frac + (self.end_frac - self.start_frac) * (progress ** self.exponent)
        zone = spec.market_price - spec.cost
        jitter = rng.uniform(-0.02, 0.02) * zone
        return spec.cost + frac * zone + jitter

    def to_dict(self):
        d = super().to_dict()
        d.update(start_frac=self.start_frac, end_frac=self.end_frac, exponent=self.exponent)
        return d


class ConcederBuyer(BuyerStrategy):
    """Concedes rapidly early, then plateaus (concave, exponent < 1)."""
    name = "conceder_buyer"
    description = "Concave concession curve (exponent=0.35); most concession concentrated early in the trajectory."
    def __init__(self, start_frac: float = 0.10, end_frac: float = 0.65, exponent: float = 0.35):
        self.start_frac = start_frac
        self.end_frac = end_frac
        self.exponent = exponent

    def propose_raw(self, spec, round_num, n_rounds, rng, bh, sh):
        progress = (round_num - 1) / max(n_rounds - 1, 1)
        frac = self.start_frac + (self.end_frac - self.start_frac) * (progress ** self.exponent)
        zone = spec.market_price - spec.cost
        jitter = rng.uniform(-0.02, 0.02) * zone
        return spec.cost + frac * zone + jitter

    def to_dict(self):
        d = super().to_dict()
        d.update(start_frac=self.start_frac, end_frac=self.end_frac, exponent=self.exponent)
        return d


class TitForTatBuyer(BuyerStrategy):
    """Buyer mirrors the *magnitude* of the seller's last concession.

    If the seller drops by Δ, the buyer raises by roughly `match_frac * Δ`.
    When the seller has not yet moved (round 1) the buyer uses anchor_frac.
    """
    name = "tit_for_tat_buyer"
    description = ("Mirrors the seller's last concession: if the seller drops by $X, "
                   "the buyer raises by 0.7*$X.  Anchors at 10% of [cost,market] in round 1.")
    def __init__(self, anchor_frac: float = 0.10, match_frac: float = 0.7,
                 cap_frac: float = 0.75):
        self.anchor_frac = anchor_frac
        self.match_frac = match_frac
        self.cap_frac = cap_frac

    def propose_raw(self, spec, round_num, n_rounds, rng, bh, sh):
        zone = spec.market_price - spec.cost
        jitter = rng.uniform(-0.01, 0.01) * zone

        # Round 1: plant an anchor.
        if round_num == 1 or not bh:
            return spec.cost + self.anchor_frac * zone + jitter

        # Compute seller's last concession (positive = seller dropped).
        valid_sp = [p for p in sh if p is not None]
        if len(valid_sp) >= 2:
            seller_drop = valid_sp[-2] - valid_sp[-1]
        else:
            seller_drop = 0.0

        # Buyer raises by match_frac * max(seller_drop, 0); never lowers.
        raise_amt = self.match_frac * max(seller_drop, 0.0)
        prev_buyer = bh[-1]
        proposed = prev_buyer + raise_amt + jitter

        # Never exceed cap_frac * market_price.
        cap = spec.cost + self.cap_frac * zone
        return min(proposed, cap)

    def to_dict(self):
        d = super().to_dict()
        d.update(anchor_frac=self.anchor_frac, match_frac=self.match_frac,
                 cap_frac=self.cap_frac)
        return d


# ---- Factory helpers for the persistent family ---------------------------

def persistent_buyer_family() -> list[BuyerStrategy]:
    """PersistentBuyers at five fractions of market_price."""
    return [PersistentBuyer(f) for f in (0.15, 0.30, 0.45, 0.60, 0.80)]


# All unique *fixed* buyer types (for indexing / enumeration).
def all_fixed_buyers() -> list[BuyerStrategy]:
    return [
        RandomBuyer(),
        BudgetBuyer(),
        WildBuyer(),
        ConcessionBuyer(),
        AnchorDragBuyer(),
        BoulwareBuyer(),
        ConcederBuyer(),
        TitForTatBuyer(),
        PersistentBuyer(0.30),
        PersistentBuyer(0.55),
    ]


# ======================================================================
# Adaptive buyer — switches strategy at scheduled rounds.
# ======================================================================

class AdaptiveBuyer(BuyerStrategy):
    """
    Composite buyer.  Given a list of sub-strategies and a schedule of
    switch-rounds, delegate `propose_raw` to whichever sub-strategy is
    active for the current round.

    `schedule` is a list of round indices (1-indexed) at which the active
    strategy changes.  At round `schedule[i]` we switch to `substrats[i+1]`.
    Round < schedule[0]  → substrats[0], etc.
    """
    def __init__(self, substrats: list[BuyerStrategy], schedule: list[int],
                 label: str | None = None):
        assert len(schedule) == len(substrats) - 1, "schedule has one less element than substrats"
        self.substrats = substrats
        self.schedule = schedule
        sub_names = [s.name for s in substrats]
        self.name = label or ("adaptive__" + "__".join(sub_names))
        self.description = (f"Adaptive buyer that cycles through "
                            f"{sub_names} switching at rounds {schedule}.")

    def _active_idx(self, round_num: int) -> int:
        idx = 0
        for s in self.schedule:
            if round_num >= s:
                idx += 1
        return idx

    def propose_raw(self, spec, round_num, n_rounds, rng, bh, sh):
        idx = self._active_idx(round_num)
        return self.substrats[idx].propose_raw(spec, round_num, n_rounds, rng, bh, sh)

    def active_name(self, round_num: int) -> str:
        return self.substrats[self._active_idx(round_num)].name

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "type": "AdaptiveBuyer",
            "substrategies": [s.to_dict() for s in self.substrats],
            "schedule": list(self.schedule),
        }


# ======================================================================
# Seller strategy texts (used to format the supplier system prompt).
# ======================================================================
#
# These override / extend NegoLib.Entities.strategies.ALL_SUPPLIER_STRATEGIES
# so that the new tactics are available without editing the library.

SUPPLIER_STRATEGY_TEXTS: dict[str, str] = {
    # Six maximally-distinct, deadline-free strategies.
    # No reference to remaining rounds, closing rounds, or deadlines.

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

    "boulware_seller": (
        "Hold your price near the top of the reasonable range.  Concede very "
        "little per turn — a few cents at most — even when the merchant "
        "pushes hard.  You would rather defend margin than agree quickly.  "
        "Do NOT reference any time limit; just stay firm at a high price."
    ),

    "conceder_seller": (
        "Concede generously, especially early.  Your first few counter-offers "
        "should each drop by a noticeable amount below your previous quote, "
        "signalling flexibility and willingness to deal.  As your price "
        "approaches a reasonable margin above your break-even, slow the rate "
        "of concession so you don't give away more than necessary."
    ),

    "tit_for_tat_matcher": (
        "Mirror the merchant.  If they raised their last offer by $X, you "
        "lower yours by roughly $X.  If they barely moved, you barely move. "
        "If they make a very low offer, respond with a matchingly stiff "
        "counter-offer.  Your behaviour is reactive, not planned."
    ),

    "relational": (
        "Negotiate as a trusted long-term partner, not a one-off seller. "
        "Explicitly frame concessions as investments in the ongoing "
        "relationship — mention reliability, future orders, and partnership. "
        "Prefer a stable, moderately-profitable deal over an aggressive win.  "
        "Concessions are moderate but always accompanied by relational "
        "language."
    ),
}


ALL_SUPPLIER_STRATEGIES_V0416 = list(SUPPLIER_STRATEGY_TEXTS.keys())


# ======================================================================
# Adaptive seller controller
# ======================================================================

@dataclass
class SellerSchedule:
    """
    Per-round seller strategy schedule.

    If `schedule` is a single string, that strategy is used for all rounds.
    If `schedule` is a list of strings of length n_rounds, element i gives the
    strategy active in round i+1.  Lists of length < n_rounds are left-
    extended to n_rounds by repeating the last entry.
    """
    schedule: list[str]
    label: str = ""

    def strategy_for(self, round_num: int, n_rounds: int) -> str:
        if not self.schedule:
            raise ValueError("empty seller schedule")
        if round_num - 1 < len(self.schedule):
            return self.schedule[round_num - 1]
        return self.schedule[-1]

    @property
    def is_adaptive(self) -> bool:
        return len(set(self.schedule)) > 1

    def to_dict(self) -> dict:
        return {"label": self.label or "__".join(self.schedule),
                "schedule": list(self.schedule),
                "is_adaptive": self.is_adaptive}


def fixed_seller_schedule(strategy: str, n_rounds: int) -> SellerSchedule:
    return SellerSchedule(schedule=[strategy] * n_rounds, label=strategy)


def twostage_seller_schedule(first: str, second: str,
                             switch_round: int,
                             n_rounds: int) -> SellerSchedule:
    """first for rounds 1..switch_round-1, second for switch_round..n_rounds."""
    sched = [first] * (switch_round - 1) + [second] * (n_rounds - switch_round + 1)
    return SellerSchedule(schedule=sched, label=f"{first}__then__{second}@r{switch_round}")


def threestage_seller_schedule(s1: str, s2: str, s3: str,
                               r1: int, r2: int, n_rounds: int) -> SellerSchedule:
    sched = ([s1] * (r1 - 1)
             + [s2] * (r2 - r1)
             + [s3] * (n_rounds - r2 + 1))
    return SellerSchedule(schedule=sched,
                          label=f"{s1}@1..{s2}@{r1}..{s3}@{r2}")


# ======================================================================
# Supplier prompt builder (now takes a strategy text directly).
# ======================================================================

def build_supplier_prompt(
    supplier_id: str, supplier_name: str,
    spec: ProductSpec, strategy: str,
) -> str:
    """
    Supplier system prompt, deadline-free.

    The prompt does NOT mention the round number, any "remaining rounds"
    count, or any deadline.  The negotiation runs as an open-ended dialog
    from the seller's point of view — the experiment driver stops it
    externally for logging, but never tells the seller that it will.
    """
    v = spec.cost + spec.internal_cost
    strategy_text = SUPPLIER_STRATEGY_TEXTS.get(strategy, strategy)

    prompt = f"""\
You are a product supplier (the Supplier) negotiating to sell a product to \
a vending machine operator (the Merchant).

PRODUCT:
  {spec.name}
  Category        : {spec.category}
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
    return prompt


# ======================================================================
# Price extraction (unchanged from 0413)
# ======================================================================

def extract_supplier_price(answer: str, product_name: str) -> float | None:
    tag_pattern = (
        r"\[PRICE\]\s*" + re.escape(product_name)
        + r"\s*:\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)"
    )
    m = re.search(tag_pattern, answer, flags=re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))

    m = re.search(r"\[PRICE\].*?\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)", answer, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))

    named = (re.escape(product_name)
             + r"\s*:?\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)")
    matches = list(re.finditer(named, answer, re.IGNORECASE))
    if matches:
        return float(matches[-1].group(1).replace(",", ""))

    matches = list(re.finditer(
        r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:per\s*unit|/\s*unit)",
        answer, re.IGNORECASE))
    if matches:
        return float(matches[-1].group(1).replace(",", ""))

    matches = list(re.finditer(
        r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)", answer, re.IGNORECASE))
    if matches:
        return float(matches[-1].group(1).replace(",", ""))

    return None


# ======================================================================
# Supplier API call (unchanged from 0413)
# ======================================================================

def _supplier_call(client, model, system, history, opening=False):
    gpt_mode = _is_gpt_model(model)

    if opening:
        effective_system = system
        user_content = ("The negotiation is starting.  The merchant has made their "
                        "opening offer above.  Provide your counter-offer.")
    else:
        effective_system = system
        user_content = ("Given the conversation history and your instructions, "
                        "provide your next negotiation response.")

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
    client, model: str,
    spec: ProductSpec,
    supplier_id: str, supplier_name: str,
    seller_schedule: SellerSchedule,
    buyer: BuyerStrategy,
    n_rounds: int = 12, rng_seed: int = 0,
    verbose: bool = False,
) -> dict:
    """One negotiation trajectory."""
    rng = random.Random(rng_seed)
    v = spec.cost + spec.internal_cost

    history = []
    rounds_log = []
    buyer_prices: list[float] = []
    supplier_prices: list[float | None] = []

    for round_num in range(1, n_rounds + 1):
        # ── Buyer turn (with seller-clipping) ──
        buyer_price = buyer.sample_price(spec, round_num, n_rounds, rng,
                                         buyer_prices, supplier_prices)
        buyer_msg, template_id = _buyer_message(spec.name, buyer_price, spec.quantity, rng)
        history.append({"speaker": "MERCHANT", "content": buyer_msg})
        buyer_prices.append(buyer_price)

        # Record buyer sub-strategy if adaptive.
        active_buyer_sub = (buyer.active_name(round_num)
                            if isinstance(buyer, AdaptiveBuyer) else buyer.name)

        if verbose:
            print(f"  R{round_num:>2} BUY ${buyer_price:.2f} "
                  f"T{template_id} [buy={active_buyer_sub}]", end="")

        # ── Seller turn ──
        seller_strat = seller_schedule.strategy_for(round_num, n_rounds)
        s_system = build_supplier_prompt(supplier_id, supplier_name, spec,
                                         seller_strat)
        s_answer, s_reasoning = _supplier_call(client, model, s_system, history,
                                               opening=(round_num == 1))
        history.append({"speaker": "SUPPLIER", "content": s_answer})

        supplier_price = extract_supplier_price(s_answer, spec.name)
        supplier_prices.append(supplier_price)

        if verbose:
            sp = f"${supplier_price:.2f}" if supplier_price else "FAIL"
            ans_short = s_answer.replace("\n", " ")[:60]
            print(f"  SEL {sp} [sel={seller_strat}]  \"{ans_short}...\"")

        rounds_log.append({
            "round": round_num,
            "buyer_price": buyer_price,
            "buyer_message": buyer_msg,
            "template_id": template_id,
            "buyer_active_strategy": active_buyer_sub,
            "supplier_active_strategy": seller_strat,
            "supplier_answer": s_answer,
            "supplier_reasoning": s_reasoning,
            "supplier_price": supplier_price,
            "supplier_system_prompt": s_system if round_num == 1 else None,
        })

    return {
        "metadata": {
            "model": model,
            "product": {
                "name": spec.name,
                "category": spec.category,
                "cost": spec.cost,
                "market_price": spec.market_price,
            },
            "supplier": {
                "id": supplier_id,
                "name": supplier_name,
                "internal_cost": spec.internal_cost,
            },
            "v": v,
            "quantity": spec.quantity,
            "buyer_type": buyer.to_dict(),
            "seller_schedule": seller_schedule.to_dict(),
            "n_rounds": n_rounds,
            "rng_seed": rng_seed,
            "timestamp": datetime.datetime.now().isoformat(),
        },
        "rounds": rounds_log,
    }


# ======================================================================
# Batch runner for one condition
# ======================================================================
#
# A "condition" here is (buyer, seller_schedule).  For each run within a
# condition, we sample a NEW ProductSpec (→ continuous cost/market/internal)
# and a NEW synthetic supplier id from a pool.  This gives diversity in the
# economic scenario while still holding the strategic condition fixed.
# ======================================================================

SUPPLIER_POOL = [
    ("S1", "Local distributor"),
    ("S2", "National distributor"),
    ("S3", "Regional wholesaler"),
    ("S4", "Direct-from-manufacturer"),
    ("S5", "Boutique importer"),
]


def run_condition(
    client, model: str,
    buyer: BuyerStrategy,
    seller_schedule: SellerSchedule,
    n_runs: int = 5, n_rounds: int = 12, base_seed: int = 5000,
    category_filter: str | None = None,
    verbose: bool = False,
) -> dict:
    runs = []
    for i in range(n_runs):
        seed = base_seed + i
        rng = random.Random(seed)
        spec = sample_product_spec(rng, category_filter=category_filter)
        supplier_id, supplier_name = rng.choice(SUPPLIER_POOL)
        if verbose:
            print(f"\n  --- Run {i+1}/{n_runs}  seed={seed}  "
                  f"prod={spec.name} cost=${spec.cost:.2f} "
                  f"mkt=${spec.market_price:.2f} int=${spec.internal_cost:.2f} ---")
        run = run_single(client, model, spec, supplier_id, supplier_name,
                         seller_schedule, buyer, n_rounds, seed, verbose)
        runs.append(run)
    return {
        "condition": {
            "model": model,
            "buyer_type": buyer.to_dict(),
            "seller_schedule": seller_schedule.to_dict(),
            "n_runs": n_runs, "n_rounds": n_rounds,
            "category_filter": category_filter,
        },
        "runs": runs,
    }


# ======================================================================
# Transition builder
# ======================================================================

def build_transitions(experiment: dict) -> list[dict]:
    """One transition per round t (t>=2): (s_{t-1}, m_t) -> s_t."""
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
                "model": meta["model"],
                "product": meta["product"]["name"],
                "category": meta["product"]["category"],
                "supplier_id": meta["supplier"]["id"],
                "quantity": meta["quantity"],

                "buyer_type": meta["buyer_type"]["name"],
                "buyer_active_strategy": curr.get("buyer_active_strategy"),

                "seller_schedule_label": meta["seller_schedule"]["label"],
                "seller_is_adaptive": meta["seller_schedule"]["is_adaptive"],
                "supplier_active_strategy_prev": prev.get("supplier_active_strategy"),
                "supplier_active_strategy_curr": curr.get("supplier_active_strategy"),

                "template_id": curr.get("template_id", -1),
            })
    return transitions


# ======================================================================
# Save helpers
# ======================================================================

def save_json(obj, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=_json_default)
    print(f"Saved: {path}")


def _json_default(o):
    if isinstance(o, (datetime.datetime, datetime.date)):
        return o.isoformat()
    if hasattr(o, "to_dict"):
        return o.to_dict()
    raise TypeError(f"not serialisable: {type(o)}")


def inspect_run(run, max_chars=300):
    meta = run["metadata"]
    print(f"  Product: {meta['product']['name']}  "
          f"Supplier: {meta['supplier']['name']}  "
          f"v={meta['v']:.2f}  "
          f"schedule={meta['seller_schedule']['label']}")
    print(f"  Buyer: {meta['buyer_type']['name']}  Model: {meta['model']}")
    print()
    for r in run["rounds"]:
        bp = r["buyer_price"]
        sp = r["supplier_price"]
        sp_str = f"${sp:.2f}" if sp else "FAIL"
        ans = r["supplier_answer"]
        ans_show = ans[:max_chars] + "..." if len(ans) > max_chars else ans
        buy_s = r.get("buyer_active_strategy", "?")
        sel_s = r.get("supplier_active_strategy", "?")
        print(f"  R{r['round']:>2} BUY ${bp:.2f} [{buy_s}]  "
              f"SEL {sp_str} [{sel_s}]")
        print(f"       {ans_show}")
        print()
