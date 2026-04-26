"""
buyer_schemes_trial.py -- Trial buyer-bid generators.

These trial schemes are modeled on the existing Scheme E style interface:
- `init_state(rng, vehicle, T) -> dict`
- `sample_bid(state, rng, t, B_prev, S_prev) -> float`

Implemented trial schemes:
A. E-style B1, then:
   - if seller ask is decreasing: buyer +10
   - if seller ask is stalled (non-decreasing) for more than 2 rounds:
     buyer +1000 each round while the stall continues
B. Buyer starts at 0, then +1000 each round.
C. E-style B1, then +10 each round.

For t >= 2, bids are clipped to [0, S_{t-1}] when there is room to move,
and kept weakly monotone in the buyer's standing offer.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable


# ----------------------------------------------------------------------
# Shared utilities
# ----------------------------------------------------------------------

def _clip(x: float, lo: float, hi: float) -> float:
    if hi < lo:
        return lo
    return max(lo, min(hi, x))


_E_B1_CENTER: float = 0.10
_E_B1_NOISE_SCALE: float = 0.01
_E_B2_CENTER: float = 0.20
_E_B2_NOISE_SCALE: float = 0.02
_E_PRE_STALL_ADD_FRAC_LO: float = 0.04
_E_PRE_STALL_ADD_FRAC_HI: float = 0.06
_E_SMALL_SELLER_DROP_FRAC: float = 0.01
_E_JUMP_FRAC_LO: float = 0.35
_E_JUMP_FRAC_HI: float = 0.55
_E_POST_STALL_ADD_FRAC_LO: float = 0.04
_E_POST_STALL_ADD_FRAC_HI: float = 0.07
_E_POST_STALL_DECAY_LO: float = 0.70
_E_POST_STALL_DECAY_HI: float = 0.90


def _sample_E_style_B1(rng: random.Random, M: float) -> float:
    """B1 sampled the same way as Scheme E in buyer_schemes.py."""
    M = float(M)
    noise = rng.uniform(-_E_B1_NOISE_SCALE * M, +_E_B1_NOISE_SCALE * M)
    return _clip(_E_B1_CENTER * M + noise, lo=0.0, hi=max(M, 0.0))


# ----------------------------------------------------------------------
# Trial Strategy A
# ----------------------------------------------------------------------

def _A_init(rng: random.Random, vehicle: dict, T: int) -> dict:
    return {
        "scheme": "A",
        "M": float(vehicle["market_price_new"]),
        "v": float(vehicle["dealer_cost"]),
        "T": int(T),
        "B1": _sample_E_style_B1(rng, vehicle["market_price_new"]),
        # E-style internal state:
        "last_S": None,
        "second_last_S": None,
        "stall_seen": False,
        "jump_done": False,
        "jump_frac": rng.uniform(_E_JUMP_FRAC_LO, _E_JUMP_FRAC_HI),
        "post_stall_add_frac": rng.uniform(
            _E_POST_STALL_ADD_FRAC_LO, _E_POST_STALL_ADD_FRAC_HI
        ),
        "post_stall_decay": rng.uniform(_E_POST_STALL_DECAY_LO, _E_POST_STALL_DECAY_HI),
        "last_post_stall_add": None,
    }


def _A_sample(
    state: dict,
    rng: random.Random,
    t: int,
    B_prev: float | None,
    S_prev: float | None,
) -> float:
    if t == 1:
        return state["B1"]

    assert B_prev is not None and S_prev is not None

    B_prev_f = float(B_prev)
    S = float(S_prev)
    upper = max(S, 0.0)
    post_stall_increment = False

    if upper <= B_prev_f:
        state["second_last_S"] = state.get("last_S")
        state["last_S"] = S
        return B_prev_f

    # E-style stall detection: compare seller ask from two observations ago.
    second_last_S = state.get("second_last_S")
    if second_last_S is not None and not state.get("stall_seen", False):
        seller_drop = float(second_last_S) - S
        small_drop = _E_SMALL_SELLER_DROP_FRAC * max(float(second_last_S), 0.0)
        if seller_drop <= small_drop:
            state["stall_seen"] = True

    if t == 2:
        # Around 0.2 * S_1 with small noise.
        noise = rng.uniform(-_E_B2_NOISE_SCALE * S, +_E_B2_NOISE_SCALE * S)
        target = _E_B2_CENTER * S + noise
    elif state.get("stall_seen", False) and not state.get("jump_done", False):
        # First round after detecting stall: jump to 0.35--0.55 * S.
        target = state["jump_frac"] * S
        state["jump_done"] = True
        state["last_post_stall_add"] = None
    elif state.get("stall_seen", False):
        # After jump, keep adding but taper each round.
        decay = state["post_stall_decay"]
        add_frac = state["post_stall_add_frac"]
        planned_add = max(add_frac * S, 0.0)
        last_add = state.get("last_post_stall_add")
        if last_add is not None:
            planned_add = min(planned_add, max(float(last_add) * decay, 0.0))
        target = B_prev_f + planned_add
        state["post_stall_add_frac"] = add_frac * decay
        post_stall_increment = True
    else:
        # Before stall, add roughly 0.05 * S each round.
        add_frac = rng.uniform(_E_PRE_STALL_ADD_FRAC_LO, _E_PRE_STALL_ADD_FRAC_HI)
        target = B_prev_f + add_frac * S

    result = _clip(max(B_prev_f, target), lo=0.0, hi=upper)
    if post_stall_increment:
        state["last_post_stall_add"] = max(result - B_prev_f, 0.0)
    state["second_last_S"] = state.get("last_S")
    state["last_S"] = S
    return result


# ----------------------------------------------------------------------
# Trial Strategy B
# ----------------------------------------------------------------------

def _B_init(rng: random.Random, vehicle: dict, T: int) -> dict:
    del rng
    return {
        "scheme": "B",
        "M": float(vehicle["market_price_new"]),
        "v": float(vehicle["dealer_cost"]),
        "T": int(T),
        "B1": 0.0,
    }


def _B_sample(
    state: dict,
    rng: random.Random,
    t: int,
    B_prev: float | None,
    S_prev: float | None,
) -> float:
    del state, rng

    if t == 1:
        return 0.0

    assert B_prev is not None and S_prev is not None
    B_prev_f = float(B_prev)
    upper = max(float(S_prev), 0.0)

    if upper <= B_prev_f:
        return B_prev_f

    target = B_prev_f + 1000.0
    return _clip(max(B_prev_f, target), lo=0.0, hi=upper)


# ----------------------------------------------------------------------
# Trial Strategy C
# ----------------------------------------------------------------------

def _C_init(rng: random.Random, vehicle: dict, T: int) -> dict:
    return {
        "scheme": "C",
        "M": float(vehicle["market_price_new"]),
        "v": float(vehicle["dealer_cost"]),
        "T": int(T),
        "B1": _sample_E_style_B1(rng, vehicle["market_price_new"]),
    }


def _C_sample(
    state: dict,
    rng: random.Random,
    t: int,
    B_prev: float | None,
    S_prev: float | None,
) -> float:
    del rng

    if t == 1:
        return state["B1"]

    assert B_prev is not None and S_prev is not None
    B_prev_f = float(B_prev)
    upper = max(float(S_prev), 0.0)

    if upper <= B_prev_f:
        return B_prev_f

    target = B_prev_f + 10.0
    return _clip(max(B_prev_f, target), lo=0.0, hi=upper)


# ----------------------------------------------------------------------
# Dispatch table
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class BuyerScheme:
    key: str
    name: str
    init_state: Callable[[random.Random, dict, int], dict]
    sample_bid: Callable[[dict, random.Random, int, float | None, float | None], float]


_SCHEMES: dict[str, BuyerScheme] = {
    "A": BuyerScheme("A", "Trial A: +10 when seller drops, +1000 after stall", _A_init, _A_sample),
    "B": BuyerScheme("B", "Trial B: start at 0, +1000 per round", _B_init, _B_sample),
    "C": BuyerScheme("C", "Trial C: E-style B1, then +10 per round", _C_init, _C_sample),
}


def get_scheme(key: str) -> BuyerScheme:
    try:
        return _SCHEMES[key]
    except KeyError as e:
        raise KeyError(f"unknown trial buyer scheme {key!r}; valid: {list(_SCHEMES)}") from e


if __name__ == "__main__":
    vehicle = {"market_price_new": 96000.0, "dealer_cost": 19000.0}
    T = 12
    for k in _SCHEMES:
        rng = random.Random(42)
        sch = get_scheme(k)
        state = sch.init_state(rng, vehicle, T)
        B_prev, S_prev = None, None
        S = 0.9 * (vehicle["market_price_new"] - vehicle["dealer_cost"]) + vehicle["dealer_cost"]
        bids = []
        for t in range(1, T + 1):
            B = sch.sample_bid(state, rng, t, B_prev, S_prev)
            bids.append(B)
            B_prev, S_prev = B, S
            S = max(vehicle["dealer_cost"], S - 0.05 * (vehicle["market_price_new"] - vehicle["dealer_cost"]))
        print(f"{k} {sch.name}:")
        print("  B:", " ".join(f"{b:7.0f}" for b in bids))
