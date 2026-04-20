"""
run_all_0416.py — Shared helpers for the nine run_all_*.ipynb notebooks.

Each notebook builds its own EXPERIMENTS list (a list of dicts with
`buyer`, `seller_schedule`, `n_runs`, `tag`, `category_filter`) and calls
`run_experiment_block(EXPERIMENTS, notebook_id, CLIENT, MODEL, N_ROUNDS, BASE_SEED)`.

Output layout:
  results_0416/<notebook_id>/<tag>.json                       # per-condition raw runs
  results_0416/<notebook_id>/__all_transitions.json           # merged transitions
  results_0416/<notebook_id>/__manifest.json                  # the EXPERIMENTS list + timings
"""

from __future__ import annotations

import datetime
import json
import time
import traceback
from pathlib import Path
from typing import Any

from exp_runner_0416 import (
    run_condition, build_transitions, save_json,
    BuyerStrategy, AdaptiveBuyer, SellerSchedule,
)


# ======================================================================
# Top-level block runner
# ======================================================================

def run_experiment_block(
    experiments: list[dict],
    notebook_id: str,
    client, model: str,
    n_rounds: int = 12,
    base_seed: int = 5000,
    output_root: Path | str = "results_0416",
    verbose: bool = True,
    resume: bool = True,
) -> dict:
    """
    Run every experiment in `experiments` and write per-condition files,
    a merged all_transitions file, and a manifest.

    Each entry in `experiments` is a dict with:
      - tag (str, unique within the notebook)
      - buyer (BuyerStrategy)
      - seller_schedule (SellerSchedule)
      - n_runs (int)
      - category_filter (optional str)

    If `resume=True`, conditions whose .json already exists are skipped.
    """
    out_dir = Path(output_root) / notebook_id
    out_dir.mkdir(parents=True, exist_ok=True)

    all_transitions = []
    timings = []
    t_block_start = time.time()

    for i, exp in enumerate(experiments, start=1):
        tag = exp["tag"]
        buyer: BuyerStrategy = exp["buyer"]
        schedule: SellerSchedule = exp["seller_schedule"]
        n_runs: int = exp["n_runs"]
        category_filter = exp.get("category_filter")

        out_path = out_dir / f"{tag}.json"
        if resume and out_path.exists():
            if verbose:
                print(f"[{i}/{len(experiments)}] SKIP (exists): {tag}")
            # Still load its transitions so the merged file is complete.
            try:
                with open(out_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                all_transitions.extend(build_transitions(existing))
            except Exception as e:
                print(f"  (warning: could not rebuild transitions from {out_path}: {e})")
            continue

        print(f"\n{'='*72}")
        print(f"[{i}/{len(experiments)}]  {tag}")
        print(f"  buyer   = {buyer.to_dict()['name']}")
        print(f"  seller  = {schedule.to_dict()['label']}  "
              f"(adaptive={schedule.is_adaptive})")
        print(f"  n_runs  = {n_runs}   n_rounds = {n_rounds}")
        print(f"{'='*72}")

        t0 = time.time()
        try:
            experiment = run_condition(
                client=client, model=model,
                buyer=buyer, seller_schedule=schedule,
                n_runs=n_runs, n_rounds=n_rounds,
                base_seed=base_seed,
                category_filter=category_filter,
                verbose=verbose,
            )
        except Exception as e:
            print(f"!! ERROR in condition {tag}: {e}")
            traceback.print_exc()
            timings.append({"tag": tag, "status": "error", "error": str(e)})
            continue
        dt = time.time() - t0

        save_json(experiment, out_path)
        trans = build_transitions(experiment)
        all_transitions.extend(trans)
        timings.append({
            "tag": tag,
            "status": "ok",
            "seconds": round(dt, 1),
            "minutes": round(dt / 60, 2),
            "n_runs": n_runs,
            "n_transitions": len(trans),
        })
        total_min = (time.time() - t_block_start) / 60
        print(f"  ({dt/60:.1f} min for this condition; "
              f"{total_min:.1f} min total so far)")

    # Merged transitions
    merged = {
        "notebook_id": notebook_id,
        "model": model,
        "n_transitions": len(all_transitions),
        "transitions": all_transitions,
    }
    save_json(merged, out_dir / "__all_transitions.json")

    # Manifest with timings
    manifest = {
        "notebook_id": notebook_id,
        "model": model,
        "n_rounds": n_rounds,
        "base_seed": base_seed,
        "timestamp": datetime.datetime.now().isoformat(),
        "total_minutes": round((time.time() - t_block_start) / 60, 2),
        "experiments": [
            {
                "tag": e["tag"],
                "buyer": e["buyer"].to_dict(),
                "seller_schedule": e["seller_schedule"].to_dict(),
                "n_runs": e["n_runs"],
                "category_filter": e.get("category_filter"),
            }
            for e in experiments
        ],
        "timings": timings,
    }
    save_json(manifest, out_dir / "__manifest.json")

    print(f"\n=== Block {notebook_id} finished: "
          f"{manifest['total_minutes']:.1f} min total, "
          f"{len(all_transitions)} transitions ===")
    return manifest


# ======================================================================
# Convenience builders shared by several notebooks
# ======================================================================

from exp_runner_0416 import (
    RandomBuyer, BudgetBuyer, WildBuyer,
    ConcessionBuyer, AnchorDragBuyer,
    BoulwareBuyer, ConcederBuyer, TitForTatBuyer,
    PersistentBuyer,
    fixed_seller_schedule, twostage_seller_schedule, threestage_seller_schedule,
    ALL_SUPPLIER_STRATEGIES_V0416,
)


def all_fixed_buyers_for_notebook() -> list[BuyerStrategy]:
    """Canonical set of 10 fixed buyers used in the fixed×fixed notebooks.

    Order is stable so runs are reproducible across notebook versions.
    No deadline-aware buyer variant is included.
    """
    return [
        RandomBuyer(),
        BudgetBuyer(),
        WildBuyer(),
        ConcessionBuyer(),
        AnchorDragBuyer(),
        BoulwareBuyer(),
        ConcederBuyer(),
        TitForTatBuyer(),
        PersistentBuyer(0.30),
        PersistentBuyer(0.55),
    ]


def fixed_pairs_for_sellers(seller_strategies: list[str],
                            n_rounds: int,
                            n_runs_per_pair: int) -> list[dict]:
    """
    Build EXPERIMENTS for the fixed×fixed case: every buyer × every seller
    in `seller_strategies`.  Used by Notebooks 1-5.
    """
    buyers = all_fixed_buyers_for_notebook()
    out = []
    for s in seller_strategies:
        sched = fixed_seller_schedule(s, n_rounds)
        for b in buyers:
            tag = f"sel_{s}__buy_{b.name}"
            out.append({
                "tag": tag,
                "buyer": b,
                "seller_schedule": sched,
                "n_runs": n_runs_per_pair,
            })
    return out
