"""
run_all_0418.py — shared driver for the 12 notebooks of the 0418 sweep.

Each notebook defines:
  INITIAL_STRATEGY : str   ('cooperative' / 'tit_for_tat_matcher' / 'anchor_high')
  ADAPTIVE         : bool
  N_RUNS           : int
  NOTEBOOK_ID      : str   ('nb1'..'nb12')

and calls `run_block(...)`.  Output:
  results_0418/<notebook_id>/run_000.json, ...
  results_0418/<notebook_id>/__manifest.json
"""

from __future__ import annotations

import datetime
import json
import time
import traceback
from pathlib import Path

from exp_runner_0418 import (
    run_single, sample_product_spec, SUPPLIER_POOL,
    TAU_LOW, TAU_HIGH, ALL_STRATEGIES,
)

import random as _random


def run_block(
    client, model: str,
    initial_strategy: str,
    adaptive: bool,
    n_runs: int,
    notebook_id: str,
    n_rounds: int = 16,
    base_seed: int = 5000,
    output_root: str | Path = "results_0418",
    verbose: bool = True,
    resume: bool = True,
) -> dict:
    """
    Run `n_runs` trajectories; save one JSON per run so the notebook is
    crash-resistant (previous JSONs survive even if a later run fails).
    """
    out_dir = Path(output_root) / notebook_id
    out_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    timings = []
    for i in range(n_runs):
        seed = base_seed + i
        out_path = out_dir / f"run_{i:03d}_seed{seed}.json"
        if resume and out_path.exists():
            if verbose:
                print(f"[{i+1}/{n_runs}] SKIP (exists): {out_path.name}")
            continue

        rng = _random.Random(seed)
        spec = sample_product_spec(rng)
        sid, sname = rng.choice(SUPPLIER_POOL)

        if verbose:
            mv = spec.market_price - spec.v
            print(f"\n[{i+1}/{n_runs}] seed={seed}  "
                  f"c={spec.cost:.2f} v-c={spec.internal_cost:.2f} "
                  f"M-v={mv:.2f}  init={initial_strategy}  adapt={adaptive}")

        t0 = time.time()
        try:
            run = run_single(
                client=client, model=model,
                spec=spec, supplier_id=sid, supplier_name=sname,
                initial_strategy=initial_strategy,
                adaptive=adaptive,
                n_rounds=n_rounds, rng_seed=seed,
                verbose=False,   # per-round prints are too noisy here
            )
        except Exception as e:
            print(f"  !! ERROR: {e}"); traceback.print_exc()
            timings.append({"i": i, "seed": seed, "status": "error",
                             "error": str(e)})
            continue
        dt = time.time() - t0

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(run, f, ensure_ascii=False, default=str)
        timings.append({"i": i, "seed": seed, "status": "ok",
                         "seconds": round(dt, 1), "minutes": round(dt/60, 2)})
        total_min = (time.time() - t_start) / 60
        if verbose:
            print(f"  done in {dt/60:.2f} min  "
                  f"(total so far: {total_min:.1f} min)")

    manifest = {
        "notebook_id":      notebook_id,
        "model":            model,
        "initial_strategy": initial_strategy,
        "adaptive":         adaptive,
        "n_runs_requested": n_runs,
        "n_runs_done":      len([t for t in timings if t.get("status")=="ok"]),
        "n_rounds":         n_rounds,
        "base_seed":        base_seed,
        "TAU_LOW":          TAU_LOW,
        "TAU_HIGH":         TAU_HIGH,
        "timestamp":        datetime.datetime.now().isoformat(),
        "total_minutes":    round((time.time() - t_start) / 60, 2),
        "timings":          timings,
    }
    with open(out_dir / "__manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)
    print(f"\n=== {notebook_id} done: {manifest['total_minutes']:.1f} min total, "
          f"{manifest['n_runs_done']}/{n_runs} runs completed ===")
    return manifest
