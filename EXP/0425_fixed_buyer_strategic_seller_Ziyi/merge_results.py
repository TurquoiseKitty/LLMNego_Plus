"""
merge_results.py -- Combine user and cooperator outputs into a unified dataset.

Expected tags come directly from plan.worker_cells_for_side(...), so this
script adapts automatically to the current scheme configuration (including
E-only runs).

This script:

  1. Reads all results/*.json under --user-dir and --cooperator-dir.
  2. Validates that the combined set has exactly the expected 120 tags, no
     duplicates, no missing, and that every file looks intact (runs list
     non-empty, no unexpected schema holes).
  3. Optionally concatenates everything into a single results/<policy>/
     directory structure, or a single flat JSON index.

Usage:
    # just audit what's there
    python merge_results.py --user-dir user_side/results \
                              --cooperator-dir coop_side/results \
                              --audit-only

    # also copy the combined set into ./merged_results/
    python merge_results.py --user-dir user_side/results \
                              --cooperator-dir coop_side/results \
                              --out-dir merged_results

    # and build a CSV manifest of the combined set
    python merge_results.py --user-dir user_side/results \
                              --cooperator-dir coop_side/results \
                              --out-dir merged_results \
                              --manifest merged_manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import plan


def _expected_user_tags() -> set[str]:
    return {c.tag for c in plan.worker_cells_for_side("user")}


def _expected_cooperator_tags() -> set[str]:
    return {c.tag for c in plan.worker_cells_for_side("cooperator")}


def _json_load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _validate_result(path: Path, data: dict, expected_tag: str) -> list[str]:
    """Return a list of problem strings (empty if clean)."""
    problems: list[str] = []
    exp = data.get("experiment") or {}
    if exp.get("tag") != expected_tag:
        problems.append(f"tag mismatch: file has tag={exp.get('tag')!r} but path says {expected_tag!r}")
    runs = data.get("runs") or []
    if not isinstance(runs, list):
        problems.append(f"runs is not a list")
    elif len(runs) == 0:
        problems.append(f"runs list is empty")
    else:
        # Check every run has a rounds list
        short_runs = [i for i, r in enumerate(runs) if len(r.get("rounds", [])) == 0]
        if short_runs:
            problems.append(f"{len(short_runs)} runs with zero rounds (indices: {short_runs[:5]}...)")
    return problems


def _scan_side(results_dir: Path, expected_tags: set[str], label: str
               ) -> tuple[dict[str, Path], list[str]]:
    """Return (found tag->path mapping, list of audit problems)."""
    problems: list[str] = []
    found: dict[str, Path] = {}

    if not results_dir.exists():
        if not expected_tags:
            return found, problems
        problems.append(f"[{label}] directory not found: {results_dir}")
        return found, problems

    for p in sorted(results_dir.glob("*.json")):
        tag = p.stem
        if tag in found:
            problems.append(f"[{label}] duplicate tag {tag} (second at {p})")
        found[tag] = p

    missing = expected_tags - set(found)
    unexpected = set(found) - expected_tags
    if missing:
        problems.append(f"[{label}] missing {len(missing)} tag(s): {sorted(missing)[:5]}...")
    if unexpected:
        problems.append(f"[{label}] unexpected {len(unexpected)} tag(s): {sorted(unexpected)[:5]}...")

    # Content validation on every expected file that's present
    for tag in sorted(expected_tags & set(found)):
        try:
            data = _json_load(found[tag])
        except Exception as e:
            problems.append(f"[{label}] {tag}: JSON load failed: {type(e).__name__}: {e}")
            continue
        for prob in _validate_result(found[tag], data, tag):
            problems.append(f"[{label}] {tag}: {prob}")

    return found, problems


def _copy_into(out_dir: Path, found: dict[str, Path], side_label: str) -> list[str]:
    """Copy all files from `found` into out_dir.  Returns list of (relative) output paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for tag, src in found.items():
        dst = out_dir / f"{tag}.json"
        if dst.exists():
            print(f"  [warn] overwriting existing {dst}")
        shutil.copy2(src, dst)
        written.append(str(dst.relative_to(out_dir.parent) if dst.is_relative_to(out_dir.parent) else dst))
    return written


def _write_manifest(manifest_path: Path, user_found: dict[str, Path],
                    coop_found: dict[str, Path]) -> None:
    """Per-file row: tag, side, scheme, policy, vehicle_idx, n_runs, path."""
    cells_by_tag = {
        c.tag: c for side in ("user", "cooperator")
        for c in plan.worker_cells_for_side(side)
    }
    rows: list[dict] = []
    for tag, src in list(user_found.items()) + list(coop_found.items()):
        cell = cells_by_tag.get(tag)
        try:
            data = _json_load(src)
        except Exception:
            data = {}
        runs = data.get("runs") or []
        rows.append({
            "tag":          tag,
            "side":         cell.side if cell else "unknown",
            "scheme":       cell.scheme if cell else "unknown",
            "policy":       cell.policy if cell else "unknown",
            "vehicle_idx":  cell.vehicle_idx if cell else -1,
            "n_runs":       len(runs),
            "n_turns":      sum(len(r.get("rounds", [])) for r in runs),
            "src_path":     str(src),
        })
    rows.sort(key=lambda r: (r["scheme"], r["policy"], r["vehicle_idx"]))
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                             ["tag","side","scheme","policy","vehicle_idx","n_runs","n_turns","src_path"])
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-dir",       type=str, required=True)
    ap.add_argument("--cooperator-dir", type=str, required=True)
    ap.add_argument("--out-dir",        type=str, default=None,
                    help="If set, copy all expected files into this directory.")
    ap.add_argument("--audit-only",     action="store_true",
                    help="Do not copy or write a manifest, just audit.")
    ap.add_argument("--manifest",       type=str, default=None,
                    help="If set, write a CSV manifest of the merged dataset.")
    args = ap.parse_args()

    user_dir = Path(args.user_dir)
    coop_dir = Path(args.cooperator_dir)

    exp_user = _expected_user_tags()
    exp_coop = _expected_cooperator_tags()
    exp_total = len(exp_user) + len(exp_coop)

    user_found, user_probs = _scan_side(user_dir, exp_user, "user")
    coop_found, coop_probs = _scan_side(coop_dir, exp_coop, "cooperator")

    # Cross-check: no tag should appear on both sides
    cross = set(user_found) & set(coop_found)
    cross_probs: list[str] = []
    if cross:
        cross_probs.append(f"tags present on BOTH sides (should be impossible): {sorted(cross)[:5]}...")

    all_probs = user_probs + coop_probs + cross_probs

    # --- report ---
    print("=" * 80)
    print(f"User side     ({user_dir}):        found {len(user_found)}/{len(exp_user)} files")
    print(f"Cooperator side ({coop_dir}):      found {len(coop_found)}/{len(exp_coop)} files")
    print(f"Combined unique tags: {len(set(user_found) | set(coop_found))}/{exp_total}")
    print("=" * 80)

    if all_probs:
        print("PROBLEMS:")
        for p in all_probs:
            print(f"  - {p}")
        if args.audit_only:
            return 1 if all_probs else 0
    else:
        print("No problems detected.")

    if args.audit_only:
        return 0

    # --- copy into out-dir if requested ---
    if args.out_dir:
        out_dir = Path(args.out_dir)
        print(f"\nCopying up to {exp_total} files into {out_dir} ...")
        _copy_into(out_dir, user_found, "user")
        _copy_into(out_dir, coop_found, "cooperator")
        print(f"  wrote {len(user_found) + len(coop_found)} files to {out_dir}")

    # --- manifest ---
    if args.manifest:
        manifest_path = Path(args.manifest)
        _write_manifest(manifest_path, user_found, coop_found)
        print(f"  wrote manifest -> {manifest_path}")

    return 0 if not all_probs else 1


if __name__ == "__main__":
    sys.exit(main())
