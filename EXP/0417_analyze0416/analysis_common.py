"""
analysis_common.py — Shared helpers for the 0416b evaluation notebooks.

Usage from a notebook:
    from analysis_common import (
        load_all_runs, build_transitions_df, add_hinge_features,
        SELLER_STRATEGIES, NEGOTIATION_MASK,
    )

The loader walks the `results_0416b/` directory (produced by the
run_all_0416b_*.ipynb notebooks), extracts one row per (run, round t>=2)
transition, and returns a single tidy DataFrame.  It is agnostic to
whether the seller is fixed or adaptive; the per-round
`supplier_active_strategy` label is preserved on every row.
"""
from __future__ import annotations

import glob
import json
import os
import re
import warnings
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


SELLER_STRATEGIES = [
    "anchor_high", "cooperative",
    "boulware_seller", "conceder_seller",
    "tit_for_tat_matcher", "relational",
]

# ----------------------------------------------------------------------
# File discovery
# ----------------------------------------------------------------------

def discover_condition_files(
    results_root: str | Path = "results_0416b",
    notebooks: Iterable[str] | None = None,
) -> list[str]:
    """Return all per-condition JSONs under `results_root`.

    Skips `__all_transitions.json` and `__manifest.json` summary files.
    `notebooks` optionally restricts to specific sub-dirs (e.g. ["nb1","nb2"]).
    """
    root = Path(results_root)
    if not root.exists():
        warnings.warn(f"results_root '{root}' does not exist")
        return []
    if notebooks is None:
        pattern = str(root / "*" / "*.json")
    else:
        files = []
        for nb in notebooks:
            files.extend(glob.glob(str(root / nb / "*.json")))
        return sorted([f for f in files if not Path(f).name.startswith("__")])
    return sorted([f for f in glob.glob(pattern) if not Path(f).name.startswith("__")])


# ----------------------------------------------------------------------
# Transition extraction
# ----------------------------------------------------------------------

def _extract_transitions_from_run(run: dict, run_global_id: int,
                                  condition_tag: str,
                                  notebook_id: str) -> list[dict]:
    """
    One row per (round t, t>=2) transition.  Brings forward supplier price
    history (s_prev, s_prev2, s_prev3), merchant history (m_prev, m_prev2,
    m_prev3), product economics (v, cost, market), and per-round strategy
    labels on both sides.
    """
    rounds = run["rounds"]
    meta = run["metadata"]
    v = meta["v"]
    cost = meta["product"]["cost"]
    market = meta["product"]["market_price"]

    rows = []
    for i in range(1, len(rounds)):
        prev, curr = rounds[i - 1], rounds[i]
        s_prev = prev["supplier_price"]
        s_curr = curr["supplier_price"]
        m_curr = curr["buyer_price"]
        if s_prev is None or s_curr is None:
            # drop transitions where parsing failed on either side
            continue

        def lookup_s(k):
            return rounds[i - k]["supplier_price"] if i >= k else None

        def lookup_m(k):
            return rounds[i - k]["buyer_price"] if i >= k else None

        rows.append({
            # ── target and primary features ──
            "s_t": s_curr,
            "m_t": m_curr,
            "s_prev": s_prev,
            "m_prev": prev["buyer_price"],
            "s_prev2": lookup_s(2),
            "m_prev2": lookup_m(2),
            "s_prev3": lookup_s(3),
            "m_prev3": lookup_m(3),

            # ── economics ──
            "v": v,
            "cost": cost,
            "market": market,
            "category": meta["product"]["category"],
            "product": meta["product"]["name"],
            "quantity": meta["quantity"],

            # ── identifiers ──
            "round_t": curr["round"],
            "run_idx": run_global_id,
            "condition_tag": condition_tag,
            "notebook_id": notebook_id,

            # ── context ──
            "model": meta["model"],
            "supplier_id": meta["supplier"]["id"],
            "internal_cost": meta["supplier"]["internal_cost"],
            "buyer_type": meta["buyer_type"]["name"],

            # ── per-round strategy labels (work for both fixed & adaptive) ──
            "buyer_active_strategy": curr.get("buyer_active_strategy",
                                              meta["buyer_type"]["name"]),
            "supplier_active_strategy_curr": curr.get("supplier_active_strategy"),
            "supplier_active_strategy_prev": prev.get("supplier_active_strategy"),
            "seller_schedule_label": meta["seller_schedule"]["label"]
                if "seller_schedule" in meta else None,
            "seller_is_adaptive": meta["seller_schedule"]["is_adaptive"]
                if "seller_schedule" in meta else False,

            # ── template ──
            "template_id": curr.get("template_id", -1),
        })
    return rows


def load_all_runs(results_root: str | Path = "results_0416b",
                  notebooks: Iterable[str] | None = None,
                  verbose: bool = True) -> pd.DataFrame:
    """
    Load all per-condition JSONs into a single transitions DataFrame.

    Each row is ONE transition (round t≥2) in ONE run.  `run_idx` is
    globally unique across conditions (so group-by-run cross-validation
    works correctly even when mixing conditions).
    """
    files = discover_condition_files(results_root, notebooks)
    if verbose:
        print(f"[analysis_common] discovered {len(files)} condition files "
              f"under {results_root}")

    all_rows = []
    run_counter = 0
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            warnings.warn(f"  skipped {fp}: {e}")
            continue

        tag = Path(fp).stem
        nb_id = Path(fp).parent.name
        for run in data.get("runs", []):
            all_rows.extend(_extract_transitions_from_run(
                run, run_counter, tag, nb_id))
            run_counter += 1

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df = _add_region_labels(df)
    if verbose:
        print(f"[analysis_common] built {len(df)} transition rows from "
              f"{df['run_idx'].nunique()} unique runs")
    return df


def _add_region_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Region labels (same convention as the example notebooks):
      Low        : m_t < v              (merchant below break-even)
      Negotiation: v <= m_t <= s_prev   (in the bargaining zone)
      High       : m_t > s_prev         (merchant offers at/above seller's
                                          previous quote — would be accepted)
    """
    df = df.copy()
    df["region"] = np.where(
        df["m_t"] < df["v"], "Low",
        np.where(df["m_t"] > df["s_prev"], "High", "Negotiation"),
    )
    return df


NEGOTIATION_MASK = lambda df: df["region"] != "High"   # noqa: E731


# ----------------------------------------------------------------------
# Hinge / concession feature engineering
# ----------------------------------------------------------------------

def add_hinge_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add the hinge and concession features used throughout the analysis.

    Hinges on (m_t - v):
      diff_pos = max(m_t - v, 0)   # merchant above break-even
      diff_neg = max(v - m_t, 0)   # merchant below break-even

    Concession history hinges:
      ds_prev  = s_{t-1} - s_{t-2}
      ds_pos   = max( ds_prev, 0)   # seller RAISED quote (rare)
      ds_neg   = max(-ds_prev, 0)   # seller LOWERED quote (normal concession)

    Useful derived quantities:
      gap      = s_prev - m_t       (bargaining gap before this step)
      s_minus_v = s_prev - v        (seller's margin above break-even)

    Δ-target:
      delta_s = s_t - s_prev        (useful as an alternative to s_t to
                                      reduce collinearity between s_t and
                                      s_prev — see notebook 02).
    """
    df = df.copy()
    df["diff_pos"] = np.maximum(df["m_t"] - df["v"], 0.0)
    df["diff_neg"] = np.maximum(df["v"] - df["m_t"], 0.0)

    df["ds_prev"] = df["s_prev"] - df["s_prev2"]
    df["ds_pos"] = np.maximum(df["ds_prev"], 0.0)
    df["ds_neg"] = np.maximum(-df["ds_prev"], 0.0)

    df["gap"] = df["s_prev"] - df["m_t"]
    df["s_minus_v"] = df["s_prev"] - df["v"]

    df["delta_s"] = df["s_t"] - df["s_prev"]

    # Interactions with s_prev
    df["diffpos_x_sprev"] = df["diff_pos"] * df["s_prev"]
    df["diffneg_x_sprev"] = df["diff_neg"] * df["s_prev"]
    return df


# ----------------------------------------------------------------------
# Synthetic data for smoke-testing notebooks
# ----------------------------------------------------------------------

def generate_synthetic_results(
    out_root: str | Path,
    n_conditions_per_strategy: int = 2,
    n_runs_per_condition: int = 3,
    n_rounds: int = 15,
    strategies: list[str] | None = None,
    rng_seed: int = 0,
) -> None:
    """
    Create a small synthetic `results_0416b/`-style tree so the analysis
    notebooks can be validated without waiting for the 200-hour LLM sweep.
    The synthetic seller follows an approximate hinge-style decision rule:

      s_t = 0.65 * s_prev + 0.35 * c_target
      c_target = v + 0.25 * (market - v)
                  + strategy_offset
                  + gamma * diff_pos - delta * diff_neg

    with additive Gaussian noise.  This is enough to exercise the loader,
    the feature engineering, and the regression/plotting pipelines.
    """
    rng = np.random.default_rng(rng_seed)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    if strategies is None:
        strategies = SELLER_STRATEGIES

    strategy_to_nb = {s: f"nb{i+1}" for i, s in enumerate(strategies)}
    buyer_names = ["random", "budget", "wild", "concession", "anchor_drag"]

    strategy_params = {
        "anchor_high":          dict(offset=0.40, gamma=0.80, delta=0.10),
        "cooperative":          dict(offset=0.00, gamma=0.60, delta=0.50),
        "boulware_seller":      dict(offset=0.45, gamma=0.50, delta=0.05),
        "conceder_seller":      dict(offset=-0.20, gamma=0.70, delta=0.70),
        "tit_for_tat_matcher":  dict(offset=0.10, gamma=0.90, delta=0.30),
        "relational":           dict(offset=0.05, gamma=0.50, delta=0.40),
    }

    for strat in strategies:
        nb_dir = out_root / strategy_to_nb[strat]
        nb_dir.mkdir(parents=True, exist_ok=True)
        for cond_i in range(n_conditions_per_strategy):
            buyer = rng.choice(buyer_names)
            tag = f"sel_{strat}__buy_{buyer}"
            runs = []
            for ri in range(n_runs_per_condition):
                cost = rng.uniform(0.3, 5.0)
                markup = rng.uniform(2.0, 5.0)
                market = cost * markup
                internal = cost * rng.uniform(0.4, 1.8)
                v = cost + internal
                quantity = int(rng.integers(20, 80))

                rounds = []
                s_prev = market * rng.uniform(0.95, 1.05)      # opening high
                for t in range(1, n_rounds + 1):
                    # merchant offers from [cost, s_prev]
                    m_t = rng.uniform(cost, s_prev * 0.99)
                    diff_pos = max(m_t - v, 0.0)
                    diff_neg = max(v - m_t, 0.0)

                    p = strategy_params[strat]
                    c_target = (v + 0.25 * (market - v)
                                + p["offset"] * (market - v)
                                + p["gamma"] * diff_pos
                                - p["delta"] * diff_neg)
                    # blend with AR(1) on s_prev
                    s_new = 0.65 * s_prev + 0.35 * c_target
                    s_new += rng.normal(scale=0.02 * (market - cost))
                    # clamp to [v*0.95, market*1.1]
                    s_new = float(np.clip(s_new, v * 0.9, market * 1.15))

                    rounds.append({
                        "round": t,
                        "buyer_price": round(m_t, 3),
                        "buyer_message": f"offer round {t}",
                        "template_id": 0,
                        "buyer_active_strategy": buyer,
                        "supplier_active_strategy": strat,
                        "supplier_answer": f"counter: ${s_new:.2f}",
                        "supplier_reasoning": None,
                        "supplier_price": round(s_new, 3),
                        "supplier_system_prompt": "(stub)" if t == 1 else None,
                    })
                    s_prev = s_new

                runs.append({
                    "metadata": {
                        "model": "synthetic",
                        "product": {
                            "name": "Synthetic Item",
                            "category": "Synthetic",
                            "cost": round(cost, 3),
                            "market_price": round(market, 3),
                        },
                        "supplier": {
                            "id": "S1",
                            "name": "Synthetic supplier",
                            "internal_cost": round(internal, 3),
                        },
                        "v": round(v, 3),
                        "quantity": quantity,
                        "buyer_type": {"name": buyer,
                                       "description": "synthetic buyer",
                                       "type": "Synthetic"},
                        "seller_schedule": {
                            "label": strat,
                            "schedule": [strat] * n_rounds,
                            "is_adaptive": False,
                        },
                        "n_rounds": n_rounds,
                        "rng_seed": int(ri),
                        "timestamp": "2026-04-17T00:00:00",
                    },
                    "rounds": rounds,
                })

            with open(nb_dir / f"{tag}.json", "w", encoding="utf-8") as f:
                json.dump({
                    "condition": {"tag": tag},
                    "runs": runs,
                }, f)


def generate_synthetic_adaptive_results(
    out_root: str | Path,
    n_runs_per_schedule: int = 3,
    n_rounds: int = 15,
    switch_round: int = 8,
    rng_seed: int = 0,
) -> None:
    """
    Create a small synthetic `results_0416b/nb8/`-style tree with TWO-STAGE
    adaptive sellers that switch strategy at `switch_round`.  Used to
    smoke-test the change-point notebook.
    """
    rng = np.random.default_rng(rng_seed)
    out_root = Path(out_root) / "nb8"
    out_root.mkdir(parents=True, exist_ok=True)

    strategy_params = {
        "anchor_high":          dict(offset=0.40, gamma=0.80, delta=0.10),
        "cooperative":          dict(offset=0.00, gamma=0.60, delta=0.50),
        "boulware_seller":      dict(offset=0.45, gamma=0.50, delta=0.05),
        "conceder_seller":      dict(offset=-0.20, gamma=0.70, delta=0.70),
    }
    pairs = [("anchor_high", "cooperative"),
             ("boulware_seller", "conceder_seller")]

    for first, second in pairs:
        tag = f"sel2_{first}__{second}__r{switch_round}__buy_random"
        runs = []
        schedule = ([first] * (switch_round - 1)
                    + [second] * (n_rounds - switch_round + 1))
        for ri in range(n_runs_per_schedule):
            cost = rng.uniform(0.3, 5.0)
            markup = rng.uniform(2.0, 5.0)
            market = cost * markup
            internal = cost * rng.uniform(0.4, 1.8)
            v = cost + internal

            rounds = []
            s_prev = market * rng.uniform(0.95, 1.05)
            for t in range(1, n_rounds + 1):
                m_t = rng.uniform(cost, s_prev * 0.99)
                strat_t = schedule[t - 1]
                p = strategy_params[strat_t]
                diff_pos = max(m_t - v, 0.0)
                diff_neg = max(v - m_t, 0.0)
                c_target = (v + 0.25 * (market - v)
                            + p["offset"] * (market - v)
                            + p["gamma"] * diff_pos
                            - p["delta"] * diff_neg)
                s_new = 0.65 * s_prev + 0.35 * c_target
                s_new += rng.normal(scale=0.02 * (market - cost))
                s_new = float(np.clip(s_new, v * 0.9, market * 1.15))

                rounds.append({
                    "round": t,
                    "buyer_price": round(m_t, 3),
                    "buyer_message": f"offer {t}",
                    "template_id": 0,
                    "buyer_active_strategy": "random",
                    "supplier_active_strategy": strat_t,
                    "supplier_answer": f"counter {s_new:.2f}",
                    "supplier_reasoning": None,
                    "supplier_price": round(s_new, 3),
                    "supplier_system_prompt": "(stub)" if t == 1 else None,
                })
                s_prev = s_new

            runs.append({
                "metadata": {
                    "model": "synthetic",
                    "product": {
                        "name": "Synthetic Item",
                        "category": "Synthetic",
                        "cost": round(cost, 3),
                        "market_price": round(market, 3),
                    },
                    "supplier": {
                        "id": "S1",
                        "name": "Synthetic supplier",
                        "internal_cost": round(internal, 3),
                    },
                    "v": round(v, 3),
                    "quantity": 40,
                    "buyer_type": {"name": "random",
                                   "description": "synthetic",
                                   "type": "Synthetic"},
                    "seller_schedule": {
                        "label": f"{first}__then__{second}@r{switch_round}",
                        "schedule": schedule,
                        "is_adaptive": True,
                    },
                    "n_rounds": n_rounds,
                    "rng_seed": int(ri),
                    "timestamp": "2026-04-17T00:00:00",
                },
                "rounds": rounds,
            })
        with open(out_root / f"{tag}.json", "w", encoding="utf-8") as f:
            json.dump({"condition": {"tag": tag}, "runs": runs}, f)


# ----------------------------------------------------------------------
# Convenience plotting helpers
# ----------------------------------------------------------------------

def setup_plot_defaults():
    import matplotlib.pyplot as plt
    import seaborn as sns
    sns.set_style("whitegrid")
    plt.rcParams["figure.dpi"] = 110
    plt.rcParams["figure.figsize"] = (10, 5)
