"""
run_all_0413.py — Master experiment runner for EXP/0413.

Grid:
  Products (3):  Sparkling water, Cola, Protein bar
  Suppliers (2): LOCAL (S1), NATIONAL (S2)
  Buyer types (8): random, wild,
                   persistent@5_levels,
                   concession, anchor_drag
  Seller strategies (6): cooperative, anchor_high, gradual_conceder,
                          tit_for_tat_matcher, fairness_responder,
                          walk_away_shutdown

Fixed: model=deepseek-reasoner, n_rounds=12, n_runs=5

Output layout:
  results/<seller_strategy>/<buyer_type>__<product_short>__<supplier_id>.json
  results/<seller_strategy>/<buyer_type>__all_transitions.json

Usage:
  # Run everything:
    python run_all_0413.py

  # Run one seller strategy:
    python run_all_0413.py cooperative

  # Run one seller strategy + one buyer type:
    python run_all_0413.py cooperative random
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI

from NegoLib.Entities.Agents import LOCAL_SUPPLIER, NATIONAL_SUPPLIER
from NegoLib.Entities.products import SPARKLING_WATER, COLA, PROTEIN_BAR

from exp_runner_0413 import (
    RandomBuyer, WildBuyer, PersistentBuyer,
    ConcessionBuyer, AnchorDragBuyer,
    run_condition, build_transitions, save_json,
)

# ═══════════════════════════════════════════════════════════════
# CONFIG — edit these
# ═══════════════════════════════════════════════════════════════
CLIENT = OpenAI(
    api_key="YOUR_DEEPSEEK_KEY",         # <-- replace
    base_url="https://api.deepseek.com",
)
MODEL = "deepseek-reasoner"
N_RUNS = 5
N_ROUNDS = 12
BASE_SEED = 5000

OUTPUT_ROOT = Path(__file__).parent / "results"

# ═══════════════════════════════════════════════════════════════
# Product × Supplier grid
# ═══════════════════════════════════════════════════════════════
PRODUCTS = [
    (SPARKLING_WATER, 24),
    (COLA,            60),
    (PROTEIN_BAR,     40),
]

SUPPLIERS = [LOCAL_SUPPLIER, NATIONAL_SUPPLIER]

PRODUCT_SHORT = {
    "Sparkling water (500ml)": "sparkling",
    "Cola (330ml)":            "cola",
    "Protein bar (60g)":       "protein",
}

# ═══════════════════════════════════════════════════════════════
# Buyer types
# ═══════════════════════════════════════════════════════════════
def _build_buyers():
    buyers = {}

    # 1. Random buyer: Uniform(cost, market)
    buyers["random"] = RandomBuyer()

    # 2. Wild buyer: Uniform(0, 2*market)
    buyers["wild"] = WildBuyer()

    # 3. Persistent buyers at 5 price levels
    #    Levels are fractions of market_price: 0.2, 0.4, 0.6, 0.8, 1.2
    #    Actual price = frac * market_price, computed per-product in the loop
    #    We use a lambda-like approach: store frac, compute price at run time
    #    → handled specially in the run loop below
    for frac in [0.2, 0.4, 0.6, 0.8, 1.2]:
        buyers[f"persistent_frac{frac:.1f}"] = frac  # sentinel: resolved per-product

    # 4. Concession buyer: starts low, concedes upward
    buyers["concession"] = ConcessionBuyer(start_frac=0.1, end_frac=0.6)

    # 5. Anchor-drag buyer: low anchor, tiny steps
    buyers["anchor_drag"] = AnchorDragBuyer(anchor_frac=0.05, step_frac=0.03)

    return buyers


BUYER_SPECS = _build_buyers()

# ═══════════════════════════════════════════════════════════════
# Seller strategies
# ═══════════════════════════════════════════════════════════════
ALL_STRATEGIES = [
    "cooperative",
    "anchor_high",
    "gradual_conceder",
    "tit_for_tat_matcher",
    "fairness_responder",
    "walk_away_shutdown",
]


# ═══════════════════════════════════════════════════════════════
# Main loop
# ═══════════════════════════════════════════════════════════════
def run_one_strategy(strategy: str, buyer_filter: str | None = None):
    """Run all buyer × product × supplier conditions for one seller strategy."""
    strat_dir = OUTPUT_ROOT / strategy
    strat_dir.mkdir(parents=True, exist_ok=True)

    for buyer_name, buyer_spec in BUYER_SPECS.items():
        if buyer_filter and buyer_name != buyer_filter:
            continue

        all_transitions_for_buyer = []

        for product, qty in PRODUCTS:
            pshort = PRODUCT_SHORT.get(product.name, product.name[:8])

            for supplier in SUPPLIERS:
                # Resolve persistent buyers to actual price
                if isinstance(buyer_spec, float):
                    # buyer_spec is a fraction of market_price
                    actual_price = round(buyer_spec * product.market_price, 2)
                    buyer = PersistentBuyer(fixed_price=actual_price)
                else:
                    buyer = buyer_spec

                v = product.cost + supplier.internal_costs.for_category(product.category)
                tag = f"{buyer_name}__{pshort}__{supplier.id}"
                print(f"\n{'='*60}")
                print(f"  Strategy={strategy}  Buyer={buyer_name}  "
                      f"Product={pshort}  Supplier={supplier.id}  v={v:.2f}")
                print(f"{'='*60}")

                experiment = run_condition(
                    client=CLIENT, model=MODEL,
                    product=product, quantity=qty,
                    supplier=supplier, strategy=strategy,
                    buyer=buyer,
                    n_runs=N_RUNS, n_rounds=N_ROUNDS,
                    base_seed=BASE_SEED,
                    verbose=True,
                )

                # Save per-condition file
                save_json(experiment, strat_dir / f"{tag}.json")

                # Collect transitions
                trans = build_transitions(experiment)
                all_transitions_for_buyer.extend(trans)

        # Save merged transitions for this buyer type
        if all_transitions_for_buyer:
            save_json(
                {"strategy": strategy, "buyer_type": buyer_name,
                 "n_transitions": len(all_transitions_for_buyer),
                 "transitions": all_transitions_for_buyer},
                strat_dir / f"{buyer_name}__all_transitions.json",
            )
            print(f"\n  [{strategy}/{buyer_name}] Total transitions: {len(all_transitions_for_buyer)}")


def main():
    # Parse CLI arguments
    strategy_filter = None
    buyer_filter = None
    if len(sys.argv) >= 2:
        strategy_filter = sys.argv[1]
    if len(sys.argv) >= 3:
        buyer_filter = sys.argv[2]

    strategies = [strategy_filter] if strategy_filter else ALL_STRATEGIES

    for strategy in strategies:
        print(f"\n{'#'*70}")
        print(f"  SELLER STRATEGY: {strategy}")
        print(f"{'#'*70}")
        run_one_strategy(strategy, buyer_filter)

    print(f"\n\nAll experiments complete.  Results in: {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
