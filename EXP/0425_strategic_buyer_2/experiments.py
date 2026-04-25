"""
experiments.py -- The 12 experiments for the 0423 LLM-buyer sweep.

Layout:

  00..05   fixed_<STRATEGY>__vs__natural_buyer
           Each of the 6 seller strategies paired with the single
           `natural_buyer` prompt. Same structure as 0421 exp 00..05, but
           the buyer is now an LLM with the `natural_buyer` persona
           instead of the uniform-random price sampler.

  06..11   fixed_<STRATEGY>__vs__mirror_<STRATEGY>
           Each of the 6 seller strategies paired with the same-name
           buyer-side mirror persona (e.g. seller patient_value_defender
           against buyer patient_value_defender). This is the "buyer
           mirrors the seller" condition.

Each experiment: all 5 cars * N_RUNS_PER_CAR runs * N_ROUNDS rounds.

Seed layout is the same shape as 0421:
    seed(exp_idx, car_idx, run_idx) = BASE_SEED
                                     + exp_idx  * 100_000
                                     + car_idx  *   1_000
                                     + run_idx
so different experiments and different runs are seeded independently.
(Note: with LLMs on both sides the seed is not actually consumed by any
randomness in the conversation itself; it is kept for bookkeeping and in
case a future buyer strategy reintroduces a sampling step.)
"""

from __future__ import annotations

from seller_schedule import fixed_schedule
from buyer_schedule import fixed_buyer_schedule
import config


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

N_ROUNDS:        int = config.N_ROUNDS
BASE_SEED:       int = config.BASE_SEED
N_RUNS_PER_CAR:  int = config.N_RUNS_PER_CAR

# Canonical order of the six seller strategies (same as 0421).
STRATEGY_KEYS: list[str] = [
    "patient_value_defender",
    "busy_impatient_closer",
    "friendly_rapport_builder",
    "reciprocal_fairness_keeper",
    "opponent_aware_diagnostic",
    "market_expert_value_justifier",
]


# ----------------------------------------------------------------------
# Build the 12-experiment list.
# ----------------------------------------------------------------------

def _build_experiments() -> list[dict]:
    out: list[dict] = []

    # --- 00..05 : 6 seller strategies vs. a single natural buyer ---
    for i, seller_strat in enumerate(STRATEGY_KEYS):
        out.append({
            "index":           i,
            "tag":             f"exp{i:02d}_fixed_{seller_strat}__vs__natural_buyer",
            "seller_schedule": fixed_schedule(seller_strat, N_ROUNDS),
            "buyer_schedule":  fixed_buyer_schedule("natural_buyer", N_ROUNDS),
            "group":           "natural_buyer",
            "seller_strategy": seller_strat,
            "buyer_strategy":  "natural_buyer",
            "replicate":       0,
        })

    # --- 06..11 : same 6 seller strategies, mirrored buyer strategy ---
    for j, seller_strat in enumerate(STRATEGY_KEYS):
        i = 6 + j
        out.append({
            "index":           i,
            "tag":             f"exp{i:02d}_fixed_{seller_strat}__vs__mirror_{seller_strat}",
            "seller_schedule": fixed_schedule(seller_strat, N_ROUNDS),
            "buyer_schedule":  fixed_buyer_schedule(seller_strat, N_ROUNDS),
            "group":           "mirror_buyer",
            "seller_strategy": seller_strat,
            "buyer_strategy":  seller_strat,   # same key, buyer-side variant
            "replicate":       0,
        })

    assert len(out) == 12, f"expected 12 experiments, got {len(out)}"
    return out


EXPERIMENTS: list[dict] = _build_experiments()


def experiment_by_index(idx: int) -> dict:
    if not (0 <= idx < len(EXPERIMENTS)):
        raise IndexError(
            f"experiment index {idx} out of range [0, {len(EXPERIMENTS)})"
        )
    return EXPERIMENTS[idx]


if __name__ == "__main__":
    for exp in EXPERIMENTS:
        ss = exp["seller_schedule"]
        bs = exp["buyer_schedule"]
        print(f"{exp['index']:>2}  {exp['tag']}")
        print(f"      group={exp['group']}")
        print(f"      seller : {ss.label}")
        print(f"      buyer  : {bs.label}")
        print()
