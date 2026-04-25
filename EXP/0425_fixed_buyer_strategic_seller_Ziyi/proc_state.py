"""
proc_state.py -- Process-state tracking for the launcher + workers.

Design goals:
  * Every subprocess has one `state/<tag>.state.json` file it owns.
  * The file is rewritten atomically (tmp + os.replace) on every update,
    so an interrupted write never leaves a corrupt file.
  * Reads are safe to do concurrently (status.py can poll while workers
    are running).
  * The field set captures everything you'd want to answer after the fact:
        - Did it start?           (`spawned_at` set)
        - Is it running now?      (`status == "running"` AND heartbeat fresh)
        - When did it stop?       (`ended_at` set)
        - Why did it stop?        (`status`, `exit_code`, `error`)
        - How far did it get?     (`runs_completed`, `rounds_completed`,
                                   `last_car_idx`, `last_run_idx`)

Status lifecycle:
    spawned   -> running -> finished       (normal successful exit)
                        |-> crashed        (exception in worker)
                        |-> killed         (SIGTERM / SIGKILL / Ctrl+C)
                        |-> stalled        (no heartbeat for > STALL_SECS)

"stalled" is a *derived* status -- it's computed by status.py from the
heartbeat timestamp, never written by the worker itself, because a stalled
worker is by definition not writing anything any more.

Every write also sets `heartbeat_at = now`, so the "stalled" detection
works regardless of which other field was updated.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# How long a worker can go without a heartbeat before status.py calls it
# "stalled".  DeepSeek reasoner calls can take 30-60 s, so 10 minutes is
# comfortably beyond any legitimate pause.
STALL_SECS: int = 600


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state_path(state_dir: Path, tag: str) -> Path:
    return Path(state_dir) / f"{tag}.state.json"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """Write `payload` to `path` atomically: dump to a temp file in the same
    directory, then rename over the target.  os.replace is atomic on POSIX
    and on Windows (Python 3.3+).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # fsync unsupported on some filesystems
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup; don't shadow the real error.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_state(state_dir: Path, tag: str) -> dict[str, Any] | None:
    p = state_path(state_dir, tag)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def write_state(state_dir: Path, tag: str, payload: dict[str, Any]) -> None:
    _atomic_write(state_path(state_dir, tag), payload)


def update_state(
    state_dir: Path,
    tag: str,
    **updates: Any,
) -> dict[str, Any]:
    """Read-modify-write one state file, stamping heartbeat_at = now."""
    current = read_state(state_dir, tag) or {}
    current.update(updates)
    current["heartbeat_at"] = _now_iso()
    write_state(state_dir, tag, current)
    return current


# ----------------------------------------------------------------------
# Worker-side helpers
# ----------------------------------------------------------------------

def initial_worker_state(
    tag: str,
    experiment_index: int,
    pid: int,
    parent_pid: int | None,
    cmdline: list[str],
    hostname: str,
    cwd: str,
    config_summary: str,
    planned_runs: int,
    planned_rounds: int,
) -> dict[str, Any]:
    """Payload a worker writes on boot, before any LLM call."""
    return {
        "tag":               tag,
        "experiment_index":  experiment_index,
        "pid":               pid,
        "parent_pid":        parent_pid,
        "hostname":          hostname,
        "cwd":               cwd,
        "cmdline":           cmdline,
        "config_summary":    config_summary,
        "status":            "spawned",
        "spawned_at":        _now_iso(),
        "heartbeat_at":      _now_iso(),
        "started_at":        None,     # set when status transitions to "running"
        "ended_at":          None,
        "exit_code":         None,
        "error":             None,
        "planned_runs":      planned_runs,
        "planned_rounds":    planned_rounds,
        "runs_completed":    0,
        "rounds_completed":  0,
        "last_car_idx":      None,
        "last_run_idx":      None,
        "last_round":        None,
        "last_checkpoint_at": None,
    }


# ----------------------------------------------------------------------
# Launcher-side state
# ----------------------------------------------------------------------

LAUNCHER_STATE_FILENAME = "_launcher.state.json"


def launcher_state_path(state_dir: Path) -> Path:
    return Path(state_dir) / LAUNCHER_STATE_FILENAME


def write_launcher_state(
    state_dir: Path,
    launcher_pid: int,
    hostname: str,
    cwd: str,
    workers: list[dict[str, Any]],
    status: str,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> None:
    payload = {
        "launcher_pid":  launcher_pid,
        "hostname":      hostname,
        "cwd":           cwd,
        "status":        status,          # "running" | "finished" | "interrupted"
        "started_at":    started_at,
        "heartbeat_at":  _now_iso(),
        "ended_at":      ended_at,
        "workers":       workers,         # list of {tag, index, pid}
    }
    _atomic_write(launcher_state_path(state_dir), payload)


def read_launcher_state(state_dir: Path) -> dict[str, Any] | None:
    p = launcher_state_path(state_dir)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# ----------------------------------------------------------------------
# Derived status (reader-side)
# ----------------------------------------------------------------------

def derive_display_status(state: dict[str, Any], now_utc: datetime | None = None) -> str:
    """Compute the displayed status, including 'stalled' if heartbeats are stale."""
    raw = state.get("status", "unknown")
    if raw in ("finished", "crashed", "killed"):
        return raw
    if raw not in ("spawned", "running"):
        return raw

    hb = state.get("heartbeat_at")
    if not hb:
        return raw
    try:
        hb_dt = datetime.fromisoformat(hb)
    except ValueError:
        return raw
    if hb_dt.tzinfo is None:
        hb_dt = hb_dt.replace(tzinfo=timezone.utc)

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    age_s = (now_utc - hb_dt).total_seconds()
    if age_s > STALL_SECS:
        return "stalled"
    return raw
