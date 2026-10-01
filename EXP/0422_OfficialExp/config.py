"""
config.py — API and runtime configuration.

Edit `DEEPSEEK_API_KEY` below if your key changes. All other fields can be
overridden at runtime via environment variables (see the env var names below)
so you don't have to touch this file when you want to try another endpoint.
"""

from __future__ import annotations

import os


# ----------------------------------------------------------------------
# DeepSeek API credentials
# ----------------------------------------------------------------------

# Override with the NEGO_API_KEY environment variable.
DEEPSEEK_API_KEY: str = os.environ.get(
    "NEGO_API_KEY",
    "YOUR_DEEPSEEK_API_KEY",
)

# Override with NEGO_BASE_URL.
DEEPSEEK_BASE_URL: str = os.environ.get(
    "NEGO_BASE_URL",
    "https://api.deepseek.com",
)

# Override with NEGO_MODEL. Must be a reasoner-style model.
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
