"""
worker.py -- Run ONE of the 12 experiments in a dedicated Python process.

Usage:
    python worker.py --experiment-index N
                     [--output-dir DIR] [--n-rounds N]
                     [--runs-per-car N] [--base-seed S] [--model M]

Config comes from config.py by default (DeepSeek reasoner + calibrated
runs-per-car).  Every argument has a corresponding env var handled in
config.py, so you can retune the workload without editing any file.

Behaviour:
    * Iterates over all 5 cars in fleet.FLEET.
    * For each car, runs N_RUNS_PER_CAR negotiations with distinct seeds.
    * After each car finishes, rewrites <output-dir>/<tag>.json in place --
      this gives free checkpointing: if the worker is killed mid-experiment
      you keep every fully-completed car's runs.
    * Emits verbose per-round progress to stdout.  The launcher captures
      that stream, prefixes it with the experiment tag, and mirrors it to a
      per-worker log file.

Timing calibration (see config.py):
    30 runs/car * 5 cars * 16 rounds = 2,400 seller calls per experiment.
    At the measured 0416b rate of ~200 calls/hour on deepseek-reasoner,
    that's ~12 hours of wall-clock per worker.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

from openai import OpenAI

import config
from fleet import FLEET, fleet_as_records
from experiments import EXPERIMENTS
from negotiation import run_single_negotiation


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _json_default(o):
    if isinstance(o, (datetime.datetime, datetime.date)):
        return o.isoformat()
    if hasattr(o, "to_dict"):
        return o.to_dict()
    raise TypeError(f"not JSON-serialisable: {type(o)}")


def _build_client(api_key: str, base_url: str) -> OpenAI:
    """Construct an OpenAI-compatible client pointed at the configured host."""
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )


def _assemble_result(exp: dict, args: argparse.Namespace,
                     total_secs: float, runs: list[dict]) -> dict:
    schedule = exp["seller_schedule"]
    return {
        "experiment": {
            "index":           exp["index"],
            "tag":             exp["tag"],
            "group":           exp["group"],
            "replicate":       exp["replicate"],
            "seller_schedule": schedule.to_dict(),
            "n_rounds":        args.n_rounds,
            "n_cars":          len(FLEET),
            "runs_per_car":    args.runs_per_car,
            "n_runs_total":    len(runs),
            "model":           args.model,
            "base_url":        args.base_url,
            "base_seed":       args.base_seed,
            "total_seconds":   round(total_secs, 1),
            "total_minutes":   round(total_secs / 60, 2),
            "total_hours":     round(total_secs / 3600, 2),
            "timestamp":       datetime.datetime.now().isoformat(),
        },
        "fleet": fleet_as_records(),
        "runs":  runs,
    }


def _save_checkpoint(out_path: Path, result: dict) -> None:
    """Atomic-ish save: write to .tmp and rename over the target."""
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=_json_default)
    tmp.replace(out_path)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment-index", type=int, required=True)
    ap.add_argument("--output-dir",       type=str, default="results")
    ap.add_argument("--n-rounds",         type=int, default=config.N_ROUNDS)
    ap.add_argument("--runs-per-car",     type=int, default=config.N_RUNS_PER_CAR)
    ap.add_argument("--base-seed",        type=int, default=config.BASE_SEED)
    ap.add_argument("--model",            type=str, default=config.DEEPSEEK_MODEL)
    ap.add_argument("--base-url",         type=str, default=config.DEEPSEEK_BASE_URL)
    ap.add_argument("--api-key",          type=str, default=config.DEEPSEEK_API_KEY)
    ap.add_argument("--quiet",            action="store_true",
                    help="Suppress per-round stdout lines.")
    args = ap.parse_args()

    if not (0 <= args.experiment_index < len(EXPERIMENTS)):
        print(f"ERROR: --experiment-index must be in [0, {len(EXPERIMENTS)})",
              file=sys.stderr, flush=True)
        sys.exit(2)
    if not args.api_key:
        print("ERROR: no API key -- set NEGO_API_KEY or edit config.py.",
              file=sys.stderr, flush=True)
        sys.exit(2)

    exp      = EXPERIMENTS[args.experiment_index]
    tag      = exp["tag"]
    schedule = exp["seller_schedule"]

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tag}.json"

    # --- banner ---
    n_calls_expected = len(FLEET) * args.runs_per_car * args.n_rounds
    print(f"=== START {tag} ===", flush=True)
    print(f"    schedule    : {schedule.label}", flush=True)
    print(f"    adaptive    : {schedule.is_adaptive}  (switches={schedule.switch_points})", flush=True)
    print(f"    unique strat: {sorted(set(schedule.schedule))}", flush=True)
    print(f"    n_rounds    : {args.n_rounds}", flush=True)
    print(f"    n_cars      : {len(FLEET)}", flush=True)
    print(f"    runs/car    : {args.runs_per_car}", flush=True)
    print(f"    total runs  : {len(FLEET) * args.runs_per_car}", flush=True)
    print(f"    total calls : {n_calls_expected}  "
          f"(~{n_calls_expected / 200:.1f} h @ 200 calls/h)", flush=True)
    print(f"    model       : {args.model}", flush=True)
    print(f"    base_url    : {args.base_url}", flush=True)
    print(f"    base_seed   : {args.base_seed}", flush=True)
    print(f"    output      : {out_path}", flush=True)
    sys.stdout.flush()

    client = _build_client(args.api_key, args.base_url)

    t_exp_start = time.time()
    runs: list[dict] = []

    for car_idx, car in enumerate(FLEET):
        car_t0 = time.time()
        print(
            f"\n--- CAR {car_idx+1}/{len(FLEET)}: {car.car_name}"
            f"  (M=${float(car.market_price_new):,.2f}"
            f"  cost=${float(car.dealer_cost):,.2f}"
            f"  cost/M={float(car.dealer_cost)/float(car.market_price_new):.2%}) ---",
            flush=True,
        )

        for run_idx in range(args.runs_per_car):
            # Seeding:  distinct per (experiment, car, run); never collides.
            seed = (
                args.base_seed
                + args.experiment_index * 100_000
                + car_idx * 1_000
                + run_idx
            )
            run_t0 = time.time()
            print(
                f"\n   run {run_idx+1}/{args.runs_per_car} on {car.car_name}  seed={seed}",
                flush=True,
            )
            try:
                run = run_single_negotiation(
                    client=client,
                    model=args.model,
                    active_car=car,
                    fleet=FLEET,
                    seller_schedule=schedule,
                    n_rounds=args.n_rounds,
                    rng_seed=seed,
                    verbose=not args.quiet,
                )
            except Exception as e:
                # Don't let one failed run kill the worker.
                print(f"   !! ERROR on run {run_idx+1}: {type(e).__name__}: {e}",
                      flush=True)
                import traceback
                traceback.print_exc()
                run = {
                    "car": {
                        "car_name": car.car_name,
                        "market_price_new": float(car.market_price_new),
                        "dealer_cost": float(car.dealer_cost),
                    },
                    "rng_seed": seed,
                    "n_rounds": args.n_rounds,
                    "seller_schedule": schedule.to_dict(),
                    "model": args.model,
                    "error": f"{type(e).__name__}: {e}",
                    "rounds": [],
                }
            runs.append(run)
            print(f"   run {run_idx+1} done in {(time.time()-run_t0)/60:.1f} min",
                  flush=True)

        # --- checkpoint after every car ---
        total_secs_so_far = time.time() - t_exp_start
        result = _assemble_result(exp, args, total_secs_so_far, runs)
        _save_checkpoint(out_path, result)
        car_mins = (time.time() - car_t0) / 60
        total_mins = total_secs_so_far / 60
        print(
            f"\n   ---> checkpoint: car {car_idx+1}/{len(FLEET)} done in {car_mins:.1f} min; "
            f"total so far {total_mins:.1f} min; saved {len(runs)} runs to {out_path.name}",
            flush=True,
        )

    # --- final save (same content as the last checkpoint, for clarity) ---
    total_secs = time.time() - t_exp_start
    result = _assemble_result(exp, args, total_secs, runs)
    _save_checkpoint(out_path, result)

    print(
        f"\n=== FINISH {tag} in {total_secs/3600:.2f} h "
        f"({len(runs)} runs, {n_calls_expected} calls planned) "
        f"-> {out_path} ===",
        flush=True,
    )


if __name__ == "__main__":
    main()
