"""
launcher.py -- Spawn N parallel workers to chew through one side's worker cells.

Design:

  * The user side has 60 cells in the E-only setup
    (plan.worker_cells_for_side), each cell ~ 200 seller
    calls ~ 1.0 h on deepseek-reasoner.
  * With 30-parallel, the E-only sweep is about two 1.0 h waves.
  * The launcher keeps a FIXED pool of N slots; whenever a slot frees it
    immediately launches the next pending cell.  No global synchronization
    barriers -- cells finish at different times and the pool backfills.
  * Signal handling mirrors 0421: SIGTERM / SIGINT to the launcher cleanly
    SIGTERMs every child, which the worker's own handler turns into a
    "killed" status in state/.

Invocation:

    # finalize your side choice and run in background
    nohup python launcher.py --side user > launcher.out 2>&1 &

    # 30 workers is the default; change with --parallelism
    nohup python launcher.py --side user --parallelism 24 > launcher.out 2>&1 &

    # resume after a crash: skip cells whose state file says status=finished
    python launcher.py --side user --skip-finished

    # dry-run: print the planned work without spawning anything
    python launcher.py --side user --dry-run

Cooperator usage is identical with --side cooperator.
"""

from __future__ import annotations

import argparse
import datetime
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import config
import plan
import proc_state as ps


# ----------------------------------------------------------------------
# Child-process management
# ----------------------------------------------------------------------

def _spawn_worker(
    side: str,
    cell_index: int,
    tag: str,
    logs_dir: Path,
    python_exe: str,
) -> subprocess.Popen:
    """Launch one worker.py subprocess in the background, with stdout/err to logs/<tag>.log."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{tag}.log"
    log_fh = open(log_path, "w", buffering=1)  # line-buffered
    cmd = [
        python_exe, "-u", "worker.py",
        "--side", side,
        "--cell-index", str(cell_index),
    ]
    # start_new_session=True puts the child in its own process group so our
    # SIGINT from Ctrl+C doesn't auto-forward; we forward manually.
    p = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return p


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--side",         type=str, required=True, choices=["user", "cooperator"])
    ap.add_argument("--parallelism",  type=int, default=config.DEFAULT_PARALLELISM)
    ap.add_argument("--only",         type=int, nargs="+", default=None,
                    help="only run these cell indices (space-separated ints)")
    ap.add_argument("--skip-finished", action="store_true",
                    help="skip cells whose state/<tag>.state.json has status=finished")
    ap.add_argument("--output-dir",   type=str, default="results")
    ap.add_argument("--state-dir",    type=str, default="state")
    ap.add_argument("--logs-dir",     type=str, default="logs")
    ap.add_argument("--python",       type=str, default=sys.executable)
    ap.add_argument("--poll-seconds", type=float, default=5.0)
    ap.add_argument("--dry-run",      action="store_true")
    args = ap.parse_args()

    state_dir = Path(args.state_dir)
    logs_dir  = Path(args.logs_dir)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    cells = plan.worker_cells_for_side(args.side)

    # --- figure out which cells to run ---
    pending_idx: list[int] = list(range(len(cells))) if args.only is None else list(args.only)

    if args.skip_finished:
        keep: list[int] = []
        for i in pending_idx:
            tag = cells[i].tag
            state_file = ps.state_path(state_dir, tag)
            if state_file.exists():
                try:
                    import json
                    s = json.loads(state_file.read_text())
                    if s.get("status") == "finished":
                        continue
                except Exception:
                    pass
            keep.append(i)
        pending_idx = keep

    total_pending = len(pending_idx)

    print("=" * 80)
    print(f"Launcher  side={args.side}  host={socket.gethostname()}  pid={os.getpid()}")
    print(f"  cells to run    : {total_pending} / {len(cells)}")
    print(f"  parallelism     : {args.parallelism}")
    print(f"  base_seed       : {config.BASE_SEED}")
    print(f"  n_rounds        : {config.N_ROUNDS}")
    print(f"  runs_per_car    : {config.N_RUNS_PER_CAR}")
    print(f"  state_dir       : {state_dir}")
    print(f"  output_dir      : {args.output_dir}")
    print(f"  logs_dir        : {logs_dir}")
    print("=" * 80)

    if args.dry_run:
        for i in pending_idx:
            print(f"  [dry-run] cell {i:>3d}  {cells[i].tag}")
        return 0

    if total_pending == 0:
        print("nothing to do.")
        return 0

    # --- launcher state file ---
    launcher_started_at = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat(timespec="seconds")
    launcher_hostname = socket.gethostname()
    launcher_cwd = os.getcwd()

    def _initial_workers() -> list[dict]:
        return [
            {"tag": cells[i].tag, "experiment_index": i, "pid": None}
            for i in pending_idx
        ]

    def _write_launcher(status: str, workers: list[dict], ended_at: str | None = None) -> None:
        ps.write_launcher_state(
            state_dir,
            launcher_pid=os.getpid(),
            hostname=launcher_hostname,
            cwd=launcher_cwd,
            workers=workers,
            status=status,
            started_at=launcher_started_at,
            ended_at=ended_at,
        )

    _write_launcher(status="running", workers=_initial_workers())

    # --- signal handling: forward SIGTERM/SIGINT to all children ---
    running: dict[int, subprocess.Popen] = {}   # cell_index -> Popen

    def _current_workers() -> list[dict]:
        return [
            {"tag": cells[i].tag, "experiment_index": i,
             "pid": (running[i].pid if i in running else None)}
            for i in pending_idx
        ]

    def _term_children(signame: str = "SIGTERM"):
        for idx, p in list(running.items()):
            if p.poll() is None:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
        _write_launcher(
            status="interrupted",
            workers=_current_workers(),
            ended_at=datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(timespec="seconds"),
        )

    def _sig_handler(signum, frame):  # noqa: ANN001
        name = signal.Signals(signum).name
        print(f"\n[launcher] received {name}; SIGTERMing {len(running)} children...",
              flush=True)
        _term_children(name)
        # don't exit immediately -- let the main loop observe the children
        # finishing and write a clean ended_at
    signal.signal(signal.SIGINT,  _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    # --- pool loop ---
    pending: list[int] = list(pending_idx)
    started = 0
    finished = 0
    t0 = time.time()

    try:
        while pending or running:
            # Fill up to `parallelism` workers
            while pending and len(running) < args.parallelism:
                idx = pending.pop(0)
                tag = cells[idx].tag
                p = _spawn_worker(args.side, idx, tag, logs_dir, args.python)
                running[idx] = p
                started += 1
                # Record the child pid in launcher state
                _write_launcher(status="running", workers=_current_workers())
                print(f"[launcher] spawn cell {idx:>3d} tag={tag} pid={p.pid}  "
                      f"(running={len(running)} pending={len(pending)} finished={finished})",
                      flush=True)

            # Poll children
            time.sleep(args.poll_seconds)
            done_now: list[int] = []
            for idx, p in running.items():
                rc = p.poll()
                if rc is not None:
                    done_now.append(idx)
                    if rc == 0:
                        print(f"[launcher] cell {idx:>3d} FINISHED (rc=0)", flush=True)
                    else:
                        print(f"[launcher] cell {idx:>3d} EXITED rc={rc}  (check state file)",
                              flush=True)
            for idx in done_now:
                running.pop(idx, None)
                finished += 1

        # Normal completion
        elapsed_hrs = (time.time() - t0) / 3600
        _write_launcher(
            status="finished",
            workers=_current_workers(),
            ended_at=datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(timespec="seconds"),
        )
        print("=" * 80)
        print(f"[launcher] all {started} cells dispatched, {finished} observed finish, "
              f"elapsed {elapsed_hrs:.2f} h")
        print("=" * 80)
        return 0

    except KeyboardInterrupt:
        print("[launcher] KeyboardInterrupt at pool loop; terminating", flush=True)
        _term_children("KeyboardInterrupt")
        return 130


if __name__ == "__main__":
    sys.exit(main())
