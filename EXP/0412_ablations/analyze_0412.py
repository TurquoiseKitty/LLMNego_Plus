"""
analyze_0412.py — Regression analysis for random-buyer negotiation experiments.

Provides:
  - OLS fitting with configurable feature sets (ablations M1–M4)
  - Leave-one-run-out cross-validation
  - Coefficient comparison across conditions
  - Diagnostic plots
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_PLT = True
except Exception:
    HAS_PLT = False


# ======================================================================
# Feature matrix builders
# ======================================================================

ABLATION_LABELS = {
    "M1": "m_t + s_{t-1}",
    "M2": "m_t + s_{t-1} + v",
    "M3": "m_t + s_{t-1} + t",
    "M4": "m_t + s_{t-1} + v + t",
}


def _feature_matrix(
    transitions: list[dict],
    ablation: str,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """
    Build design matrix X and target y for a given ablation.

    Returns (X, y, feature_names).
    """
    m = np.array([t["m_t"] for t in transitions], dtype=float)
    s = np.array([t["s_prev"] for t in transitions], dtype=float)
    y = np.array([t["s_t"] for t in transitions], dtype=float)
    v = np.array([t["v"] for t in transitions], dtype=float)
    t = np.array([t["round_t"] for t in transitions], dtype=float)

    ones = np.ones_like(m)

    if ablation == "M1":
        X = np.column_stack([ones, m, s])
        names = ["intercept", "m_t", "s_prev"]
    elif ablation == "M2":
        X = np.column_stack([ones, m, s, v])
        names = ["intercept", "m_t", "s_prev", "v"]
    elif ablation == "M3":
        X = np.column_stack([ones, m, s, t])
        names = ["intercept", "m_t", "s_prev", "t"]
    elif ablation == "M4":
        X = np.column_stack([ones, m, s, v, t])
        names = ["intercept", "m_t", "s_prev", "v", "t"]
    else:
        raise ValueError(f"Unknown ablation: {ablation}")

    return X, y, names


# ======================================================================
# OLS fit
# ======================================================================

def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def _r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return float(1 - ss_res / ss_tot) if ss_tot > 1e-12 else 1.0


def fit_ols(
    transitions: list[dict],
    ablation: str,
) -> dict:
    """Fit OLS on all transitions.  Returns coefficients, RMSE, R², etc."""
    X, y, names = _feature_matrix(transitions, ablation)
    n, p = X.shape

    beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ beta

    rmse = _rmse(y, y_hat)
    r2 = _r2(y, y_hat)

    # Standard errors (homoscedastic)
    resid = y - y_hat
    dof = max(n - p, 1)
    s2 = float(np.sum(resid ** 2)) / dof
    try:
        cov = s2 * np.linalg.inv(X.T @ X)
        se = np.sqrt(np.diag(cov))
    except np.linalg.LinAlgError:
        se = np.full(p, np.nan)

    coefs = {}
    for i, name in enumerate(names):
        coefs[name] = {
            "value": float(beta[i]),
            "se": float(se[i]),
        }

    return {
        "ablation": ablation,
        "features": ABLATION_LABELS.get(ablation, ablation),
        "n_samples": int(n),
        "n_params": int(p),
        "rmse": rmse,
        "r2": r2,
        "coefficients": coefs,
        "predictions": y_hat.tolist(),
        "true_values": y.tolist(),
    }


# ======================================================================
# Leave-one-run-out cross-validation
# ======================================================================

def loocv_by_run(
    transitions: list[dict],
    ablation: str,
) -> dict:
    """
    Leave-one-run-out CV.  Each fold holds out all transitions from one run.
    Returns per-fold and aggregate RMSE.
    """
    run_ids = sorted(set(t["run_idx"] for t in transitions))
    if len(run_ids) < 2:
        return {"ablation": ablation, "cv_rmse": None, "n_folds": 0,
                "note": "need >= 2 runs for LOOCV"}

    all_errors = []
    fold_results = []

    for held_out in run_ids:
        train = [t for t in transitions if t["run_idx"] != held_out]
        test = [t for t in transitions if t["run_idx"] == held_out]
        if not train or not test:
            continue

        X_tr, y_tr, names = _feature_matrix(train, ablation)
        X_te, y_te, _ = _feature_matrix(test, ablation)

        try:
            beta, _, _, _ = np.linalg.lstsq(X_tr, y_tr, rcond=None)
        except Exception:
            continue

        y_pred = X_te @ beta
        errors = (y_te - y_pred) ** 2
        all_errors.extend(errors.tolist())

        fold_results.append({
            "held_out_run": int(held_out),
            "n_test": int(len(y_te)),
            "fold_rmse": _rmse(y_te, y_pred),
        })

    cv_rmse = float(np.sqrt(np.mean(all_errors))) if all_errors else None

    return {
        "ablation": ablation,
        "cv_rmse": cv_rmse,
        "n_folds": len(fold_results),
        "folds": fold_results,
    }


# ======================================================================
# Run all ablations
# ======================================================================

def run_all_ablations(
    transitions: list[dict],
    label: str = "",
) -> dict:
    """Run M1–M4 ablations with OLS and LOOCV.  Returns summary dict."""
    results = {}
    for abl in ["M1", "M2", "M3", "M4"]:
        ols = fit_ols(transitions, abl)
        cv = loocv_by_run(transitions, abl)
        results[abl] = {
            "ols": ols,
            "loocv": cv,
        }
    return {"label": label, "n_transitions": len(transitions), "ablations": results}


# ======================================================================
# Per-condition analysis (e.g. per-strategy)
# ======================================================================

def analyze_per_condition(
    transitions: list[dict],
    condition_key: str,
    ablation: str = "M2",
) -> dict:
    """
    Fit the regression separately for each value of condition_key
    (e.g. "strategy" or "model") and report coefficients per group.
    """
    groups = {}
    for t in transitions:
        key = t[condition_key]
        groups.setdefault(key, []).append(t)

    per_group = {}
    for key, grp in sorted(groups.items()):
        if len(grp) < 5:
            per_group[key] = {"n": len(grp), "note": "too few samples"}
            continue
        ols = fit_ols(grp, ablation)
        cv = loocv_by_run(grp, ablation)
        per_group[key] = {
            "n": len(grp),
            "ols": ols,
            "loocv": cv,
        }

    # Also fit pooled
    pooled_ols = fit_ols(transitions, ablation)
    pooled_cv = loocv_by_run(transitions, ablation)

    return {
        "condition_key": condition_key,
        "ablation": ablation,
        "per_group": per_group,
        "pooled": {"ols": pooled_ols, "loocv": pooled_cv},
    }


# ======================================================================
# Plotting
# ======================================================================

def plot_ablation_comparison(
    results: dict,
    save_path: str | Path,
    title: str = "",
) -> None:
    """Bar chart comparing RMSE (in-sample and CV) across ablations."""
    if not HAS_PLT:
        return

    ablations = ["M1", "M2", "M3", "M4"]
    ols_rmse = [results["ablations"][a]["ols"]["rmse"] for a in ablations]
    cv_rmse = [
        results["ablations"][a]["loocv"]["cv_rmse"] or 0 for a in ablations
    ]

    x = np.arange(len(ablations))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(x - width / 2, ols_rmse, width, label="In-sample RMSE", alpha=0.85)
    ax.bar(x + width / 2, cv_rmse, width, label="LOOCV RMSE", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(
        [f"{a}\n{ABLATION_LABELS[a]}" for a in ablations], fontsize=9
    )
    ax.set_ylabel("RMSE")
    ax.set_title(title or "Ablation Comparison")
    ax.legend()
    fig.tight_layout()
    fig.savefig(save_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {save_path}")


def plot_true_vs_pred(
    results: dict,
    save_path: str | Path,
    title: str = "",
) -> None:
    """2×2 scatter plots of true vs predicted for each ablation."""
    if not HAS_PLT:
        return

    ablations = ["M1", "M2", "M3", "M4"]
    fig, axes = plt.subplots(2, 2, figsize=(10, 9))

    for i, abl in enumerate(ablations):
        ax = axes[i // 2, i % 2]
        ols = results["ablations"][abl]["ols"]
        y_true = np.array(ols["true_values"])
        y_pred = np.array(ols["predictions"])
        rmse = ols["rmse"]
        r2 = ols["r2"]

        ax.scatter(y_true, y_pred, alpha=0.6, s=20)
        lo = min(y_true.min(), y_pred.min()) * 0.95
        hi = max(y_true.max(), y_pred.max()) * 1.05
        ax.plot([lo, hi], [lo, hi], "k--", linewidth=1)
        ax.set_xlabel("True s_t")
        ax.set_ylabel("Predicted s_t")
        ax.set_title(f"{abl}: {ABLATION_LABELS[abl]}\nRMSE={rmse:.4f}  R²={r2:.4f}")
        ax.set_aspect("equal", adjustable="box")

    fig.suptitle(title, fontsize=13, y=1.01)
    fig.tight_layout()
    fig.savefig(save_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {save_path}")


def plot_coefficient_comparison(
    per_condition: dict,
    save_path: str | Path,
) -> None:
    """Plot coefficients ± SE for each condition group side by side."""
    if not HAS_PLT:
        return

    groups = per_condition["per_group"]
    valid_groups = {
        k: g for k, g in groups.items()
        if isinstance(g.get("ols"), dict)
    }
    if not valid_groups:
        return

    group_names = sorted(valid_groups.keys())
    coef_names = ["m_t", "s_prev", "v"]  # exclude intercept for clarity
    # filter to only coefficients that exist in the ablation
    sample_coefs = list(
        valid_groups[group_names[0]]["ols"]["coefficients"].keys()
    )
    coef_names = [c for c in coef_names if c in sample_coefs]

    n_groups = len(group_names)
    n_coefs = len(coef_names)

    fig, axes = plt.subplots(1, n_coefs, figsize=(4 * n_coefs, 5))
    if n_coefs == 1:
        axes = [axes]

    for ci, cname in enumerate(coef_names):
        ax = axes[ci]
        vals = []
        errs = []
        for gn in group_names:
            c = valid_groups[gn]["ols"]["coefficients"][cname]
            vals.append(c["value"])
            errs.append(c["se"])

        x = np.arange(n_groups)
        ax.bar(x, vals, yerr=errs, capsize=4, alpha=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(group_names, rotation=35, ha="right", fontsize=8)
        ax.set_title(f"Coefficient: {cname}")
        ax.axhline(0, color="gray", linewidth=0.5)

    cond = per_condition["condition_key"]
    fig.suptitle(f"Coefficients by {cond}", fontsize=12, y=1.02)
    fig.tight_layout()
    fig.savefig(save_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {save_path}")


# ======================================================================
# CSV export
# ======================================================================

def export_transitions_csv(
    transitions: list[dict],
    path: str | Path,
) -> None:
    """Export transitions to CSV for external analysis."""
    if not transitions:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "run_idx", "round_t", "m_t", "s_prev", "s_t",
        "v", "cost", "market", "strategy", "model", "supplier_id", "product",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for t in transitions:
            writer.writerow({k: t.get(k) for k in fields})
    print(f"CSV saved: {path}")


# ======================================================================
# Summary printer
# ======================================================================

def print_ablation_summary(results: dict) -> None:
    """Pretty-print the ablation comparison table."""
    print(f"\n{'='*70}")
    print(f"  {results.get('label', 'Analysis')}  (N={results['n_transitions']})")
    print(f"{'='*70}")
    header = f"  {'Model':<6} {'Features':<22} {'RMSE':>8} {'R²':>8} {'CV_RMSE':>9}"
    print(header)
    print(f"  {'-'*55}")

    for abl in ["M1", "M2", "M3", "M4"]:
        data = results["ablations"][abl]
        ols = data["ols"]
        cv = data["loocv"]
        cv_str = f"{cv['cv_rmse']:.4f}" if cv["cv_rmse"] else "N/A"
        print(
            f"  {abl:<6} {ols['features']:<22} "
            f"{ols['rmse']:>8.4f} {ols['r2']:>8.4f} {cv_str:>9}"
        )

    # Print coefficients for M2 (the key model)
    m2_coefs = results["ablations"]["M2"]["ols"]["coefficients"]
    print(f"\n  M2 coefficients:")
    for name, info in m2_coefs.items():
        print(f"    {name:<12} = {info['value']:>8.4f}  ±  {info['se']:.4f}")
    print()
