"""
buyer_schedule.py -- Per-round strategy schedule for the buyer agent.

Symmetric to seller_schedule.py. In the 0423 experiment every experiment
uses a *fixed* buyer schedule (one strategy for all rounds of a negotiation),
but the same machinery supports two- and three-phase schedules in case later
experiments need them.

Note: the buyer strategy catalog is drawn from buyer_prompt_ensemble, which
includes the 7 keys:
    natural_buyer, patient_value_defender, busy_impatient_closer,
    friendly_rapport_builder, reciprocal_fairness_keeper,
    opponent_aware_diagnostic, market_expert_value_justifier
"""

from __future__ import annotations

from dataclasses import dataclass

from buyer_prompt_ensemble import BUYER_STRATEGIES


def _validate_strategy(key: str) -> None:
    if key not in BUYER_STRATEGIES:
        valid = ", ".join(sorted(BUYER_STRATEGIES))
        raise KeyError(f"Unknown buyer strategy key {key!r}. Valid: {valid}")


@dataclass(frozen=True)
class BuyerSchedule:
    label: str
    schedule: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.schedule:
            raise ValueError("BuyerSchedule.schedule is empty.")
        for key in self.schedule:
            _validate_strategy(key)

    def strategy_for_round(self, round_num: int) -> str:
        if round_num < 1:
            raise ValueError(f"round_num must be >= 1, got {round_num}")
        idx = min(round_num - 1, len(self.schedule) - 1)
        return self.schedule[idx]

    @property
    def is_adaptive(self) -> bool:
        return len(set(self.schedule)) > 1

    @property
    def switch_points(self) -> list[int]:
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


def fixed_buyer_schedule(strategy: str, n_rounds: int) -> BuyerSchedule:
    _validate_strategy(strategy)
    return BuyerSchedule(
        label=f"fixed_buyer__{strategy}",
        schedule=tuple([strategy] * n_rounds),
    )
