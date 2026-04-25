"""
launcher.py -- Spawn all 12 worker processes, one per experiment.

Each worker is a subprocess that runs `worker.py --experiment-index N` with
its stdout/stderr captured to `logs/<tag>.log`. The launcher writes its own
state file at `state/_launcher.state.json` so status.py can recover PIDs.

SIGTERM / SIGINT on the launcher propagate to all children. Workers
themselves install SIGTERM / SIGINT handlers that flip their state file to
`killed` and flush a partial results JSON before exiting.

Usage:
    python launcher.py                 # run all 12
    python launcher.py --only 0 3 4    # run a subset
    python launcher.py --log-dir logs --state-dir state --output-dir results
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from experiments import EXPERIMENTS
import proc_state as ps


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _spawn_worker(
    idx: int,
    log_dir: Path,
    state_dir: Path,
    output_dir: Path,
    extra_args: list[str],
) -> tuple[subprocess.Popen, Path]:
    exp = EXPERIMENTS[idx]
    tag = exp["tag"]
    log_path = log_dir / f"{tag}.log"

    cmd = [
        sys.executable, "worker.py",
        "--experiment-index", str(idx),
        "--output-dir", str(output_dir),
        "--state-dir",  str(state_dir),
    ] + list(extra_args)

    log_fp = log_path.open("w", buffering=1, encoding="utf-8")
    # start_new_session so SIGINT at the terminal doesn't auto-propagate
    # (we install our own handlers to forward signals deliberately).
    proc = subprocess.Popen(
        cmd,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return proc, log_path


def _forward_signal_to_children(
    procs: list[subprocess.Popen],
    signame: str,
    sig: int,
) -> None:
    for p in procs:
        if p.poll() is None:
            try:
                os.kill(p.pid, sig)
                print(f"  sent {signame} to worker pid {p.pid}", flush=True)
            except ProcessLookupError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, nargs="*", default=None,
                    help="Subset of experiment indices to run (default: all 12).")
    ap.add_argument("--log-dir",    type=str, default="logs")
    ap.add_argument("--state-dir",  type=str, default="state")
    ap.add_argument("--output-dir", type=str, default="results")
    ap.add_argument("--extra", nargs=argparse.REMAINDER, default=[],
                    help="Everything after --extra is forwarded to each worker.")
    args = ap.parse_args()

    indices = args.only if args.only is not None else list(range(len(EXPERIMENTS)))
    indices = sorted(set(indices))
    for i in indices:
        if not (0 <= i < len(EXPERIMENTS)):
            print(f"ERROR: index {i} out of range [0, {len(EXPERIMENTS)})",
                  file=sys.stderr)
            return 2

    log_dir    = Path(args.log_dir);    log_dir.mkdir(parents=True, exist_ok=True)
    state_dir  = Path(args.state_dir);  state_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path(args.output_dir); output_dir.mkdir(parents=True, exist_ok=True)

    started_at = _now_iso()
    procs: list[subprocess.Popen] = []
    workers_meta: list[dict] = []

    print(f"=== LAUNCHER PID {os.getpid()}  host {socket.gethostname()} ===", flush=True)
    print(f"    spawning {len(indices)} workers  (indices: {indices})", flush=True)
    print(f"    log_dir={log_dir}  state_dir={state_dir}  output_dir={output_dir}",
          flush=True)

    for i in indices:
        exp = EXPERIMENTS[i]
        proc, log_path = _spawn_worker(
            i, log_dir, state_dir, output_dir, args.extra,
        )
        procs.append(proc)
        workers_meta.append({
            "tag":              exp["tag"],
            "experiment_index": i,
            "pid":              proc.pid,
        })
        print(f"    [{i:>2}] spawned pid={proc.pid}  tag={exp['tag']}  log={log_path}",
              flush=True)

    ps.write_launcher_state(state_dir, os.getpid(), socket.gethostname(), os.getcwd(), workers_meta, "running", started_at=started_at)

    # Forward SIGINT / SIGTERM to all children, then wait.
    def _handler(signum, frame):  # noqa: ANN001
        name = signal.Signals(signum).name
        print(f"\n*** launcher received {name}; forwarding to children ***", flush=True)
        _forward_signal_to_children(procs, name, signal.SIGTERM)
        ps.write_launcher_state(
            state_dir, os.getpid(), socket.gethostname(), os.getcwd(),
            workers_meta, "interrupted",
            started_at=started_at, ended_at=_now_iso(),
        )
    signal.signal(signal.SIGINT,  _handler)
    signal.signal(signal.SIGTERM, _handler)

    try:
        while True:
            alive = [p for p in procs if p.poll() is None]
            if not alive:
                break
            # refresh heartbeat
            ps.write_launcher_state(state_dir, os.getpid(), socket.gethostname(), os.getcwd(), workers_meta, "running", started_at=started_at)
            time.sleep(15)
    except KeyboardInterrupt:
        # Second Ctrl+C path -- hard kill.
        print("\n*** hard SIGKILL ***", flush=True)
        _forward_signal_to_children(procs, "SIGKILL", signal.SIGKILL)

    exit_codes = [p.poll() if p.poll() is not None else -1 for p in procs]
    print("\n=== all workers exited ===", flush=True)
    for meta, ec in zip(workers_meta, exit_codes):
        print(f"    [{meta['experiment_index']:>2}] pid={meta['pid']:>6}  "
              f"exit={ec}  tag={meta['tag']}", flush=True)

    ps.write_launcher_state(
        state_dir, os.getpid(), socket.gethostname(), os.getcwd(),
        workers_meta, "finished",
        started_at=started_at, ended_at=_now_iso(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
