"""
launcher.py — Spawn 12 worker.py processes in parallel, one per experiment.

This replaces the previous 12-notebook pattern. Each child is a fresh
Python interpreter running

    python -u worker.py --experiment-index <N> --output-dir <RESULTS>

The launcher:
  * inherits the current environment (OPENAI_API_KEY, NEGO_MODEL, etc.),
  * reads each child's combined stdout+stderr line-by-line from a dedicated
    reader thread,
  * prefixes every line with the experiment tag and mirrors it to the
    launcher's own stdout,
  * also writes the un-prefixed lines to logs/<tag>.log so each worker has
    its own clean log,
  * installs a SIGINT handler that terminates all children on Ctrl+C.

Typical use:
    export OPENAI_API_KEY=sk-...
    python launcher.py
    # or, to override the model:
    NEGO_MODEL=gpt-4o python launcher.py
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from experiments import EXPERIMENTS


# ----------------------------------------------------------------------
# Global bookkeeping so the signal handler can reach live processes
# ----------------------------------------------------------------------

_PROCS: list[tuple[str, subprocess.Popen]] = []
_SHUTDOWN = threading.Event()


def _install_sigint_handler() -> None:
    def _handler(signum, frame):  # noqa: ANN001
        if _SHUTDOWN.is_set():
            # second Ctrl+C -> hard kill everything immediately
            print("\n[launcher] Second interrupt — killing workers.", flush=True)
            for _tag, p in _PROCS:
                if p.poll() is None:
                    try:
                        p.kill()
                    except Exception:
                        pass
            sys.exit(130)
        _SHUTDOWN.set()
        print("\n[launcher] Interrupted — terminating workers "
              "(Ctrl+C again to hard-kill).", flush=True)
        for _tag, p in _PROCS:
            if p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass
    signal.signal(signal.SIGINT, _handler)


# ----------------------------------------------------------------------
# Per-worker output reader (runs in its own thread)
# ----------------------------------------------------------------------

def _stream_reader(proc: subprocess.Popen, tag: str, log_path: Path) -> None:
    """Read proc.stdout line-by-line and fan it out to:
        * launcher stdout, with a `[tag]` prefix, and
        * logs/<tag>.log, without the prefix.
    """
    assert proc.stdout is not None
    with log_path.open("w", encoding="utf-8", buffering=1) as logf:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            print(f"[{tag}] {line}", flush=True)
            logf.write(line + "\n")
    # Drain any remaining bytes (rare, but safe).
    try:
        proc.stdout.close()
    except Exception:
        pass


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=str, default="results",
                    help="Where worker.py writes <tag>.json files.")
    ap.add_argument("--logs-dir",   type=str, default="logs",
                    help="Where per-worker .log files are mirrored.")
    ap.add_argument("--stagger",    type=float, default=0.0,
                    help="Seconds to wait between spawning successive workers. "
                         "Use a positive value if your API provider's rate "
                         "limiter dislikes 12 simultaneous first requests.")
    ap.add_argument("--only",       type=int, nargs="*", default=None,
                    help="If set, only run these experiment indices (0..11). "
                         "Useful for resuming or debugging a subset.")
    args = ap.parse_args()

    results_dir = Path(args.output_dir)
    logs_dir    = Path(args.logs_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Pass the environment through unchanged; workers pick up NEGO_* vars
    # (if any were exported) and otherwise fall back to config.py defaults.
    env = os.environ.copy()

    _install_sigint_handler()

    here = Path(__file__).resolve().parent
    worker_path = here / "worker.py"

    selected = set(args.only) if args.only else set(e["index"] for e in EXPERIMENTS)
    to_run   = [e for e in EXPERIMENTS if e["index"] in selected]

    print(f"[launcher] spawning {len(to_run)} worker(s); "
          f"output -> {results_dir}, logs -> {logs_dir}", flush=True)
    import config as _cfg
    print(f"[launcher] config : {_cfg.summarise()}", flush=True)

    threads: list[threading.Thread] = []
    t_block_start = time.time()

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
        ]
        print(f"[launcher] + spawning  [{tag}]  (idx={idx})", flush=True)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(here),
        )
        _PROCS.append((tag, proc))
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
    statuses: list[tuple[str, int]] = []
    for tag, proc in _PROCS:
        rc = proc.wait()
        statuses.append((tag, rc))
        print(f"[launcher] - finished  [{tag}]  rc={rc}", flush=True)
    for th in threads:
        th.join(timeout=5.0)

    total_min = (time.time() - t_block_start) / 60
    print(f"\n[launcher] ========= ALL WORKERS DONE in {total_min:.1f} min =========",
          flush=True)
    fails: list[str] = []
    for tag, rc in statuses:
        if rc == 0:
            print(f"  {tag}: OK")
        else:
            print(f"  {tag}: FAIL (rc={rc})")
            fails.append(tag)

    if fails:
        print(f"\n[launcher] {len(fails)} worker(s) failed: {fails}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
