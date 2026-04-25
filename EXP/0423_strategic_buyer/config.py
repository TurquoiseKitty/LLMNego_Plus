"""
config.py -- API and runtime configuration for the 0423 LLM-buyer sweep.

Edit `DEEPSEEK_API_KEY` below if your key changes. All other fields can be
overridden at runtime via environment variables (see the env var names below).

Differences vs. the 0421 config:
    * N_RUNS_PER_CAR default is 15 (was 30). With an LLM buyer added, each
      round now consumes roughly twice as many LLM calls and twice as much
      wall clock, so halving runs-per-car keeps the per-experiment budget
      at the same ~12 h target.
    * BASE_SEED bumped to 20260423 (today's date) so 0423 seeds don't
      collide with 0421 seeds.
    * DEEPSEEK_BUYER_MODEL added; defaults to the same model as the seller
      (DEEPSEEK_MODEL). Set NEGO_BUYER_MODEL to decouple.
"""

from __future__ import annotations

import os


# ----------------------------------------------------------------------
# DeepSeek API credentials  (unchanged from 0421)
# ----------------------------------------------------------------------

DEEPSEEK_API_KEY: str = os.environ.get(
    "NEGO_API_KEY",
    "sk-81e3e6eae33d4486ad4127e0cb3630a6",
)

DEEPSEEK_BASE_URL: str = os.environ.get(
    "NEGO_BASE_URL",
    "https://api.deepseek.com",
)

# Model used by the seller (and by the buyer by default).
DEEPSEEK_MODEL: str = os.environ.get(
    "NEGO_MODEL",
    "deepseek-reasoner",
)

# Optional override for the buyer model. If NEGO_BUYER_MODEL is unset, the
# buyer uses the same model as the seller. Must also be a reasoner-style
# model (or a GPT-style model handled via the <think>...</think> fallback
# in negotiation.py).
DEEPSEEK_BUYER_MODEL: str = os.environ.get(
    "NEGO_BUYER_MODEL",
    DEEPSEEK_MODEL,
)


# ----------------------------------------------------------------------
# Per-call API parameters  (unchanged from 0421)
# ----------------------------------------------------------------------

MAX_TOKENS: int = 4096

THINKING_EXTRA_BODY: dict = {
    "enable_thinking": True,
    "thinking_budget": 8192,
}

REQUEST_TIMEOUT_SECONDS: float = 300.0


# ----------------------------------------------------------------------
# Retry policy  (unchanged from 0421)
# ----------------------------------------------------------------------

RETRY_MAX_ATTEMPTS: int = 4
RETRY_BASE_DELAY_SECONDS: float = 8.0


# ----------------------------------------------------------------------
# Workload calibration
# ----------------------------------------------------------------------
# 0421 calibration: ~200 seller calls / h.
#
# With buyer-side LLM added, each ROUND now costs 2 calls (1 buyer + 1
# seller) instead of 1. To keep the per-experiment wall clock near 12 h:
#
#   calls_budget / h    = 200 seller-equivalent calls  (same throughput)
#   calls / round       = 2
#   rounds_budget / h   = 100
#   target rounds / exp = 1200    (~12 h)
#   rounds_per_run      = 16
#   runs_per_exp        = 1200 / 16 = 75
#   runs_per_car        = 75 / 5  = 15
#
# So N_RUNS_PER_CAR = 15 keeps this sweep at roughly the same ~12 h / worker
# as the 0421 sweep. Override with NEGO_RUNS_PER_CAR to change.
# ----------------------------------------------------------------------

N_RUNS_PER_CAR: int = int(os.environ.get("NEGO_RUNS_PER_CAR", "10"))
N_ROUNDS:      int = int(os.environ.get("NEGO_N_ROUNDS", "16"))
BASE_SEED:     int = int(os.environ.get("NEGO_BASE_SEED", "20260423"))


def summarise() -> str:
    return (
        f"seller_model={DEEPSEEK_MODEL}  buyer_model={DEEPSEEK_BUYER_MODEL}  "
        f"base_url={DEEPSEEK_BASE_URL}  n_rounds={N_ROUNDS}  "
        f"runs_per_car={N_RUNS_PER_CAR}  base_seed={BASE_SEED}"
    )


if __name__ == "__main__":
    print(summarise())
