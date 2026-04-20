"""
config.py — API and runtime configuration.

Edit `DEEPSEEK_API_KEY` below if your key changes. All other fields can be
overridden at runtime via environment variables (see the env var names below)
so you don't have to touch this file when you want to try another endpoint.
"""

from __future__ import annotations

import os


# ----------------------------------------------------------------------
# DeepSeek API credentials  (copied from the 0416b notebooks in the rar)
# ----------------------------------------------------------------------

# Hard default — same key that was committed in the rar's notebooks.
# Override with the NEGO_API_KEY environment variable if you rotate it.
DEEPSEEK_API_KEY: str = os.environ.get(
    "NEGO_API_KEY",
    "sk-81e3e6eae33d4486ad4127e0cb3630a6",
)

# Override with NEGO_BASE_URL.
DEEPSEEK_BASE_URL: str = os.environ.get(
    "NEGO_BASE_URL",
    "https://api.deepseek.com",
)

# Override with NEGO_MODEL.  Must be a reasoner-style model; the call path
# expects a `reasoning_content` field to be present on the response message.
DEEPSEEK_MODEL: str = os.environ.get(
    "NEGO_MODEL",
    "deepseek-reasoner",
)


# ----------------------------------------------------------------------
# Per-call API parameters  (matches the 0416b runner exactly)
# ----------------------------------------------------------------------

# Budget for the final-answer tokens.
MAX_TOKENS: int = 4096

# Extra parameters forwarded to the API for reasoner-style models.
THINKING_EXTRA_BODY: dict = {
    "enable_thinking": True,
    "thinking_budget": 8192,
}

# Per-request HTTP timeout (seconds).  Reasoner calls can be long; DeepSeek
# typically finishes in ~15-25 s but we leave generous headroom.
REQUEST_TIMEOUT_SECONDS: float = 300.0


# ----------------------------------------------------------------------
# Retry policy
# ----------------------------------------------------------------------

# Transient errors get exponential-backoff retries with these settings.
RETRY_MAX_ATTEMPTS: int = 4          # 1 initial + 3 retries
RETRY_BASE_DELAY_SECONDS: float = 8.0   # 8, 16, 32 s between retries


# ----------------------------------------------------------------------
# Workload calibration
# ----------------------------------------------------------------------
# Calibration source: results_0416b / README_0416b.md
#   * nb1  : 220 runs * 15 rounds = 3,300 seller calls / 16.5 h ≈ 200 calls/h
#   * nb11 : 252 runs * 15 rounds = 3,780 seller calls / 18.9 h ≈ 200 calls/h
#
# To target ~12 h per subprocess:
#   calls_budget = 200 * 12      = 2,400 seller calls per experiment
#   runs_per_car = 2,400 / (5 * 16) = 30
#
# So N_RUNS_PER_CAR = 30 gives 30 * 5 = 150 negotiations per experiment, and
# 150 * 16 = 2,400 calls ≈ 12 h of wall-clock per worker at the 0416b rate.
# ----------------------------------------------------------------------

N_RUNS_PER_CAR: int = int(os.environ.get("NEGO_RUNS_PER_CAR", "30"))
N_ROUNDS:      int = int(os.environ.get("NEGO_N_ROUNDS", "16"))
BASE_SEED:     int = int(os.environ.get("NEGO_BASE_SEED", "20260420"))


def summarise() -> str:
    """Short human-readable config dump, printed by worker.py banners."""
    return (
        f"model={DEEPSEEK_MODEL}  base_url={DEEPSEEK_BASE_URL}  "
        f"n_rounds={N_ROUNDS}  runs_per_car={N_RUNS_PER_CAR}  "
        f"base_seed={BASE_SEED}"
    )


if __name__ == "__main__":
    print(summarise())
