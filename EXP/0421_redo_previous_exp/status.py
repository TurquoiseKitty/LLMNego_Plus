"""
status.py -- One-shot status report of the current / most-recent sweep.

Reads <state-dir>/*.state.json and prints a compact table of each worker's
current status, runs completed, progress %, last heartbeat age, and PID.

Usage:
    python status.py                  # one-shot report
    python status.py --watch          # refresh every 10 s
    python status.py --watch --interval 30
    python status.py --kill-all       # pkill every live worker + launcher
                                      # (reads PIDs straight out of state/)

`--kill-all` is a convenience wrapper: for every worker whose state file
says status == "running" or "spawned" (and whose PID is still alive), it
sends SIGTERM.  The workers' own signal handlers then re-stamp their state
files as status="killed" and exit.  It also SIGTERMs the launcher PID.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import proc_state as ps
from experiments import EXPERIMENTS


LIVE_STATUSES = {"spawned", "running"}
DEAD_STATUSES = {"finished", "crashed", "killed", "stalled"}


def _age_seconds(iso: str | None, now: datetime) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds()


def _fmt_age(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 90 * 60:
        return f"{seconds/60:.1f}m"
    return f"{seconds/3600:.1f}h"


def _pid_alive(pid: int | None) -> bool | None:
    """True / False / None (None means we don't know, e.g. permission denied)."""
    if pid is None:
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # it exists, we just can't signal it
    except OSError:
        return None


def render_report(state_dir: Path) -> str:
    now = datetime.now(timezone.utc)

    launcher = ps.read_launcher_state(state_dir)
    lines: list[str] = []
    lines.append("=" * 96)
    if launcher:
        l_age = _age_seconds(launcher.get("heartbeat_at"), now)
        lines.append(
            f"Launcher: pid={launcher.get('launcher_pid')}  "
            f"status={launcher.get('status')}  "
            f"host={launcher.get('hostname')}  "
            f"started={launcher.get('started_at')}  "
            f"hb_age={_fmt_age(l_age)}"
        )
    else:
        lines.append("Launcher: <no launcher state file>")
    lines.append("=" * 96)
    lines.append(
        f"{'tag':<45} {'pid':>7} {'status':<10} {'runs':>9} "
        f"{'progress':>9} {'car':>4} {'round':>5} {'hb':>6} {'alive':>5}"
    )
    lines.append("-" * 96)

    totals = {"live": 0, "finished": 0, "crashed": 0, "killed": 0, "stalled": 0, "none": 0}
    for exp in EXPERIMENTS:
        tag = exp["tag"]
        st = ps.read_state(state_dir, tag)
        if st is None:
            lines.append(f"{tag:<45} {'-':>7} {'(none)':<10} "
                         f"{'-':>9} {'-':>9} {'-':>4} {'-':>5} {'-':>6} {'-':>5}")
            totals["none"] += 1
            continue

        status = ps.derive_display_status(st, now_utc=now)
        runs_done   = st.get("runs_completed", 0) or 0
        planned     = st.get("planned_runs") or 0
        rounds_done = st.get("rounds_completed", 0) or 0
        planned_r   = st.get("planned_rounds") or 0
        car_idx     = st.get("last_car_idx")
        run_idx     = st.get("last_run_idx")
        last_round  = st.get("last_round")
        hb_age      = _age_seconds(st.get("heartbeat_at"), now)

        pid = st.get("pid")
        alive = _pid_alive(pid)
        alive_str = "?" if alive is None else ("yes" if alive else "no")

        runs_str = f"{runs_done}/{planned}" if planned else str(runs_done)
        pct = (rounds_done / planned_r * 100) if planned_r else 0.0
        pct_str = f"{pct:5.1f}%"
        car_str = f"{(car_idx+1) if car_idx is not None else '-'}/5"
        run_str = (f"{last_round}" if last_round is not None else "-")

        # Tally
        if status == "finished":
            totals["finished"] += 1
        elif status == "crashed":
            totals["crashed"] += 1
        elif status == "killed":
            totals["killed"] += 1
        elif status == "stalled":
            totals["stalled"] += 1
        else:
            totals["live"] += 1

        lines.append(
            f"{tag:<45} {pid or '-':>7} {status:<10} "
            f"{runs_str:>9} {pct_str:>9} {car_str:>4} {run_str:>5} "
            f"{_fmt_age(hb_age):>6} {alive_str:>5}"
        )

    lines.append("-" * 96)
    lines.append(
        f"Totals:  live={totals['live']}  finished={totals['finished']}  "
        f"crashed={totals['crashed']}  killed={totals['killed']}  "
        f"stalled={totals['stalled']}  no_state_file={totals['none']}"
    )
    lines.append("Notes:")
    lines.append("   * 'stalled' = status claims running but heartbeat is >10 min old")
    lines.append(f"                (the process likely died without writing an obituary)")
    lines.append("   * 'alive'   = kill(pid, 0) succeeds right now")
    return "\n".join(lines)


def kill_all(state_dir: Path) -> int:
    """Send SIGTERM to every apparently-alive worker + the launcher.

    Returns the number of processes signalled.
    """
    now = datetime.now(timezone.utc)
    signalled = 0

    for exp in EXPERIMENTS:
        tag = exp["tag"]
        st = ps.read_state(state_dir, tag)
        if st is None:
            continue
        pid = st.get("pid")
        status = ps.derive_display_status(st, now_utc=now)
        if status not in LIVE_STATUSES:
            continue
        if not _pid_alive(pid):
            print(f"  [{tag}] pid={pid}  status={status} but pid not alive -- skipping")
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"  [{tag}] SIGTERM sent to pid={pid}")
            signalled += 1
        except ProcessLookupError:
            print(f"  [{tag}] pid={pid} disappeared before we could signal it")

    launcher = ps.read_launcher_state(state_dir)
    if launcher:
        lpid = launcher.get("launcher_pid")
        lstatus = launcher.get("status")
        if lstatus == "running" and _pid_alive(lpid):
            try:
                os.kill(lpid, signal.SIGTERM)
                print(f"  [launcher] SIGTERM sent to pid={lpid}")
                signalled += 1
            except ProcessLookupError:
                print(f"  [launcher] pid={lpid} disappeared before we could signal it")
    return signalled


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", type=str, default="state")
    ap.add_argument("--watch",     action="store_true",
                    help="Refresh the report every --interval seconds.")
    ap.add_argument("--interval",  type=int, default=10,
                    help="Refresh interval in seconds when --watch is set.")
    ap.add_argument("--kill-all",  action="store_true",
                    help="SIGTERM every live worker and the launcher.")
    args = ap.parse_args()

    state_dir = Path(args.state_dir)

    if args.kill_all:
        print("[status] Sending SIGTERM to every live worker and the launcher...")
        n = kill_all(state_dir)
        print(f"[status] Signalled {n} process(es).")
        print("[status] Wait a few seconds, then run `python status.py` again "
              "to confirm their state files flipped to 'killed'.")
        return 0

    if not args.watch:
        print(render_report(state_dir))
        return 0

    # --watch loop
    try:
        while True:
            os.system("clear" if os.name != "nt" else "cls")
            print(render_report(state_dir))
            print(f"\n(refreshing every {args.interval}s -- Ctrl+C to exit)")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[status] exiting watch loop.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
