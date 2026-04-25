"""
plan.py — the worker-cell grid for the buyer-scheme E sweep.

This run is a factorial over
    POLICIES   (12) x SCHEMES  (1: E)  x  VEHICLES  (5)
= 60 cells.  Each cell comprises N_RUNS_PER_CAR (= 10) independent negotiation
cycles of length N_ROUNDS (= 20) turns.

Seeding convention
------------------
Each individual negotiation cycle has a seed drawn deterministically from

    seed(p, s, v, r) = BASE_SEED
                     + POLICY_IDX[p]   * 10_000_000
                     + SCHEME_IDX[s]   *  1_000_000
                     + VEHICLE_IDX[v]  *    100_000
                     + r                   # r in [0, N_RUNS_PER_CAR)

The factor hierarchy guarantees no two (p, s, v, r) tuples ever share a seed.

Partitioning
------------
Scheme is fixed to E, so the user side carries the full grid and the cooperator
side is intentionally empty to avoid duplicate runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import config


# ----------------------------------------------------------------------
# Canonical orderings (used for deterministic seeding).  DO NOT REORDER.
# ----------------------------------------------------------------------

POLICY_KEYS: list[str] = [
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
POLICY_IDX: dict[str, int] = {k: i for i, k in enumerate(POLICY_KEYS)}

SchemeKey = Literal["E"]
SCHEME_KEYS: list[SchemeKey] = ["E"]
SCHEME_IDX: dict[str, int] = {k: i for i, k in enumerate(SCHEME_KEYS)}

# Vehicle ordering matches fleet.py (Mercedes, Cadillac, Honda, Toyota, Ford).
VEHICLE_IDX: dict[str, int] = {
    "2014 Mercedes-Benz S550":       0,
    "2016 Cadillac CTS 3.6 Luxury":  1,
    "2019 Honda Accord Sport 1.5T":  2,
    "2022 Toyota RAV4 XLE AWD":      3,
    "2023 Ford Mustang GT Premium":  4,
}


# ----------------------------------------------------------------------
# Partition of the E-only grid between user and cooperator
# ----------------------------------------------------------------------

USER_SCHEMES:        list[SchemeKey] = ["E"]
COOPERATOR_SCHEMES:  list[SchemeKey] = []


def cells_for_side(side: Literal["user", "cooperator"]) -> list[tuple[str, SchemeKey]]:
    """Return the list of (policy, scheme) cells assigned to `side`.

    Each (policy, scheme) cell expands to 5 vehicles x N_RUNS_PER_CAR cycles,
    run together by one worker.  With scheme fixed to E, the user side has
    12 policies x 1 scheme = 12 (policy, scheme) cells; cooperator has none.
    """
    schemes = USER_SCHEMES if side == "user" else COOPERATOR_SCHEMES
    return [(p, s) for p in POLICY_KEYS for s in schemes]


# ----------------------------------------------------------------------
# Finer-grained cell = one worker unit when we need more parallelism
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class WorkerCell:
    """One scheduling unit for a worker.

    A worker processes ONE (policy, scheme, vehicle) combination.
    Rationale for this granularity:

    * one cell = 10 runs * 20 rounds = 200 seller calls
    * at ~200 calls/hour = ~1.0 h wall clock per cell
    * 60 cells in the E-only user sweep
    * a single 30-parallel launcher finishes in roughly two 1.0 h waves
    * if we pick a coarser unit (all 5 vehicles per cell) a single worker
      takes ~5 h, which can still be too slow for quick iteration
    * the finer unit also makes failure recovery cheap: if one cell
      crashes, we only re-run 200 calls, not 1,000

    Each cell writes one self-contained results/<tag>.json file, and the
    final E-only dataset is the concatenation of all 60 such files.
    """
    policy:       str
    scheme:       SchemeKey
    vehicle_idx:  int          # 0..4
    side:         Literal["user", "cooperator"]
    tag:          str = field(init=False)

    def __post_init__(self) -> None:
        # object.__setattr__ is the frozen-dataclass way to set a field.
        object.__setattr__(
            self, "tag",
            f"{self.side[:4]}_{self.scheme}_{self.policy}_v{self.vehicle_idx+1}",
        )


def worker_cells_for_side(side: Literal["user", "cooperator"]) -> list[WorkerCell]:
    """All worker cells assigned to `side`. 60 user cells = 12 policies x 1 scheme x 5 vehicles."""
    return [
        WorkerCell(policy=p, scheme=s, vehicle_idx=v, side=side)
        for (p, s) in cells_for_side(side)
        for v in range(len(VEHICLE_IDX))
    ]


# ----------------------------------------------------------------------
# Deterministic seeding
# ----------------------------------------------------------------------

def run_seed(policy: str, scheme: SchemeKey, vehicle_idx: int, run_idx: int) -> int:
    """Seed for the (policy, scheme, vehicle, run) negotiation cycle.

    Using distinct powers-of-10 multipliers for each factor ensures a unique
    integer per tuple without collisions.  The base seed is fixed in
    config.BASE_SEED so independent launches reproduce identical data.
    """
    if scheme not in SCHEME_IDX:
        raise ValueError(f"unknown scheme {scheme!r}")
    if policy not in POLICY_IDX:
        raise ValueError(f"unknown policy {policy!r}")
    if not (0 <= vehicle_idx < len(VEHICLE_IDX)):
        raise ValueError(f"vehicle_idx out of range: {vehicle_idx}")
    return (
        config.BASE_SEED
        + POLICY_IDX[policy]      * 10_000_000
        + SCHEME_IDX[scheme]      *  1_000_000
        + vehicle_idx             *    100_000
        + run_idx
    )


# ----------------------------------------------------------------------
# Diagnostic: print the plan
# ----------------------------------------------------------------------

def _fmt(cells: list[WorkerCell]) -> str:
    return "\n".join(
        f"  {i:>3d}  {c.tag:<60s}  policy={c.policy:<35s}  scheme={c.scheme}"
        for i, c in enumerate(cells)
    )


if __name__ == "__main__":
    print("Experiment plan")
    print("=" * 78)
    print(f"  policies        : {len(POLICY_KEYS)}  {POLICY_KEYS}")
    print(f"  schemes         : {len(SCHEME_KEYS)}  {SCHEME_KEYS}")
    print(f"  vehicles        : {len(VEHICLE_IDX)}")
    print(f"  runs per car    : {config.N_RUNS_PER_CAR}")
    print(f"  rounds per run  : {config.N_ROUNDS}")
    total_cycles = (len(POLICY_KEYS) * len(SCHEME_KEYS) * len(VEHICLE_IDX)
                    * config.N_RUNS_PER_CAR)
    total_calls  = total_cycles * config.N_ROUNDS
    print(f"  total cycles    : {total_cycles:,}")
    print(f"  total calls     : {total_calls:,}")
    print()
    print(f"User worker cells  ({len(worker_cells_for_side('user'))}):")
    print(_fmt(worker_cells_for_side("user")))
    print()
    print(f"Cooperator worker cells ({len(worker_cells_for_side('cooperator'))}):")
    print(_fmt(worker_cells_for_side("cooperator")))
