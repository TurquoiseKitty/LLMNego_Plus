"""
seller_schedule.py — Per-round strategy schedules for the seller agent.

A SellerSchedule answers one question: "for round t, which of the six seller
strategies from seller_prompt_ensemble.STRATEGIES should the prompt render?"

Three builders are provided:

  fixed_schedule(strategy, n_rounds)
      Single strategy for every round of a negotiation.

  two_phase_schedule(first, second, switch_round, n_rounds)
      Use `first` for rounds 1 .. switch_round - 1, then `second` for
      rounds switch_round .. n_rounds.

  three_phase_schedule(s1, s2, s3, r1, r2, n_rounds)
      Three consecutive phases with switch points at r1 and r2.

The SellerSchedule object is immutable, hashable (via tuple), and has a
compact dict view used by the experiment manifest.
"""

from __future__ import annotations

from dataclasses import dataclass

from seller_prompt_ensemble import STRATEGIES


def _validate_strategy(key: str) -> None:
    if key not in STRATEGIES:
        valid = ", ".join(sorted(STRATEGIES))
        raise KeyError(f"Unknown strategy key {key!r}. Valid: {valid}")


@dataclass(frozen=True)
class SellerSchedule:
    label: str
    schedule: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.schedule:
            raise ValueError("SellerSchedule.schedule is empty.")
        for key in self.schedule:
            _validate_strategy(key)

    def strategy_for_round(self, round_num: int) -> str:
        """Clamped lookup: requests past the end of the schedule repeat the last entry."""
        if round_num < 1:
            raise ValueError(f"round_num must be >= 1, got {round_num}")
        idx = min(round_num - 1, len(self.schedule) - 1)
        return self.schedule[idx]

    @property
    def is_adaptive(self) -> bool:
        return len(set(self.schedule)) > 1

    @property
    def switch_points(self) -> list[int]:
        """1-indexed round numbers at which the active strategy changes."""
        out: list[int] = []
        for i in range(1, len(self.schedule)):
            if self.schedule[i] != self.schedule[i - 1]:
                out.append(i + 1)
        return out

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "schedule": list(self.schedule),
            "is_adaptive": self.is_adaptive,
            "switch_points": self.switch_points,
            "unique_strategies": sorted(set(self.schedule)),
        }


def fixed_schedule(strategy: str, n_rounds: int) -> SellerSchedule:
    _validate_strategy(strategy)
    return SellerSchedule(
        label=f"fixed__{strategy}",
        schedule=tuple([strategy] * n_rounds),
    )


def two_phase_schedule(
    first: str,
    second: str,
    switch_round: int,
    n_rounds: int,
) -> SellerSchedule:
    _validate_strategy(first)
    _validate_strategy(second)
    if not (2 <= switch_round <= n_rounds):
        raise ValueError(f"switch_round must be in [2, {n_rounds}], got {switch_round}")
    sched = [first] * (switch_round - 1) + [second] * (n_rounds - switch_round + 1)
    return SellerSchedule(
        label=f"twophase__{first}__to__{second}@r{switch_round}",
        schedule=tuple(sched),
    )


def three_phase_schedule(
    s1: str, s2: str, s3: str,
    r1: int, r2: int,
    n_rounds: int,
) -> SellerSchedule:
    for s in (s1, s2, s3):
        _validate_strategy(s)
    if not (2 <= r1 < r2 <= n_rounds):
        raise ValueError(
            f"require 2 <= r1 < r2 <= n_rounds, got r1={r1}, r2={r2}, n_rounds={n_rounds}"
        )
    sched = (
        [s1] * (r1 - 1)
        + [s2] * (r2 - r1)
        + [s3] * (n_rounds - r2 + 1)
    )
    return SellerSchedule(
        label=f"threephase__{s1}@1_{s2}@{r1}_{s3}@{r2}",
        schedule=tuple(sched),
    )
