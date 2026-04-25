"""
worker.py -- Run ONE of the 12 experiments in a dedicated Python process.

0423 LLM-buyer version. Same state-file + heartbeat model as the 0421
worker; the only substantive change is that each experiment now carries a
buyer schedule as well as a seller schedule, and run_single_negotiation is
called with both.

Usage:
    python worker.py --experiment-index N
                     [--output-dir DIR] [--state-dir DIR]
                     [--n-rounds N] [--runs-per-car N]
                     [--base-seed S] [--model M] [--buyer-model M]

Status lifecycle (same as 0421):
    spawned -> running -> finished | crashed | killed
    stalled  (derived by status.py from stale heartbeats)
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
from experiments import EXPERIMENTS
from negotiation import run_single_negotiation
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


def _assemble_result(exp: dict, args: argparse.Namespace,
                     total_secs: float, runs: list[dict]) -> dict:
    seller_schedule = exp["seller_schedule"]
    buyer_schedule  = exp["buyer_schedule"]
    return {
        "experiment": {
            "index":            exp["index"],
            "tag":              exp["tag"],
            "group":            exp["group"],
            "seller_strategy":  exp["seller_strategy"],
            "buyer_strategy":   exp["buyer_strategy"],
            "replicate":        exp["replicate"],
            "seller_schedule":  seller_schedule.to_dict(),
            "buyer_schedule":   buyer_schedule.to_dict(),
            "n_rounds":         args.n_rounds,
            "n_cars":           len(FLEET),
            "runs_per_car":     args.runs_per_car,
            "n_runs_total":     len(runs),
            "model":            args.model,
            "buyer_model":      args.buyer_model,
            "base_url":         args.base_url,
            "base_seed":        args.base_seed,
            "pid":              os.getpid(),
            "hostname":         socket.gethostname(),
            "total_seconds":    round(total_secs, 1),
            "total_minutes":    round(total_secs / 60, 2),
            "total_hours":      round(total_secs / 3600, 2),
            "timestamp":        datetime.datetime.now().isoformat(),
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
# Round-level hook: update state on every completed seller round
# ----------------------------------------------------------------------

class _RoundTracker:
    """Piggybacks on run_single_negotiation's verbose print to update the
    state file after each round (same mechanism as 0421)."""
    def __init__(self, state_dir: Path, tag: str, car_idx: int, run_idx: int):
        self.state_dir = state_dir
        self.tag = tag
        self.car_idx = car_idx
        self.run_idx = run_idx

    def bump_round(self, round_num: int) -> None:
        ps.update_state(
            self.state_dir, self.tag,
            last_round=round_num,
            last_car_idx=self.car_idx,
            last_run_idx=self.run_idx,
        )


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment-index", type=int, required=True)
    ap.add_argument("--output-dir",       type=str, default="results")
    ap.add_argument("--state-dir",        type=str, default="state")
    ap.add_argument("--n-rounds",         type=int, default=config.N_ROUNDS)
    ap.add_argument("--runs-per-car",     type=int, default=config.N_RUNS_PER_CAR)
    ap.add_argument("--base-seed",        type=int, default=config.BASE_SEED)
    ap.add_argument("--model",            type=str, default=config.DEEPSEEK_MODEL)
    ap.add_argument("--buyer-model",      type=str, default=config.DEEPSEEK_BUYER_MODEL)
    ap.add_argument("--base-url",         type=str, default=config.DEEPSEEK_BASE_URL)
    ap.add_argument("--api-key",          type=str, default=config.DEEPSEEK_API_KEY)
    ap.add_argument("--quiet",            action="store_true")
    args = ap.parse_args()

    if not (0 <= args.experiment_index < len(EXPERIMENTS)):
        print(f"ERROR: --experiment-index must be in [0, {len(EXPERIMENTS)})",
              file=sys.stderr, flush=True)
        return 2
    if not args.api_key:
        print("ERROR: no API key -- set NEGO_API_KEY or edit config.py.",
              file=sys.stderr, flush=True)
        return 2

    exp       = EXPERIMENTS[args.experiment_index]
    tag       = exp["tag"]
    seller_schedule = exp["seller_schedule"]
    buyer_schedule  = exp["buyer_schedule"]
    state_dir = Path(args.state_dir)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tag}.json"

    planned_runs   = len(FLEET) * args.runs_per_car
    planned_rounds = planned_runs * args.n_rounds

    # --- initial state file ---
    ps.write_state(state_dir, tag, ps.initial_worker_state(
        tag=tag,
        experiment_index=args.experiment_index,
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

    print(f"=== START {tag} ===", flush=True)
    print(f"    pid         : {os.getpid()}", flush=True)
    print(f"    hostname    : {socket.gethostname()}", flush=True)
    print(f"    state_file  : {state_dir / (tag + '.state.json')}", flush=True)
    print(f"    seller      : {seller_schedule.label}", flush=True)
    print(f"    buyer       : {buyer_schedule.label}", flush=True)
    print(f"    n_rounds    : {args.n_rounds}", flush=True)
    print(f"    n_cars      : {len(FLEET)}", flush=True)
    print(f"    runs/car    : {args.runs_per_car}", flush=True)
    print(f"    total runs  : {planned_runs}  (total rounds: {planned_rounds}, "
          f"total LLM calls \u2248 {planned_rounds * 2})", flush=True)
    print(f"    seller_model: {args.model}", flush=True)
    print(f"    buyer_model : {args.buyer_model}", flush=True)
    print(f"    base_url    : {args.base_url}", flush=True)
    print(f"    base_seed   : {args.base_seed}", flush=True)
    print(f"    output      : {out_path}", flush=True)
    sys.stdout.flush()

    ps.update_state(
        state_dir, tag,
        status="running",
        started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    )

    client = _build_client(args.api_key, args.base_url)

    t_exp_start = time.time()
    runs: list[dict] = []

    try:
        for car_idx, car in enumerate(FLEET):
            car_t0 = time.time()
            print(
                f"\n--- CAR {car_idx+1}/{len(FLEET)}: {car.car_name}"
                f"  (M=${float(car.market_price_new):,.2f}"
                f"  cost=${float(car.dealer_cost):,.2f}"
                f"  cost/M={float(car.dealer_cost)/float(car.market_price_new):.2%}) ---",
                flush=True,
            )
            ps.update_state(state_dir, tag, last_car_idx=car_idx)

            for run_idx in range(args.runs_per_car):
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
                tracker = _RoundTracker(state_dir, tag, car_idx, run_idx)

                # Hook the builtin print so per-round lines also heartbeat.
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
                                    rn = int(m[j:k])
                                    tracker.bump_round(rn)
                                except ValueError:
                                    pass
                try:
                    builtins.print = _round_print
                    run = run_single_negotiation(
                        client=client,
                        model=args.model,
                        active_car=car,
                        fleet=FLEET,
                        seller_schedule=seller_schedule,
                        buyer_schedule=buyer_schedule,
                        n_rounds=args.n_rounds,
                        rng_seed=seed,
                        verbose=not args.quiet,
                        buyer_model=args.buyer_model,
                    )
                except _Killed:
                    raise
                except Exception as e:
                    print(f"   !! ERROR on run {run_idx+1}: {type(e).__name__}: {e}",
                          flush=True)
                    traceback.print_exc()
                    run = {
                        "car": {
                            "car_name": car.car_name,
                            "market_price_new": float(car.market_price_new),
                            "dealer_cost": float(car.dealer_cost),
                        },
                        "rng_seed": seed,
                        "n_rounds": args.n_rounds,
                        "seller_schedule": seller_schedule.to_dict(),
                        "buyer_schedule":  buyer_schedule.to_dict(),
                        "model": args.model,
                        "buyer_model": args.buyer_model,
                        "error": f"{type(e).__name__}: {e}",
                        "rounds": [],
                    }
                finally:
                    builtins.print = orig_print

                runs.append(run)
                ps.update_state(
                    state_dir, tag,
                    runs_completed=len(runs),
                    rounds_completed=sum(len(r.get("rounds", [])) for r in runs),
                    last_car_idx=car_idx,
                    last_run_idx=run_idx,
                )
                print(f"   run {run_idx+1} done in {(time.time()-run_t0)/60:.1f} min",
                      flush=True)

            # --- checkpoint after every car ---
            total_secs_so_far = time.time() - t_exp_start
            result = _assemble_result(exp, args, total_secs_so_far, runs)
            _save_checkpoint(out_path, result)
            car_mins = (time.time() - car_t0) / 60
            total_mins = total_secs_so_far / 60
            print(
                f"\n   ---> checkpoint: car {car_idx+1}/{len(FLEET)} "
                f"done in {car_mins:.1f} min; "
                f"total so far {total_mins:.1f} min; "
                f"saved {len(runs)} runs to {out_path.name}",
                flush=True,
            )
            ps.update_state(
                state_dir, tag,
                last_checkpoint_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            )

        # --- success path ---
        total_secs = time.time() - t_exp_start
        result = _assemble_result(exp, args, total_secs, runs)
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
        total_secs = time.time() - t_exp_start
        if runs:
            try:
                partial = _assemble_result(exp, args, total_secs, runs)
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
        total_secs = time.time() - t_exp_start
        tb = traceback.format_exc()
        if runs:
            try:
                partial = _assemble_result(exp, args, total_secs, runs)
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
