"""
worker.py -- Run ONE (policy, scheme, vehicle) cell in a dedicated Python process.

Usage:
    python worker.py --side {user,cooperator} --cell-index K
                     [--output-dir DIR] [--state-dir DIR]
                     [--n-rounds N] [--runs-per-car N]
                     [--base-seed S] [--model M]

where --cell-index K is the index into plan.worker_cells_for_side(side).

Each cell = one (policy, buyer_scheme, vehicle).  The worker runs N_RUNS_PER_CAR
(= 50) independent negotiations of N_ROUNDS (= 12) turns each, and writes
results/<tag>.json where <tag> = e.g. "user_A_patient_value_defender_v1".

State tracking uses proc_state.py atomic writes identically to the 0421
pipeline.  See README.md for state-field definitions.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import signal
import socket
import sys
import time
import traceback
from pathlib import Path

from openai import OpenAI

import config
from fleet import FLEET, fleet_as_records
from negotiation import run_single_negotiation
from buyer_schemes import get_scheme
import plan
import proc_state as ps


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
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )


def _assemble_result(cell: plan.WorkerCell, args: argparse.Namespace,
                     total_secs: float, runs: list[dict]) -> dict:
    return {
        "experiment": {
            "tag":             cell.tag,
            "side":            cell.side,
            "policy":          cell.policy,
            "buyer_scheme":    cell.scheme,
            "vehicle_idx":     cell.vehicle_idx,
            "vehicle_name":    FLEET[cell.vehicle_idx].car_name,
            "n_rounds":        args.n_rounds,
            "runs_per_car":    args.runs_per_car,
            "n_runs_total":    len(runs),
            "model":           args.model,
            "base_url":        args.base_url,
            "base_seed":       args.base_seed,
            "pid":             os.getpid(),
            "hostname":        socket.gethostname(),
            "total_seconds":   round(total_secs, 1),
            "total_minutes":   round(total_secs / 60, 2),
            "total_hours":     round(total_secs / 3600, 2),
            "timestamp":       datetime.datetime.now().isoformat(),
        },
        "fleet": fleet_as_records(),
        "runs":  runs,
    }


def _save_checkpoint(out_path: Path, result: dict) -> None:
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=_json_default)
    tmp.replace(out_path)


# ----------------------------------------------------------------------
# Signal handling -> "killed" status
# ----------------------------------------------------------------------

class _Killed(SystemExit):
    def __init__(self, signame: str) -> None:
        super().__init__(128)
        self.signame = signame


def _install_term_handlers() -> None:
    def _h(signum, frame):  # noqa: ANN001
        raise _Killed(signal.Signals(signum).name)
    signal.signal(signal.SIGTERM, _h)
    signal.signal(signal.SIGINT,  _h)


# ----------------------------------------------------------------------
# Round-level heartbeat: wrap builtins.print like the 0421 worker did.
# ----------------------------------------------------------------------

class _RoundTracker:
    def __init__(self, state_dir: Path, tag: str, run_idx: int):
        self.state_dir = state_dir
        self.tag       = tag
        self.run_idx   = run_idx

    def bump_round(self, round_num: int) -> None:
        ps.update_state(
            self.state_dir, self.tag,
            last_round=round_num,
            last_run_idx=self.run_idx,
        )


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--side",         type=str, required=True, choices=["user", "cooperator"])
    ap.add_argument("--cell-index",   type=int, required=True)
    ap.add_argument("--output-dir",   type=str, default="results")
    ap.add_argument("--state-dir",    type=str, default="state")
    ap.add_argument("--n-rounds",     type=int, default=config.N_ROUNDS)
    ap.add_argument("--runs-per-car", type=int, default=config.N_RUNS_PER_CAR)
    ap.add_argument("--base-seed",    type=int, default=config.BASE_SEED)
    ap.add_argument("--model",        type=str, default=config.DEEPSEEK_MODEL)
    ap.add_argument("--base-url",     type=str, default=config.DEEPSEEK_BASE_URL)
    ap.add_argument("--api-key",      type=str, default=config.DEEPSEEK_API_KEY)
    ap.add_argument("--quiet",        action="store_true")
    args = ap.parse_args()

    cells = plan.worker_cells_for_side(args.side)
    if not (0 <= args.cell_index < len(cells)):
        print(f"ERROR: --cell-index must be in [0, {len(cells)})", file=sys.stderr, flush=True)
        return 2
    if not args.api_key:
        print("ERROR: no API key -- set NEGO_API_KEY or edit config.py.",
              file=sys.stderr, flush=True)
        return 2

    cell      = cells[args.cell_index]
    tag       = cell.tag
    state_dir = Path(args.state_dir)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tag}.json"

    vehicle        = FLEET[cell.vehicle_idx]
    buyer_scheme   = get_scheme(cell.scheme)
    planned_runs   = args.runs_per_car
    planned_rounds = planned_runs * args.n_rounds

    # --- initial state file ---
    ps.write_state(state_dir, tag, ps.initial_worker_state(
        tag=tag,
        experiment_index=args.cell_index,
        pid=os.getpid(),
        parent_pid=os.getppid(),
        cmdline=sys.argv,
        hostname=socket.gethostname(),
        cwd=os.getcwd(),
        config_summary=config.summarise(),
        planned_runs=planned_runs,
        planned_rounds=planned_rounds,
    ))

    _install_term_handlers()

    # --- banner ---
    print(f"=== START {tag} ===", flush=True)
    print(f"    pid         : {os.getpid()}", flush=True)
    print(f"    hostname    : {socket.gethostname()}", flush=True)
    print(f"    state_file  : {ps.state_path(state_dir, tag)}", flush=True)
    print(f"    side        : {cell.side}", flush=True)
    print(f"    policy      : {cell.policy}", flush=True)
    print(f"    scheme      : {cell.scheme} ({buyer_scheme.name})", flush=True)
    print(f"    vehicle     : #{cell.vehicle_idx+1} {vehicle.car_name}"
          f"  (M=${float(vehicle.market_price_new):,.0f}"
          f"  cost=${float(vehicle.dealer_cost):,.0f})", flush=True)
    print(f"    n_rounds    : {args.n_rounds}", flush=True)
    print(f"    runs/car    : {args.runs_per_car}", flush=True)
    print(f"    total runs  : {planned_runs}  (total calls: {planned_rounds})", flush=True)
    print(f"    model       : {args.model}  at {args.base_url}", flush=True)
    print(f"    base_seed   : {args.base_seed}", flush=True)
    print(f"    output      : {out_path}", flush=True)

    # --- transition to "running" ---
    ps.update_state(
        state_dir, tag,
        status="running",
        started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    )

    client = _build_client(args.api_key, args.base_url)

    t_cell_start = time.time()
    runs: list[dict] = []

    try:
        for run_idx in range(args.runs_per_car):
            seed = plan.run_seed(
                policy=cell.policy,
                scheme=cell.scheme,
                vehicle_idx=cell.vehicle_idx,
                run_idx=run_idx,
            )
            run_t0 = time.time()
            print(
                f"\n   run {run_idx+1}/{args.runs_per_car} on {vehicle.car_name}  seed={seed}",
                flush=True,
            )
            tracker = _RoundTracker(state_dir, tag, run_idx)

            # Hook round-level heartbeat via print wrapper
            import builtins
            orig_print = builtins.print
            def _round_print(*a, **kw):
                orig_print(*a, **kw)
                if a and isinstance(a[0], str):
                    m = a[0].lstrip()
                    if m.startswith("R") and len(m) >= 4:
                        j = 1
                        while j < len(m) and m[j] == " ":
                            j += 1
                        k = j
                        while k < len(m) and m[k].isdigit():
                            k += 1
                        if k > j:
                            try:
                                tracker.bump_round(int(m[j:k]))
                            except ValueError:
                                pass

            try:
                builtins.print = _round_print
                run = run_single_negotiation(
                    client=client,
                    model=args.model,
                    active_car=vehicle,
                    fleet=FLEET,
                    policy_key=cell.policy,
                    buyer_scheme=buyer_scheme,
                    n_rounds=args.n_rounds,
                    rng_seed=seed,
                    verbose=not args.quiet,
                )
            except _Killed:
                raise
            except Exception as e:
                print(f"   !! ERROR on run {run_idx+1}: {type(e).__name__}: {e}", flush=True)
                traceback.print_exc()
                run = {
                    "car": {
                        "car_name":         vehicle.car_name,
                        "market_price_new": float(vehicle.market_price_new),
                        "dealer_cost":      float(vehicle.dealer_cost),
                    },
                    "rng_seed":           seed,
                    "n_rounds_planned":   args.n_rounds,
                    "n_rounds_generated": 0,
                    "agreed":             False,
                    "agreement_round":    None,
                    "policy":             cell.policy,
                    "buyer_scheme":       cell.scheme,
                    "model":              args.model,
                    "error":              f"{type(e).__name__}: {e}",
                    "rounds":             [],
                }
            finally:
                builtins.print = orig_print

            runs.append(run)
            ps.update_state(
                state_dir, tag,
                runs_completed=len(runs),
                rounds_completed=sum(len(r.get("rounds", [])) for r in runs),
                last_run_idx=run_idx,
            )
            print(f"   run {run_idx+1} done in {(time.time()-run_t0)/60:.1f} min",
                  flush=True)

            # Checkpoint every 10 runs to bound the worst-case data loss.
            if (run_idx + 1) % 10 == 0 or (run_idx + 1) == args.runs_per_car:
                total_secs_so_far = time.time() - t_cell_start
                result = _assemble_result(cell, args, total_secs_so_far, runs)
                _save_checkpoint(out_path, result)
                ps.update_state(
                    state_dir, tag,
                    last_checkpoint_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                )
                print(f"   ---> checkpoint after run {run_idx+1}: "
                      f"{(time.time()-t_cell_start)/60:.1f} min elapsed, "
                      f"{len(runs)} runs saved to {out_path.name}",
                      flush=True)

        # --- success path ---
        total_secs = time.time() - t_cell_start
        result = _assemble_result(cell, args, total_secs, runs)
        _save_checkpoint(out_path, result)

        ps.update_state(
            state_dir, tag,
            status="finished",
            exit_code=0,
            ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        )
        print(
            f"\n=== FINISH {tag} in {total_secs/3600:.2f} h "
            f"({len(runs)} runs) -> {out_path} ===",
            flush=True,
        )
        return 0

    except _Killed as k:
        total_secs = time.time() - t_cell_start
        if runs:
            try:
                partial = _assemble_result(cell, args, total_secs, runs)
                _save_checkpoint(out_path, partial)
            except Exception:
                pass
        ps.update_state(
            state_dir, tag,
            status="killed",
            error=f"signal {k.signame}",
            exit_code=128,
            ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        )
        print(f"\n=== KILLED {tag} by {k.signame} after "
              f"{total_secs/60:.1f} min ({len(runs)} runs saved) ===",
              flush=True)
        return 130

    except Exception as e:
        total_secs = time.time() - t_cell_start
        tb = traceback.format_exc()
        if runs:
            try:
                partial = _assemble_result(cell, args, total_secs, runs)
                _save_checkpoint(out_path, partial)
            except Exception:
                pass
        ps.update_state(
            state_dir, tag,
            status="crashed",
            error=f"{type(e).__name__}: {e}",
            traceback=tb,
            exit_code=1,
            ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        )
        print(f"\n=== CRASHED {tag} after {total_secs/60:.1f} min: "
              f"{type(e).__name__}: {e} ===", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
