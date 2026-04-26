"""
buyer_schemes.py -- Buyer-bid generators.

Schemes A-D are the four random buyer-bid generators from the paper.
Scheme E is an additional custom strategy that follows the same init/sample
interface and dispatch format.

Spec source for A-D: Appendix B.1 of NegotiatorFollowLinear v10.

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

E. Low anchor with seller-stall jump.
       B_1 = 0.1 * M + U[-0.01 * M, 0.01 * M]
       B_2 = max{ B_1, 0.2 * S_1 + U[-0.02 * S_1, 0.02 * S_1] }
   For later rounds, the buyer adds roughly 0.05 * S_{t-1} while the seller
   continues to concede materially.  A seller stall is detected by comparing
   the seller ask two observations back with the current seller ask; if the
   two-step decrease is <= 1% of the older seller ask, the seller is treated
   as stalled.  Once stalled, the buyer jumps to roughly 0.35--0.55 * S_{t-1}, then
   continues adding with a tapering per-run preference so later increases
   become smaller and less likely to overpay.  The buyer's standing offer
   is kept weakly monotone; new increases are capped at S_{t-1}.

Initialization is common to schemes A-D:
       B_1 ~ U[0, 0.3 * M]

Scheme E uses custom initialization:
       B_1 = 0.1 * M + U[-0.01 * M, 0.01 * M]

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
# Scheme E -- Low anchor with seller-stall jump
# ----------------------------------------------------------------------
# Custom strategy:
#   1. B_1 starts low, around 0.1 * M with small noise.
#   2. B_2 starts around 0.2 * S_1.
#   3. While seller asks keep falling materially, add about 0.05 * S_{t-1}.
#   4. If the two-step seller ask decrease is small, jump to
#      about 0.35--0.55 * S_{t-1}, then keep adding with a tapering per-run
#      preference so later increases become smaller.

_E_B1_CENTER:               float = 0.10
_E_B1_NOISE_SCALE:          float = 0.01
_E_B2_CENTER:               float = 0.20
_E_B2_NOISE_SCALE:          float = 0.02
_E_PRE_STALL_ADD_FRAC_LO:   float = 0.04
_E_PRE_STALL_ADD_FRAC_HI:   float = 0.06
_E_SMALL_SELLER_DROP_FRAC:  float = 0.01
_E_JUMP_FRAC_LO:            float = 0.35
_E_JUMP_FRAC_HI:            float = 0.55
_E_POST_STALL_ADD_FRAC_LO:  float = 0.04
_E_POST_STALL_ADD_FRAC_HI:  float = 0.07
_E_POST_STALL_DECAY_LO:     float = 0.70
_E_POST_STALL_DECAY_HI:     float = 0.90


def _sample_E_B1(rng: random.Random, M: float) -> float:
    """Initial buyer bid around 0.1 * M with small symmetric noise."""
    M = float(M)
    noise = rng.uniform(-_E_B1_NOISE_SCALE * M, +_E_B1_NOISE_SCALE * M)
    return _clip(_E_B1_CENTER * M + noise, lo=0.0, hi=max(M, 0.0))


def _E_init(rng: random.Random, vehicle: dict, T: int) -> dict:
    return {
        "scheme": "E",
        "M":      float(vehicle["market_price_new"]),
        "v":      float(vehicle["dealer_cost"]),
        "T":      int(T),
        "B1":     _sample_E_B1(rng, vehicle["market_price_new"]),
        # Mutable per-run state used to detect whether seller concessions stall.
        "last_S": None,
        "second_last_S": None,
        "stall_seen": False,
        "jump_done": False,
        # The jump target, initial post-stall increment, and decay are drawn
        # once per run, so this strategy has a stable buyer "preference"
        # after the stall signal while still tapering later increases.
        "jump_frac": rng.uniform(_E_JUMP_FRAC_LO, _E_JUMP_FRAC_HI),
        "post_stall_add_frac": rng.uniform(
            _E_POST_STALL_ADD_FRAC_LO, _E_POST_STALL_ADD_FRAC_HI
        ),
        "post_stall_decay": rng.uniform(
            _E_POST_STALL_DECAY_LO, _E_POST_STALL_DECAY_HI
        ),
        "last_post_stall_add": None,
    }


def _E_sample(state: dict, rng: random.Random,
              t: int, B_prev: float | None, S_prev: float | None) -> float:
    if t == 1:
        return state["B1"]

    assert B_prev is not None and S_prev is not None, \
        "scheme E needs both lagged values from round >= 2"

    B_prev_f = float(B_prev)
    S = float(S_prev)
    upper = max(S, 0.0)
    post_stall_increment = False

    # Detect a seller stall by comparing the current known seller ask to the
    # seller ask from two seller observations ago.  In the user's notation,
    # this checks whether S_{t-2} - S_t is <= 1% of S_{t-2}.
    second_last_S = state.get("second_last_S")
    if second_last_S is not None and not state.get("stall_seen", False):
        seller_drop = float(second_last_S) - S
        small_drop = _E_SMALL_SELLER_DROP_FRAC * max(float(second_last_S), 0.0)
        if seller_drop <= small_drop:
            state["stall_seen"] = True

    if upper <= B_prev_f:
        # Seller is already at or below the buyer's standing offer; keep the
        # standing offer unchanged, mirroring scheme B's no-room-to-move case.
        state["second_last_S"] = state.get("last_S")
        state["last_S"] = S
        return B_prev_f

    if t == 2:
        # Around 0.2 * S_1, with small random noise.
        noise = rng.uniform(-_E_B2_NOISE_SCALE * S, +_E_B2_NOISE_SCALE * S)
        target = _E_B2_CENTER * S + noise
    elif state.get("stall_seen", False) and not state.get("jump_done", False):
        # First round after detecting a seller stall: jump to 0.35--0.55 * S.
        target = state["jump_frac"] * S
        state["jump_done"] = True
        state["last_post_stall_add"] = None
    elif state.get("stall_seen", False):
        # After the jump, keep adding but taper the increment each round.
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
        # Before a stall, add roughly 0.05 * S each round.
        add_frac = rng.uniform(_E_PRE_STALL_ADD_FRAC_LO, _E_PRE_STALL_ADD_FRAC_HI)
        target = B_prev_f + add_frac * S

    # Preserve ascending-bid behavior: never reduce the standing buyer offer.
    result = _clip(max(B_prev_f, target), lo=0.0, hi=upper)
    if post_stall_increment:
        # Store the actual realized increase, after clipping, so the next
        # post-stall increase is no larger and usually smaller.
        state["last_post_stall_add"] = max(result - B_prev_f, 0.0)
    state["second_last_S"] = state.get("last_S")
    state["last_S"] = S
    return result


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
    "E": BuyerScheme("E", "Low anchor with seller-stall jump", _E_init, _E_sample),
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
