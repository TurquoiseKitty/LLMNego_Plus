"""
config.py — API and runtime configuration for the buyer-scheme sweep.

Changes from the 0421 version:
  * N_ROUNDS = 12         (was 16)
  * N_RUNS_PER_CAR = 50   (was 30)
  * BASE_SEED bumped      (fresh randomness for the new design)

All fields can be overridden at runtime via environment variables; see below.
"""

from __future__ import annotations
import os


# ----------------------------------------------------------------------
# DeepSeek API credentials
# ----------------------------------------------------------------------
DEEPSEEK_API_KEY: str = os.environ.get(
    "NEGO_API_KEY",
    "sk-81e3e6eae33d4486ad4127e0cb3630a6",
)
DEEPSEEK_BASE_URL: str = os.environ.get(
    "NEGO_BASE_URL",
    "https://api.deepseek.com",
)
DEEPSEEK_MODEL: str = os.environ.get(
    "NEGO_MODEL",
    "deepseek-reasoner",
)


# ----------------------------------------------------------------------
# Per-call API parameters
# ----------------------------------------------------------------------
MAX_TOKENS: int = 4096
THINKING_EXTRA_BODY: dict = {
    "enable_thinking": True,
    "thinking_budget": 8192,
}
REQUEST_TIMEOUT_SECONDS: float = 300.0


# ----------------------------------------------------------------------
# Retry policy
# ----------------------------------------------------------------------
RETRY_MAX_ATTEMPTS: int = 4           # 1 initial + 3 retries
RETRY_BASE_DELAY_SECONDS: float = 8.0 # 8, 16, 32 s between retries


# ----------------------------------------------------------------------
# Workload calibration
# ----------------------------------------------------------------------
# New design: 6 policies x 5 vehicles x 4 schemes x 50 runs x T=12 turns.
# Total: 72,000 seller calls.
#
# At ~200 calls/hour/worker (DeepSeek reasoner, observed on 0421):
#   per (policy, scheme, vehicle, 50 runs, 12 turns) = 600 calls
#   per worker serving 2 cells = 1,200 calls ≈ 6 h wall clock
#
# So we partition the full 120-cell grid into 30+30 workers (half per user),
# 2 cells per worker, each ~6 h.  See runner.py / launcher.py for mechanics.
# ----------------------------------------------------------------------

N_RUNS_PER_CAR: int = int(os.environ.get("NEGO_RUNS_PER_CAR", "50"))
N_ROUNDS:      int = int(os.environ.get("NEGO_N_ROUNDS",     "12"))
BASE_SEED:     int = int(os.environ.get("NEGO_BASE_SEED",    "20260425"))


# ----------------------------------------------------------------------
# Parallelism hint for the launcher (not a hard cap)
# ----------------------------------------------------------------------
# Suggested number of parallel workers per half-of-sweep.  Can be overridden
# with NEGO_PARALLELISM on the launcher command line.
DEFAULT_PARALLELISM: int = int(os.environ.get("NEGO_PARALLELISM", "30"))


def summarise() -> str:
    """Short human-readable config dump, printed by worker banners."""
    return (
        f"model={DEEPSEEK_MODEL}  base_url={DEEPSEEK_BASE_URL}  "
        f"n_rounds={N_ROUNDS}  runs_per_car={N_RUNS_PER_CAR}  "
        f"base_seed={BASE_SEED}"
    )


if __name__ == "__main__":
    print(summarise())
