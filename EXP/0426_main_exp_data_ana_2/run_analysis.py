"""
run_analysis.py
===============

Main entry point for the v15 analysis of the used-car bargaining experiment.

Usage (from inside the bundle directory):
    python run_analysis.py --data_dir /path/to/merged_results --out_dir ./out

The script:
  1. Loads all 120 JSON files.
  2. Runs preprocessing.
  3. For every (scheme, policy) combination, pools all 5 vehicles and runs
     grouped 10-fold CV on every (feature_family, model) pair.
  4. Performs Stage 1 + Stage 2 selection per (scheme, policy).
  5. Writes:
       - out/turns_summary.csv          counts before/after each filter
       - out/leaderboard_full.csv       every (scheme, policy, family, model) row
       - out/selected_linear.csv        the chosen linear spec per (scheme, policy)
       - out/feature_summary.csv        family descriptions
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import negolin_v15 as nv


MODELS = ("Base", "OLS", "Ridge", "GBR")     # MLP dropped per user's request


def build_leaderboard_for_group(turns: pd.DataFrame,
                                scheme: str,
                                policy: str,
                                verbose: bool = False) -> pd.DataFrame:
    """For a given (scheme, policy) subset of `turns`, run every
    (feature family, model) pair and return one row per pair."""
    subset = turns.loc[(turns["scheme"] == scheme)
                       & (turns["policy"] == policy)].copy()
    rows = []

    # --- Base is a special one-off: use Base feature spec everywhere
    for family_name in ["Base"] + list(nv.FEATURE_SPECS.keys()):
        meta, X, y, cols = nv.build_design_matrix(subset, family_name)
        if len(meta) == 0:
            continue

        # Partition: use D_negotiation only for train/eval
        (_, _, _), (meta_neg, X_neg, y_neg) = nv.partition_persist(meta, X, y)
        n_full = len(meta)
        n_neg  = len(meta_neg)
        if n_neg < nv.OUTER_FOLDS * 2:
            # Not enough data in negotiation stage
            continue

        family_key = family_name   # 'Base' | 'I' | ... | 'VII'
        if family_name == "Base":
            # Base uses its own S_tilde_t ~ S_tilde_{t-1} regression and is only
            # meaningful as Base -> skip other model names.
            model_list = ["Base"]
        else:
            model_list = [m for m in MODELS if m != "Base"]

        for model_name in model_list:
            t0 = time.time()
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    pred_df, alphas = nv.grouped_cv_predict(
                        meta_neg, X_neg, y_neg, model_name,
                        n_splits=nv.OUTER_FOLDS, seed=nv.RANDOM_SEED)
                    m = nv.cv_metrics(pred_df)
            except Exception as e:
                if verbose:
                    print(f"[{scheme}/{policy}/{family_key}/{model_name}] failed: {e}")
                continue
            elapsed = time.time() - t0

            # For linear models, also fit an OLS on *all* of X_neg/y_neg to get
            # theta_l1 (we use the fitted OLS coefficient vector as the
            # parsimony proxy; ridge's shrinkage lives in alpha, but the l1
            # of its coefficients is meaningful too if fit on the whole set).
            theta_l1 = np.nan
            if model_name in ("OLS",) or model_name.startswith("Ridge"):
                if model_name == "OLS":
                    theta = nv.fit_theta_ols(X_neg, y_neg)
                else:
                    # Refit Ridge on the whole split, with alpha = median of CV picks
                    alpha = float(np.nanmedian(alphas)) if len(alphas) else 1.0
                    from sklearn.preprocessing import StandardScaler
                    from sklearn.linear_model import Ridge
                    from sklearn.pipeline import Pipeline
                    est = Pipeline([("scale", StandardScaler()),
                                    ("m", Ridge(alpha=alpha))]).fit(X_neg, y_neg)
                    coefs = est.named_steps["m"].coef_
                    intercept = est.named_steps["m"].intercept_
                    theta = np.concatenate([[intercept], coefs])
                theta_l1 = float(np.sum(np.abs(theta)))

            if family_name == "Base":
                dim_phi = nv.BASE_SPEC["dim"]
                tau     = nv.BASE_SPEC["tau"]
            else:
                dim_phi = nv.FEATURE_SPECS[family_name]["dim"]
                tau     = nv.FEATURE_SPECS[family_name]["tau"]

            rows.append({
                "scheme":    scheme,
                "policy":    policy,
                "family":    family_key,
                "model":     model_name,
                "n":         m["n"],
                "n_full":    n_full,
                "frac_neg":  n_neg / max(n_full, 1),
                "mae":       m["mae"],
                "mae_se":    m["mae_se"],
                "mae_dollar":  m["mae_dollar"],
                "mape":      m["mape"],
                "mape_dollar": m["mape_dollar"],
                "bias":      m["bias"],
                "rmse":      m["rmse"],
                "dim_phi":   dim_phi,
                "tau":       tau,
                "theta_l1":  theta_l1,
                "alpha_med": float(np.nanmedian(alphas)) if len(alphas) else np.nan,
                "elapsed_s": elapsed,
            })

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", required=True, type=str,
                        help="Directory containing the 120 JSON result files")
    parser.add_argument("--out_dir", default="./out", type=str)
    parser.add_argument("--schemes", nargs="+", default=list(nv.SCHEMES))
    parser.add_argument("--policies", nargs="+", default=list(nv.POLICIES))
    parser.add_argument("--skip_gbr", action="store_true",
                        help="Skip GradientBoosting for a quicker run")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Loading data from {args.data_dir} ...")
    raw = nv.load_run_files(args.data_dir, schemes=args.schemes, policies=args.policies)
    print(f"      raw rows = {len(raw):,}, unique runs = {raw['run_id'].nunique():,}")

    print("[2/4] Preprocessing turns ...")
    marked, turns = nv.preprocess_turns(raw)

    # Counts for the paper
    summary_rows = []
    for (sch, pol), g in turns.groupby(["scheme", "policy"]):
        n_rows_all = len(g)
        n_rows_in_rng = int(g["round"].between(nv.MODEL_ROUND_MIN, nv.MODEL_ROUND_MAX).sum())
        # Build a "full" design matrix using feature VII (most restrictive lags)
        meta7, X7, y7, _ = nv.build_design_matrix(g.assign(scheme=sch, policy=pol), "VII")
        n_model_rows = len(meta7)
        (_, _, _), (_, _, y_neg) = nv.partition_persist(meta7, X7, y7)
        n_neg = len(y_neg)
        n_runs = int(g["run_id"].nunique())
        summary_rows.append({
            "scheme": sch, "policy": pol,
            "n_rows_all_turns": n_rows_all,
            "n_rows_in_round_range": n_rows_in_rng,
            "n_model_rows_VII":  n_model_rows,
            "n_negotiation_VII": n_neg,
            "frac_neg_VII":      n_neg / max(n_model_rows, 1),
            "n_runs":            n_runs,
        })
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out_dir / "turns_summary.csv", index=False)
    print(summary.to_string(index=False))

    print("[3/4] Fitting models for every (scheme, policy, family, model) ...")
    if args.skip_gbr:
        globals()["MODELS"] = tuple(m for m in MODELS if m != "GBR")
        print(f"      MODELS = {MODELS}")

    leaderboards = []
    for scheme in args.schemes:
        for policy in args.policies:
            print(f"   -> scheme={scheme}, policy={policy} ...")
            lb = build_leaderboard_for_group(turns, scheme, policy, verbose=True)
            leaderboards.append(lb)
    leaderboard = pd.concat(leaderboards, ignore_index=True)
    leaderboard.to_csv(out_dir / "leaderboard_full.csv", index=False)

    print("[4/4] Running two-stage selection per (scheme, policy) ...")
    picks = []
    for (sch, pol), lb in leaderboard.groupby(["scheme", "policy"]):
        lb = lb.dropna(subset=["mae"])
        if len(lb) == 0:
            continue
        result = nv.stage_selection(lb)
        picks.append({
            "scheme": sch, "policy": pol,
            "best_family":  result["best_row"]["family"],
            "best_model":   result["best_row"]["model"],
            "best_mae":     result["best_row"]["mae"],
            "best_mae_dollar": result["best_row"]["mae_dollar"],
            "chosen_family":  result["chosen_row"]["family"],
            "chosen_model":   result["chosen_row"]["model"],
            "chosen_dim_phi": result["chosen_row"]["dim_phi"],
            "chosen_tau":     result["chosen_row"]["tau"],
            "chosen_theta_l1":result["chosen_row"]["theta_l1"],
            "chosen_mae":     result["chosen_row"]["mae"],
            "chosen_mae_dollar": result["chosen_row"]["mae_dollar"],
            "gap_mae_abs":    result["gap_mae_abs"],
            "gap_mae_rel":    result["gap_mae_rel"],
        })
    picks_df = pd.DataFrame(picks)
    picks_df.to_csv(out_dir / "selected_linear.csv", index=False)
    nv.feature_summary().to_csv(out_dir / "feature_summary.csv", index=False)

    print("\n=== Selected linear policies (per scheme, policy) ===")
    print(picks_df.to_string(index=False))
    print(f"\nAll outputs -> {out_dir.resolve()}")


if __name__ == "__main__":
    sys.exit(main())
