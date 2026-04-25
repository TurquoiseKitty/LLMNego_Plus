"""
buyer_schemes.py -- The four random buyer-bid generators from the paper.

These are THE buyer processes.  Everything that separates scheme A from B
from C from D lives here and nowhere else.

Spec source: Appendix B.1 of NegotiatorFollowLinear v10.

A. Anchored IID.
       B_t = max{ B_{t-1}, U[0, S_{t-1}] }
   The weak monotonicity preserves ascending-bid negotiations while the
   fresh uniform draw at each turn keeps B_t nearly conditionally
   independent of B_{t-1} given S_{t-1}.

B. Slow fractional concession.
       B_t = B_{t-1} + (S_{t-1} - B_{t-1}) * Beta(1, 3)
   Cooperative-buyer-looking monotone ascent; Beta(1,3) mean = 0.25.

C. Random walk with retreats.
       B_t = clip( B_{t-1} + (M - v) * N(0.04, 0.01), [0, S_{t-1}] )
   Variance 0.01 means sigma = 0.1.  About 1/3 of turns have dB < 0.

D. Perturbed pacing.
       B_t = clip( (t/T) * M * lambda + (M - v) * U[-0.08, 0.08],
                   [0, S_{t-1}] )
   where lambda ~ U[0.7, 1.3] is drawn ONCE at the start of a run and
   held fixed across all turns.  Gives the cleanest experimental
   identification: the U[-0.08, 0.08] noise is exogenous to state.

Initialization is common to all four schemes:
       B_1 ~ U[0, 0.3 * M]

Each scheme exposes two callables:

    init_state(rng, vehicle, T) -> dict
        Returns a per-run state object, typically {"B1": float_B1_sample,
        "lambda": float_lambda_or_None, "market_price": M, "dealer_cost": v,
        "T": T}.

    sample_bid(state, rng, t, B_prev, S_prev) -> float
        Returns the buyer's bid at round t in [1, T].
        B_prev is the previous buyer bid (None on round 1; then == state["B1"]).
        S_prev is the previous seller ask (None on round 1).

A dispatch factory `get_scheme(scheme_key)` returns the two callables bound
together as a named tuple; the negotiation runner calls init_state once and
sample_bid per round.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable


# ----------------------------------------------------------------------
# Shared utilities
# ----------------------------------------------------------------------

def _clip(x: float, lo: float, hi: float) -> float:
    if hi < lo:  # degenerate interval — just return the floor
        return lo
    return max(lo, min(hi, x))


def _sample_B1(rng: random.Random, M: float) -> float:
    """Initial buyer bid ~ U[0, 0.3 * M].  Shared across all four schemes."""
    return rng.uniform(0.0, 0.3 * float(M))


# ----------------------------------------------------------------------
# Scheme A -- Anchored IID
# ----------------------------------------------------------------------

def _A_init(rng: random.Random, vehicle: dict, T: int) -> dict:
    return {
        "scheme": "A",
        "M":      float(vehicle["market_price_new"]),
        "v":      float(vehicle["dealer_cost"]),
        "T":      int(T),
        "B1":     _sample_B1(rng, vehicle["market_price_new"]),
    }


def _A_sample(state: dict, rng: random.Random,
              t: int, B_prev: float | None, S_prev: float | None) -> float:
    if t == 1:
        return state["B1"]
    # max { B_prev, U[0, S_prev] }
    upper = float(S_prev) if S_prev is not None else state["M"]
    draw = rng.uniform(0.0, max(upper, 0.0))
    return max(float(B_prev), draw)


# ----------------------------------------------------------------------
# Scheme B -- Slow fractional concession
# ----------------------------------------------------------------------

def _B_init(rng: random.Random, vehicle: dict, T: int) -> dict:
    return {
        "scheme": "B",
        "M":      float(vehicle["market_price_new"]),
        "v":      float(vehicle["dealer_cost"]),
        "T":      int(T),
        "B1":     _sample_B1(rng, vehicle["market_price_new"]),
    }


def _B_sample(state: dict, rng: random.Random,
              t: int, B_prev: float | None, S_prev: float | None) -> float:
    if t == 1:
        return state["B1"]
    assert B_prev is not None and S_prev is not None, \
        "scheme B needs both lagged values from round >= 2"
    gap = float(S_prev) - float(B_prev)
    if gap <= 0.0:
        # Seller already at or below buyer's standing offer -- no room to move
        # up; stay put (this mirrors the agreement condition and will be
        # dropped from analysis by the preprocessing rules).
        return float(B_prev)
    # random.betavariate(alpha, beta) gives Beta(alpha, beta) in (0, 1).
    frac = rng.betavariate(1.0, 3.0)
    return float(B_prev) + gap * frac


# ----------------------------------------------------------------------
# Scheme C -- Random walk with retreats
# ----------------------------------------------------------------------
# B_t = clip( B_prev + (M - v) * N(mu=0.04, sigma=0.1), [0, S_prev] )

_C_MU:    float = 0.04
_C_SIGMA: float = 0.1          # so variance = 0.01 as specified in the paper


def _C_init(rng: random.Random, vehicle: dict, T: int) -> dict:
    return {
        "scheme": "C",
        "M":      float(vehicle["market_price_new"]),
        "v":      float(vehicle["dealer_cost"]),
        "T":      int(T),
        "B1":     _sample_B1(rng, vehicle["market_price_new"]),
    }


def _C_sample(state: dict, rng: random.Random,
              t: int, B_prev: float | None, S_prev: float | None) -> float:
    if t == 1:
        return state["B1"]
    assert B_prev is not None and S_prev is not None
    M = state["M"]; v = state["v"]
    drift = (M - v) * rng.gauss(_C_MU, _C_SIGMA)
    upper = float(S_prev)
    return _clip(float(B_prev) + drift, lo=0.0, hi=max(upper, 0.0))


# ----------------------------------------------------------------------
# Scheme D -- Perturbed pacing
# ----------------------------------------------------------------------
# lambda drawn ONCE per run in init_state.

_D_NOISE_SCALE: float = 0.08   # U[-0.08, +0.08] * (M - v)


def _D_init(rng: random.Random, vehicle: dict, T: int) -> dict:
    return {
        "scheme": "D",
        "M":      float(vehicle["market_price_new"]),
        "v":      float(vehicle["dealer_cost"]),
        "T":      int(T),
        "B1":     _sample_B1(rng, vehicle["market_price_new"]),
        "lambda": rng.uniform(0.7, 1.3),    # fixed for the whole run
    }


def _D_sample(state: dict, rng: random.Random,
              t: int, B_prev: float | None, S_prev: float | None) -> float:
    if t == 1:
        return state["B1"]
    M = state["M"]; v = state["v"]; T = state["T"]; lam = state["lambda"]
    assert S_prev is not None
    anchor = (t / T) * M * lam
    noise  = (M - v) * rng.uniform(-_D_NOISE_SCALE, +_D_NOISE_SCALE)
    upper  = float(S_prev)
    return _clip(anchor + noise, lo=0.0, hi=max(upper, 0.0))


# ----------------------------------------------------------------------
# Dispatch table
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class BuyerScheme:
    key:         str
    name:        str
    init_state:  Callable[[random.Random, dict, int], dict]
    sample_bid:  Callable[[dict, random.Random, int, float | None, float | None], float]


_SCHEMES: dict[str, BuyerScheme] = {
    "A": BuyerScheme("A", "Anchored IID",              _A_init, _A_sample),
    "B": BuyerScheme("B", "Slow fractional concession", _B_init, _B_sample),
    "C": BuyerScheme("C", "Random walk with retreats",  _C_init, _C_sample),
    "D": BuyerScheme("D", "Perturbed pacing",           _D_init, _D_sample),
}


def get_scheme(key: str) -> BuyerScheme:
    try:
        return _SCHEMES[key]
    except KeyError as e:
        raise KeyError(f"unknown buyer scheme {key!r}; valid: {list(_SCHEMES)}") from e


# ----------------------------------------------------------------------
# Minimal self-test
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Smoke test: does each scheme produce T turns of plausible bids?
    vehicle = {"market_price_new": 96000.0, "dealer_cost": 19000.0}
    T = 12
    for k in _SCHEMES:
        rng = random.Random(42)
        sch = get_scheme(k)
        state = sch.init_state(rng, vehicle, T)
        B_prev, S_prev = None, None
        # Stylised seller that concedes ~5% of margin per round (fake).
        S = 0.9 * (vehicle["market_price_new"] - vehicle["dealer_cost"]) + vehicle["dealer_cost"]
        bids = []
        for t in range(1, T + 1):
            B = sch.sample_bid(state, rng, t, B_prev, S_prev)
            bids.append(B)
            B_prev, S_prev = B, S
            S = max(vehicle["dealer_cost"], S - 0.05 * (vehicle["market_price_new"] - vehicle["dealer_cost"]))
        print(f"{k} {sch.name}:")
        print("  B:", " ".join(f"{b:7.0f}" for b in bids))
