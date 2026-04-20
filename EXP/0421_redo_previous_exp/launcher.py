"""
launcher.py -- Spawn 12 worker.py processes in parallel, one per experiment.

Each child is a fresh Python interpreter running:
    python -u worker.py --experiment-index <N>
                        --output-dir <RESULTS>
                        --state-dir  <STATE>

The launcher writes <state-dir>/_launcher.state.json containing its own PID
and the PID/tag of every worker it spawned.  Each worker in turn maintains
its own <state-dir>/<tag>.state.json.  Together these give you:

    * a single place to look up every running PID (for pkill by PID),
    * the tag / experiment index of every running worker,
    * per-worker status transitions (spawned / running / finished /
      crashed / killed) with timestamps,
    * per-worker progress (runs completed, rounds completed, last round).

Ctrl+C (SIGINT) and `kill <launcher_pid>` (SIGTERM) both trigger a clean
shutdown: the launcher SIGTERMs every child, waits for them to flush their
state files (they get a chance to record status=killed), and exits.
A second Ctrl+C hard-kills anything still alive.
"""

from __future__ import annotations

import argparse
import datetime
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from experiments import EXPERIMENTS
import proc_state as ps


# ----------------------------------------------------------------------
# Globals for signal handlers
# ----------------------------------------------------------------------

_PROCS: list[tuple[str, int, subprocess.Popen]] = []   # (tag, exp_idx, Popen)
_SHUTDOWN = threading.Event()
_STATE_DIR: Path = Path("state")
_LAUNCHER_STARTED_AT: str | None = None


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _write_launcher_state(status: str, ended_at: str | None = None) -> None:
    ps.write_launcher_state(
        state_dir=_STATE_DIR,
        launcher_pid=os.getpid(),
        hostname=socket.gethostname(),
        cwd=os.getcwd(),
        workers=[
            {"tag": tag, "experiment_index": idx, "pid": p.pid}
            for tag, idx, p in _PROCS
        ],
        status=status,
        started_at=_LAUNCHER_STARTED_AT,
        ended_at=ended_at,
    )


def _install_signal_handlers() -> None:
    def _handler(signum, frame):  # noqa: ANN001
        signame = signal.Signals(signum).name
        if _SHUTDOWN.is_set():
            print(f"\n[launcher] Second {signame} -- hard-killing workers.", flush=True)
            for _tag, _idx, p in _PROCS:
                if p.poll() is None:
                    try:
                        p.kill()
                    except Exception:
                        pass
            _write_launcher_state("interrupted", ended_at=_now_iso())
            sys.exit(130)
        _SHUTDOWN.set()
        print(f"\n[launcher] Caught {signame} -- terminating workers "
              f"(send signal again to hard-kill).", flush=True)
        for _tag, _idx, p in _PROCS:
            if p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass
        _write_launcher_state("interrupted", ended_at=_now_iso())
    # Both Ctrl+C and `kill <pid>` get the graceful path.
    signal.signal(signal.SIGINT,  _handler)
    signal.signal(signal.SIGTERM, _handler)


# ----------------------------------------------------------------------
# Per-worker stdout reader
# ----------------------------------------------------------------------

def _stream_reader(proc: subprocess.Popen, tag: str, log_path: Path) -> None:
    """Read proc.stdout line-by-line, fan out to:
        * launcher stdout, with a `[tag]` prefix,
        * logs/<tag>.log, without the prefix.
    """
    assert proc.stdout is not None
    with log_path.open("w", encoding="utf-8", buffering=1) as logf:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            print(f"[{tag}] {line}", flush=True)
            logf.write(line + "\n")
    try:
        proc.stdout.close()
    except Exception:
        pass


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> None:
    global _STATE_DIR, _LAUNCHER_STARTED_AT

    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=str, default="results")
    ap.add_argument("--logs-dir",   type=str, default="logs")
    ap.add_argument("--state-dir",  type=str, default="state")
    ap.add_argument("--stagger",    type=float, default=0.0,
                    help="Seconds between successive worker spawns. Use >0 if "
                         "your API provider rate-limits simultaneous openings.")
    ap.add_argument("--only",       type=int, nargs="*", default=None,
                    help="If set, only run these experiment indices (0..11).")
    args = ap.parse_args()

    results_dir = Path(args.output_dir)
    logs_dir    = Path(args.logs_dir)
    state_dir   = Path(args.state_dir)
    for d in (results_dir, logs_dir, state_dir):
        d.mkdir(parents=True, exist_ok=True)
    _STATE_DIR = state_dir

    env = os.environ.copy()

    selected = set(args.only) if args.only else set(e["index"] for e in EXPERIMENTS)
    to_run   = [e for e in EXPERIMENTS if e["index"] in selected]

    _LAUNCHER_STARTED_AT = _now_iso()
    _install_signal_handlers()

    print(f"[launcher] pid={os.getpid()}  hostname={socket.gethostname()}", flush=True)
    print(f"[launcher] spawning {len(to_run)} worker(s); "
          f"output -> {results_dir}, logs -> {logs_dir}, state -> {state_dir}",
          flush=True)
    import config as _cfg
    print(f"[launcher] config  : {_cfg.summarise()}", flush=True)

    here = Path(__file__).resolve().parent
    worker_path = here / "worker.py"

    threads: list[threading.Thread] = []
    t_block_start = time.time()

    _write_launcher_state("running")

    # --- spawn ---
    for exp in to_run:
        if _SHUTDOWN.is_set():
            break
        tag = exp["tag"]
        idx = exp["index"]
        cmd = [
            sys.executable, "-u", str(worker_path),
            "--experiment-index", str(idx),
            "--output-dir",       str(results_dir),
            "--state-dir",        str(state_dir),
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(here),
        )
        _PROCS.append((tag, idx, proc))
        print(f"[launcher] + spawned  [{tag}]  idx={idx}  pid={proc.pid}", flush=True)
        _write_launcher_state("running")   # includes the new PID
        th = threading.Thread(
            target=_stream_reader,
            args=(proc, tag, logs_dir / f"{tag}.log"),
            daemon=True,
        )
        th.start()
        threads.append(th)
        if args.stagger > 0:
            time.sleep(args.stagger)

    # --- wait ---
    statuses: list[tuple[str, int, int]] = []  # (tag, pid, rc)
    for tag, idx, proc in _PROCS:
        rc = proc.wait()
        statuses.append((tag, proc.pid, rc))
        print(f"[launcher] - finished  [{tag}]  pid={proc.pid}  rc={rc}", flush=True)
    for th in threads:
        th.join(timeout=5.0)

    total_min = (time.time() - t_block_start) / 60
    print(f"\n[launcher] ========= ALL WORKERS DONE in {total_min:.1f} min =========",
          flush=True)

    # --- summary (with state-file status) ---
    fails: list[str] = []
    for tag, pid, rc in statuses:
        st = ps.read_state(state_dir, tag) or {}
        status_str = st.get("status", "?")
        runs_done  = st.get("runs_completed", "?")
        ended_at   = st.get("ended_at", "?")
        note = ""
        if rc == 0 and status_str == "finished":
            note = "OK"
        else:
            note = f"FAIL (rc={rc}, status={status_str})"
            fails.append(tag)
        print(f"  {tag}: pid={pid}  rc={rc}  status={status_str}  "
              f"runs_done={runs_done}  ended_at={ended_at}  -> {note}",
              flush=True)

    _write_launcher_state("finished", ended_at=_now_iso())

    if fails:
        print(f"\n[launcher] {len(fails)} worker(s) failed: {fails}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
