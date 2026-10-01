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
    "YOUR_DEEPSEEK_API_KEY",
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
RETRY_MAX_ATTEMPTS: int = 4
RETRY_BASE_DELAY_SECONDS: float = 8.0


# ----------------------------------------------------------------------
# Workload calibration
# ----------------------------------------------------------------------
N_RUNS_PER_CAR: int = int(os.environ.get("NEGO_RUNS_PER_CAR", "50"))
N_ROUNDS:      int = int(os.environ.get("NEGO_N_ROUNDS",     "12"))
BASE_SEED:     int = int(os.environ.get("NEGO_BASE_SEED",    "20260425"))


# ----------------------------------------------------------------------
# Parallelism hint for the launcher (not a hard cap)
# ----------------------------------------------------------------------
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
