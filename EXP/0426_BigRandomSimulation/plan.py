"""
plan.py — the 120-cell grid and its partition between user and cooperator.

The full experiment is a factorial over
    POLICIES   (6) x SCHEMES  (4)  x  VEHICLES  (5)
= 120 cells.  Each cell comprises N_RUNS_PER_CAR (= 50) independent negotiation
cycles of length N_ROUNDS (= 12) turns.

Seeding convention
------------------
Each individual negotiation cycle has a seed drawn deterministically from

    seed(p, s, v, r) = BASE_SEED
                     + POLICY_IDX[p]   * 10_000_000
                     + SCHEME_IDX[s]   *  1_000_000
                     + VEHICLE_IDX[v]  *    100_000
                     + r                   # r in [0, N_RUNS_PER_CAR)

The factor hierarchy guarantees no two (p, s, v, r) tuples ever share a seed,
so the user and the cooperator can launch their halves of the grid in
parallel and the resulting JSONs merge cleanly (no double-counted runs, no
collisions in rng state).

Partitioning the grid between user and cooperator
-------------------------------------------------
We split by SCHEME: the user runs schemes A and B (60 cells, 50 * 60 = 3,000
cycles, 36,000 seller calls); the cooperator runs schemes C and D (same).
This is cleaner than an arbitrary partition because a merged dataset is
unambiguous about who generated which rows -- the scheme field in each cell's
JSON identifies it.

At ~200 seller calls / hour / worker, one half = 36,000 / 200 = 180
worker-hours, which finishes in ~6 h on 30 parallel workers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import config


# ----------------------------------------------------------------------
# Canonical orderings (used for deterministic seeding).  DO NOT REORDER.
# ----------------------------------------------------------------------

POLICY_KEYS: list[str] = [
    "patient_value_defender",
    "busy_impatient_closer",
    "friendly_rapport_builder",
    "reciprocal_fairness_keeper",
    "opponent_aware_diagnostic",
    "market_expert_value_justifier",
]
POLICY_IDX: dict[str, int] = {k: i for i, k in enumerate(POLICY_KEYS)}

SchemeKey = Literal["A", "B", "C", "D"]
SCHEME_KEYS: list[SchemeKey] = ["A", "B", "C", "D"]
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
# Partition of the 120-cell grid between user and cooperator
# ----------------------------------------------------------------------

USER_SCHEMES:        list[SchemeKey] = ["A", "B"]
COOPERATOR_SCHEMES:  list[SchemeKey] = ["C", "D"]


def cells_for_side(side: Literal["user", "cooperator"]) -> list[tuple[str, SchemeKey]]:
    """Return the list of (policy, scheme) cells assigned to `side`.

    Each (policy, scheme) cell expands to 5 vehicles x N_RUNS_PER_CAR cycles,
    run together by one worker.  So 6 policies x 2 schemes = 12 cells per
    side, which is a convenient per-side worker count but tied by design to
    the scheme-per-side split; the launcher further splits each cell if you
    request more parallelism than 12 workers.
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

    * one cell = 50 runs * 12 rounds = 600 seller calls
    * at ~200 calls/hour = ~3 h wall clock per cell
    * 60 cells per side, so a single 30-parallel launcher finishes half
      the grid in 2 rounds of (3 h * 2) = 6 h total
    * if we pick a coarser unit (all 5 vehicles per cell) a single worker
      takes ~15 h, which blows the 6 h budget even with 30 parallel slots
    * the finer unit also makes failure recovery cheap: if one cell
      crashes, we only re-run 600 calls, not 3,000

    Each cell writes one self-contained results/<tag>.json file, and the
    final dataset is the concatenation of all 120 such files.
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
    """All worker cells assigned to `side`.  60 per side = 6 policies x 2 schemes x 5 vehicles."""
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
