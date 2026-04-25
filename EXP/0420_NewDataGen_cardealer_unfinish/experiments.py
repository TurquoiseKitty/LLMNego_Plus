"""
experiments.py — The 12 experiments for this sweep.

Layout of the 12 experiments:

  00..05  fixed_<STRATEGY>            each of the 6 ensemble strategies, one
                                      strategy per experiment, 5 cars each.
  06..08  transition_A  (x3 reps)     warm-open / firm-close two-phase
                                      schedule, 3 independent replicates
                                      (different seeds, same schedule) so the
                                      transition rule accumulates enough
                                      trajectories for downstream analysis.
  09..11  transition_B  (x3 reps)     probe -> market-anchor -> reciprocal-
                                      close three-phase schedule; same
                                      3-replicate pattern, a "slightly more
                                      difficult" rule than transition_A
                                      (two switch points instead of one).

Each experiment exposes all 5 cars (one negotiation per car) at 16 rounds,
so one experiment == 80 seller-LLM calls, and the whole sweep is 960 calls.

Total per-run seed layout:
    seed(exp_idx, car_idx) = BASE_SEED + exp_idx * 1000 + car_idx
so within-experiment cars never collide and across-experiment replicates of
the same schedule are seeded independently.
"""

from __future__ import annotations

from seller_schedule import (
    SellerSchedule,
    fixed_schedule,
    two_phase_schedule,
    three_phase_schedule,
)
import config


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

# Pulled from config.py so a single env var can retune everything.
N_ROUNDS:        int = config.N_ROUNDS
BASE_SEED:       int = config.BASE_SEED
N_RUNS_PER_CAR:  int = config.N_RUNS_PER_CAR

# Canonical order of the six seller strategies from seller_prompt_ensemble.
STRATEGY_KEYS: list[str] = [
    "patient_value_defender",
    "busy_impatient_closer",
    "friendly_rapport_builder",
    "reciprocal_fairness_keeper",
    "opponent_aware_diagnostic",
    "market_expert_value_justifier",
]


# ----------------------------------------------------------------------
# Transition rules
# ----------------------------------------------------------------------

# Transition A — "warm open, firm close", single switch point.
#   Rounds  1.. 8 :  friendly_rapport_builder
#   Rounds  9..16 :  patient_value_defender
TRANSITION_A: SellerSchedule = two_phase_schedule(
    first="friendly_rapport_builder",
    second="patient_value_defender",
    switch_round=9,
    n_rounds=N_ROUNDS,
)

# Transition B — "probe, justify, close", two switch points.
# Deliberately more structure than Transition A: the seller first diagnoses
# the buyer, then anchors with market-expert justification, then closes
# under a reciprocal-fairness frame. Harder to detect a single break point
# because the trajectory has two.
#   Rounds  1.. 5 :  opponent_aware_diagnostic
#   Rounds  6..11 :  market_expert_value_justifier
#   Rounds 12..16 :  reciprocal_fairness_keeper
TRANSITION_B: SellerSchedule = three_phase_schedule(
    s1="opponent_aware_diagnostic",
    s2="market_expert_value_justifier",
    s3="reciprocal_fairness_keeper",
    r1=6, r2=12,
    n_rounds=N_ROUNDS,
)


# ----------------------------------------------------------------------
# Build the 12-experiment list
# ----------------------------------------------------------------------

def _build_experiments() -> list[dict]:
    out: list[dict] = []

    # --- 0..5 : fixed strategies ---
    for i, strat in enumerate(STRATEGY_KEYS):
        out.append({
            "index":           i,
            "tag":             f"exp{i:02d}_fixed_{strat}",
            "seller_schedule": fixed_schedule(strat, N_ROUNDS),
            "group":           "fixed",
            "replicate":       0,
        })

    # --- 6..8 : transition A, 3 replicates ---
    for j in range(3):
        i = 6 + j
        out.append({
            "index":           i,
            "tag":             f"exp{i:02d}_transitionA_rep{j+1}",
            "seller_schedule": TRANSITION_A,
            "group":           "transition_A",
            "replicate":       j + 1,
        })

    # --- 9..11 : transition B, 3 replicates ---
    for j in range(3):
        i = 9 + j
        out.append({
            "index":           i,
            "tag":             f"exp{i:02d}_transitionB_rep{j+1}",
            "seller_schedule": TRANSITION_B,
            "group":           "transition_B",
            "replicate":       j + 1,
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
    # Quick dump for human inspection.
    for exp in EXPERIMENTS:
        sched = exp["seller_schedule"]
        print(f"{exp['index']:>2}  {exp['tag']}")
        print(f"      group={exp['group']}  rep={exp['replicate']}")
        print(f"      schedule label: {sched.label}")
        print(f"      switches at   : {sched.switch_points}")
        print(f"      unique strats : {sorted(set(sched.schedule))}")
        print()
