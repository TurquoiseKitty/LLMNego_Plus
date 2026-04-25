"""
experiments.py — The 12 fixed-strategy experiments for this sweep.

Unlike the original package, this version removes the adaptive / multi-strategy
schedules and runs only 12 *single-strategy* experiments. Each experiment fixes
one seller prompt for all 16 rounds so the resulting trajectories isolate the
pricing pattern induced by that one implicit seller instruction.

Total per-run seed layout:
    seed(exp_idx, car_idx, run_idx)
        = BASE_SEED + exp_idx * 100_000 + car_idx * 1_000 + run_idx

So within-experiment cars never collide and across-experiment strategies are
seeded independently.
"""

from __future__ import annotations

from seller_schedule import SellerSchedule, fixed_schedule
import config


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

N_ROUNDS: int = config.N_ROUNDS
BASE_SEED: int = config.BASE_SEED
N_RUNS_PER_CAR: int = config.N_RUNS_PER_CAR


# ----------------------------------------------------------------------
# Canonical order of the 12 selected Appendix-A seller strategies
# ----------------------------------------------------------------------

STRATEGY_KEYS: list[str] = [
    "fu_high_price_brief_anchor",
    "deng_patient_rational_extractor",
    "vaccaro_warm_high_dominance",
    "liu_mental_model_tactician",
    "chatterjee_aggressive_high_ask",
    "chatterjee_fair_midpoint",
    "chatterjee_passive_gradual",
    "kong_stochastic_sampler",
    "kwon_competitive_reactive_guard",
    "mangla_mirroring_responder",
    "mazur_grim_trigger_punisher",
    "mazur_corridor_keeper",
]


def _build_experiments() -> list[dict]:
    out: list[dict] = []
    for i, strat in enumerate(STRATEGY_KEYS):
        out.append(
            {
                "index": i,
                "tag": f"exp{i:02d}_fixed_{strat}",
                "seller_schedule": fixed_schedule(strat, N_ROUNDS),
                "group": "fixed",
                "replicate": 0,
            }
        )
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
        sched: SellerSchedule = exp["seller_schedule"]
        print(f"{exp['index']:>2}  {exp['tag']}")
        print(f"      group={exp['group']}  rep={exp['replicate']}")
        print(f"      schedule label: {sched.label}")
        print(f"      switches at   : {sched.switch_points}")
        print(f"      unique strats : {sorted(set(sched.schedule))}")
        print()
