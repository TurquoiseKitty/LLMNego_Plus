"""
negolin_v15.py
==============

Pipeline for Appendix B.1 of v15 of "Prompt-Induced Linearity: Recovering
Negotiation Policies in LLMs".

Data layout
-----------
We expect 120 JSON files under `data_dir`, one per (buyer_scheme, policy,
vehicle) triple. Filenames are of the form

    {scheme_prefix}_{policy_slug}_v{vehicle_idx}.json

with scheme_prefix in {user_A, user_B, coop_C, coop_D} (mapping to buyer
schemes A, B, C, D) and vehicle_idx in {1,...,5}.

Pipeline (v15 Appendix B.1)
---------------------------
    load_run_files(...)          -> one row per (scheme, policy, vehicle, run, round)
    preprocess_turns(...)        -> truncate S to [v,M]; detect agreement
                                    (S <= 1.005 B) and floor (S <= v); drop
                                    anything strictly AFTER the first such
                                    turn; compute normalized prices and lags
    build_design_matrix(...)     -> restrict to t in [3, 12]; materialize one
                                    of feature families I..VII or 'Base'; return
                                    (meta, X, y=Y_t, cols)
    partition_persist(...)       -> split D into D_persist (|Y_t| <= 1e-2)
                                    and D_negotiation (|Y_t|  >  1e-2)
    grouped_cv_predict(...)      -> grouped 10-fold CV (folds at run_id),
                                    returns OOF predictions on the Y_t scale
    cv_metrics(...)              -> MAE, MAE$, MAPE, MAPE$  (the four paper metrics)
    stage_selection(...)         -> Stage 1: top-k by MAE; Stage 2: prefer
                                    linear, smallest dim(phi) / tau / ||theta||_1
"""

from __future__ import annotations

import os
import json
import math
from pathlib import Path
from collections import OrderedDict
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from sklearn.base import clone
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingRegressor


# =============================================================================
# Constants
# =============================================================================

POLICIES = ("PVD", "IC", "FRB", "RFK", "OADS", "MEVJ")
POLICY_SLUGS = OrderedDict([
    ("PVD",  "patient_value_defender"),
    ("IC",   "busy_impatient_closer"),
    ("FRB",  "friendly_rapport_builder"),
    ("RFK",  "reciprocal_fairness_keeper"),
    ("OADS", "opponent_aware_diagnostic"),
    ("MEVJ", "market_expert_value_justifier"),
])
POLICY_FROM_SLUG = {v: k for k, v in POLICY_SLUGS.items()}

SCHEMES = ("A", "B", "C", "D")
SCHEME_PREFIX = OrderedDict([
    ("A", "user_A"),
    ("B", "user_B"),
    ("C", "coop_C"),
    ("D", "coop_D"),
])

# v15 constants
ETA             = 1.0e-4
AGREEMENT_MULT  = 1.005
PERSIST_THRESH  = 1.0e-2        # |Y_t| <= this -> D_persist
MODEL_ROUND_MIN = 3             # t in [3, 12]  because Y_{t-1} may appear
MODEL_ROUND_MAX = 12
OUTER_FOLDS     = 10
INNER_FOLDS     = 5
RIDGE_ALPHAS    = np.logspace(-3, 1, 5)  # {1e-3, 1e-2, 1e-1, 1, 10}
RANDOM_SEED     = 2026
EPS_MAPE        = 1.0e-3        # stability for MAPE denominator


# =============================================================================
# Loading
# =============================================================================

def _to_float(x):
    try:    return float(x)
    except: return np.nan

def _to_int(x, default=-1):
    try:    return int(float(x))
    except: return default


def load_run_files(data_dir: os.PathLike,
                   schemes: Sequence[str] = SCHEMES,
                   policies: Sequence[str] = POLICIES,
                   vehicle_ids: Sequence[int] = (1, 2, 3, 4, 5)) -> pd.DataFrame:
    """Flatten all matching JSON files into one (scheme, policy, vehicle, run, round) table.

    Each run inside a file is assigned a globally unique `run_id` so that the
    same run_idx in different files does not collide.
    """
    data_dir = Path(data_dir)
    rows = []
    gid = 0

    for scheme in schemes:
        prefix = SCHEME_PREFIX[scheme]
        for pol in policies:
            slug = POLICY_SLUGS[pol]
            for vid in vehicle_ids:
                fp = data_dir / f"{prefix}_{slug}_v{vid}.json"
                if not fp.exists():
                    raise FileNotFoundError(fp)
                with open(fp, "r", encoding="utf-8") as f:
                    d = json.load(f)

                for run_local, run in enumerate(d["runs"]):
                    car = run["car"]
                    car_name = car["car_name"]
                    M = _to_float(car.get("market_price_new"))
                    v = _to_float(car.get("dealer_cost"))
                    for rd in run.get("rounds", []):
                        rows.append({
                            "scheme":          scheme,
                            "policy":          pol,
                            "vehicle_id":      vid,        # 1..5
                            "car_name":        car_name,
                            "M":               M,
                            "v":               v,
                            "run_id":          gid,        # unique across files
                            "run_local":       run_local,  # 0..49 within file
                            "round":           _to_int(rd.get("round")),
                            "buyer_price_raw": _to_float(rd.get("buyer_price")),
                            "seller_price_raw":_to_float(rd.get("seller_price")),
                            "buyer_template_id": _to_int(rd.get("buyer_template_id"), -1),
                        })
                    gid += 1

    return pd.DataFrame(rows)


# =============================================================================
# Preprocessing
# =============================================================================

def preprocess_turns(raw: pd.DataFrame,
                     agreement_mult: float = AGREEMENT_MULT,
                     eta: float = ETA) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply v15 Appendix B.1 preprocessing.

    Steps:
      1. Truncate S to [v, M].
      2. Detect agreement turns: S <= agreement_mult * B.
      3. Detect floor turns: S <= v  (i.e. seller hit the reservation floor).
      4. Drop every row strictly AFTER the first agreement-or-floor turn
         (the first such turn itself is kept -- but it will be excluded from
         modelling because there is no further observed action).
      5. Compute normalized prices, logit-clipped S tilde, Y_t, and lag features.

    Returns
    -------
    all_marked : DataFrame
        Every raw turn with diagnostic flags.
    turns      : DataFrame
        Post-processing analysis table with lag features and Y_t.
    """
    out = raw.copy()
    out["B"]      = pd.to_numeric(out["buyer_price_raw"],  errors="coerce")
    out["S_raw"]  = pd.to_numeric(out["seller_price_raw"], errors="coerce")
    out["parse_fail"]      = out["S_raw"].isna()
    out["lower_truncated"] = out["S_raw"] < out["v"]
    out["upper_truncated"] = out["S_raw"] > out["M"]
    out["S"]               = out["S_raw"].clip(lower=out["v"], upper=out["M"])

    out["agreement_flag"] = (~out["parse_fail"]) & (out["S"] <= agreement_mult * out["B"])
    out["floor_flag"]     = (~out["parse_fail"]) & (out["S"] <= out["v"])
    # "terminal" = either agreement or floor
    out["terminal_flag"]  = out["agreement_flag"] | out["floor_flag"]

    # first terminal round per run
    first_term = (out.loc[out["terminal_flag"]]
                     .groupby("run_id", observed=True)["round"].min()
                     .rename("first_terminal_round"))
    out = out.merge(first_term, on="run_id", how="left")

    # Drop rows STRICTLY AFTER the first terminal turn (paper: "discard all
    # observations following the turn at which..."). Keep the terminal turn
    # itself since its S_t still carries information.
    out["after_terminal"] = (out["first_terminal_round"].notna()
                             & (out["round"] > out["first_terminal_round"]))
    turns = out.loc[~out["after_terminal"]].copy()

    # Normalized prices
    turns["margin"]  = turns["M"] - turns["v"]
    turns["B_tilde"] = (turns["B"] - turns["v"]) / turns["margin"]
    turns["S_tilde"] = (turns["S"] - turns["v"]) / turns["margin"]

    # Logit-clipped S tilde
    def _logit_clip(p):
        p = np.clip(p, eta, 1.0 - eta)
        return np.log(p / (1.0 - p))
    turns["S_tilde_L"] = _logit_clip(turns["S_tilde"].to_numpy())

    # Sort within run, then compute one- and two-step lags of B_tilde, S_tilde_L
    # plus the lag of round (for gap check).
    turns = turns.sort_values(["scheme", "policy", "vehicle_id", "run_id", "round"]).reset_index(drop=True)
    g = turns.groupby("run_id", sort=False, observed=True)

    for k in (1, 2):
        turns[f"B_tilde_lag{k}"]   = g["B_tilde"].shift(k)
        turns[f"S_tilde_lag{k}"]   = g["S_tilde"].shift(k)
        turns[f"S_tilde_L_lag{k}"] = g["S_tilde_L"].shift(k)
        turns[f"round_lag{k}"]     = g["round"].shift(k)

    # Y_t = S_tilde_L_t - S_tilde_L_{t-1}  (defined for t >= 2)
    turns["Y"] = turns["S_tilde_L"] - turns["S_tilde_L_lag1"]
    # Y_{t-1} (defined for t >= 3)
    turns["Y_lag1"] = g["Y"].shift(1)

    # Concession delta and its positive / negative parts
    turns["dB"]     = turns["B_tilde"] - turns["B_tilde_lag1"]
    turns["dB_pos"] = np.maximum(turns["dB"],  0.0)
    turns["dB_neg"] = np.maximum(-turns["dB"], 0.0)

    # Positive / negative components of B_tilde and B_tilde_lag1
    # (B_tilde itself is non-negative by design but we keep the machinery so
    # the feature family matches the paper's definition in case values wander
    # slightly negative after truncation; in that case one half will zero out)
    for col in ("B_tilde", "B_tilde_lag1"):
        turns[f"{col}_pos"] = np.maximum(turns[col],  0.0)
        turns[f"{col}_neg"] = np.maximum(-turns[col], 0.0)

    return out, turns


# =============================================================================
# Feature specifications (v15: I..VII, plus Base)
# =============================================================================
# For each family we store:
#   cols : list of non-constant feature columns in `turns` DataFrame
#   tau  : lag order
#   dim  : dimension of phi including the intercept "1"
#
# Paper definitions (normalized variables; S_tilde_L = logit-clipped S_tilde):
#   I.   (1, B_t, S_{t-1}, B_{t-1})
#   II.  (1, B_t, S^L_{t-1}, B_{t-1})
#   III. (1, B_t, S^L_{t-1}, B_{t-1}, S^L_{t-2}, B_{t-2})
#   IV.  (1, B_t^+, B_t^-, S^L_{t-1}, B_{t-1}^+, B_{t-1}^-)
#   V.   (1, dB_t, S^L_{t-1})
#   VI.  (1, dB_t, S^L_{t-1}, Y_{t-1})
#   VII. (1, B_t^+, B_t^-, dB_t^+, dB_t^-, S^L_{t-1}, Y_{t-1})
FEATURE_SPECS = OrderedDict([
    ("I",   {"cols": ["B_tilde", "S_tilde_lag1", "B_tilde_lag1"],
             "tau": 1, "dim": 4,
             "desc": "(1, B_t, S_{t-1}, B_{t-1})"}),
    ("II",  {"cols": ["B_tilde", "S_tilde_L_lag1", "B_tilde_lag1"],
             "tau": 1, "dim": 4,
             "desc": "(1, B_t, S^L_{t-1}, B_{t-1})"}),
    ("III", {"cols": ["B_tilde", "S_tilde_L_lag1", "B_tilde_lag1",
                      "S_tilde_L_lag2", "B_tilde_lag2"],
             "tau": 2, "dim": 6,
             "desc": "(1, B_t, S^L_{t-1}, B_{t-1}, S^L_{t-2}, B_{t-2})"}),
    ("IV",  {"cols": ["B_tilde_pos", "B_tilde_neg", "S_tilde_L_lag1",
                      "B_tilde_lag1_pos", "B_tilde_lag1_neg"],
             "tau": 1, "dim": 6,
             "desc": "(1, B_t^+, B_t^-, S^L_{t-1}, B_{t-1}^+, B_{t-1}^-)"}),
    ("V",   {"cols": ["dB", "S_tilde_L_lag1"],
             "tau": 1, "dim": 3,
             "desc": "(1, dB_t, S^L_{t-1})"}),
    ("VI",  {"cols": ["dB", "S_tilde_L_lag1", "Y_lag1"],
             "tau": 2, "dim": 4,
             "desc": "(1, dB_t, S^L_{t-1}, Y_{t-1})"}),
    ("VII", {"cols": ["B_tilde_pos", "B_tilde_neg", "dB_pos", "dB_neg",
                      "S_tilde_L_lag1", "Y_lag1"],
             "tau": 2, "dim": 7,
             "desc": "(1, B_t^+, B_t^-, dB_t^+, dB_t^-, S^L_{t-1}, Y_{t-1})"}),
])

# Base model is special: predicts S_tilde_t = theta_0 + theta_1 S_tilde_{t-1}.
# It uses S_tilde (not S_tilde_L) as its feature on the *normalized price* scale.
BASE_SPEC = {"cols": ["S_tilde_lag1"], "tau": 1, "dim": 2,
             "desc": "Base: S_tilde_t ~ theta_0 + theta_1 * S_tilde_{t-1}"}


def feature_summary() -> pd.DataFrame:
    rows = []
    for k, s in FEATURE_SPECS.items():
        rows.append({"family": k, "description": s["desc"],
                     "tau": s["tau"], "dim_phi": s["dim"]})
    return pd.DataFrame(rows)


# =============================================================================
# Design matrix
# =============================================================================

def build_design_matrix(turns: pd.DataFrame,
                        feature_name: str,
                        round_min: int = MODEL_ROUND_MIN,
                        round_max: int = MODEL_ROUND_MAX
                        ) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, list[str]]:
    """Build (meta, X, y, cols) for one feature family.

    For non-Base families:
      - y = Y_t  (logit-increment target)
      - X = the columns in FEATURE_SPECS[feature_name]["cols"]

    For Base:
      - y = Y_t  (we keep the same target for uniform evaluation)
      - X = [S_tilde_lag1] -- the Base model will be fit on S_tilde (not Y)
        downstream, so we carry S_tilde too for the fit. See _fit_base.

    Rows kept: t in [round_min, round_max], contiguous lag gap (round_lag1 ==
    round-1 when tau>=1; round_lag2 == round-2 when tau>=2), not parse_fail,
    and all required columns non-null.
    """
    spec = BASE_SPEC if feature_name == "Base" else FEATURE_SPECS[feature_name]
    cols = list(spec["cols"])
    tau  = int(spec["tau"])

    sub = turns.loc[turns["round"].between(round_min, round_max)
                    & (~turns["parse_fail"])].copy()

    # Required columns for validity: features, target Y, margin, grouping keys.
    required = cols + ["Y", "S_tilde", "S_tilde_lag1", "margin",
                       "run_id", "vehicle_id", "round", "scheme", "policy"]
    if tau >= 1: required.append("round_lag1")
    if tau >= 2: required.append("round_lag2")

    mask = sub[required].notna().all(axis=1)
    # Contiguity check on lags: gaps shouldn't happen if we never drop internal
    # rows, but this is a guard against any unexpected gap
    if tau >= 1: mask &= sub["round_lag1"].eq(sub["round"] - 1)
    if tau >= 2: mask &= sub["round_lag2"].eq(sub["round"] - 2)
    sub = sub.loc[mask].copy()

    X = sub[cols].to_numpy(dtype=float)
    y = sub["Y"].to_numpy(dtype=float)
    return sub, X, y, cols


def partition_persist(meta: pd.DataFrame,
                      X: np.ndarray,
                      y: np.ndarray,
                      thresh: float = PERSIST_THRESH
                      ) -> tuple[tuple[pd.DataFrame, np.ndarray, np.ndarray],
                                 tuple[pd.DataFrame, np.ndarray, np.ndarray]]:
    """Split (meta, X, y) into persist (|y| <= thresh) and negotiation (|y| > thresh)."""
    absY = np.abs(y)
    mask_persist = absY <= thresh
    mask_neg = ~mask_persist
    persist = (meta.loc[mask_persist].reset_index(drop=True),
               X[mask_persist], y[mask_persist])
    negotiation = (meta.loc[mask_neg].reset_index(drop=True),
                   X[mask_neg], y[mask_neg])
    return persist, negotiation


# =============================================================================
# Model fitting / prediction
# =============================================================================

def _fit_model(model_name: str,
               X_tr: np.ndarray,
               y_tr: np.ndarray,
               *,
               S_tilde_tr: Optional[np.ndarray] = None,
               fixed_alpha: Optional[float] = None,
               groups_tr: Optional[np.ndarray] = None,
               seed: int = RANDOM_SEED):
    """Fit one estimator on the negotiation-stage training split.

    - Base fits S_tilde_t ~ OLS on S_tilde_{t-1}  (uses S_tilde_tr as target).
    - OLS fits y=Y on scaled X.
    - Ridge-lambda fits y=Y on scaled X, lambda chosen by inner grouped CV unless fixed.
    - GBR fits y=Y on X (no scaling).
    """
    if model_name == "Base":
        # X_tr has one column = S_tilde_lag1; target = S_tilde_t
        m = LinearRegression()
        m.fit(X_tr, S_tilde_tr)
        return m, {"kind": "base"}

    if model_name == "OLS":
        m = Pipeline([("scale", StandardScaler()),
                      ("m", LinearRegression())])
        m.fit(X_tr, y_tr)
        return m, {"kind": "linear", "alpha": np.nan}

    if model_name.startswith("Ridge"):
        if fixed_alpha is not None:
            alpha = float(fixed_alpha)
        else:
            alpha = _inner_alpha_ridge(X_tr, y_tr, groups_tr, seed=seed)
        m = Pipeline([("scale", StandardScaler()),
                      ("m", Ridge(alpha=alpha))])
        m.fit(X_tr, y_tr)
        return m, {"kind": "linear", "alpha": alpha}

    if model_name == "GBR":
        m = GradientBoostingRegressor(n_estimators=300, max_depth=3,
                                      learning_rate=0.05, subsample=0.85,
                                      random_state=seed)
        m.fit(X_tr, y_tr)
        return m, {"kind": "gbr"}

    raise ValueError(f"Unknown model: {model_name}")


def _predict_model(model, info: dict, X_te: np.ndarray,
                   S_tilde_lag1_te: Optional[np.ndarray] = None
                   ) -> np.ndarray:
    """Return predicted Y_t.

    For Base we first predict S_tilde_t, then convert to a Y_t prediction via
    Y_hat = logit(clip(S_tilde_hat)) - logit(clip(S_tilde_{t-1})).
    """
    if info.get("kind") == "base":
        S_hat = np.clip(model.predict(X_te), ETA, 1.0 - ETA)
        S_lag = np.clip(S_tilde_lag1_te, ETA, 1.0 - ETA)
        return np.log(S_hat / (1 - S_hat)) - np.log(S_lag / (1 - S_lag))
    return model.predict(X_te)


def _inner_alpha_ridge(X: np.ndarray, y: np.ndarray,
                       groups: Optional[np.ndarray],
                       seed: int = RANDOM_SEED) -> float:
    """Inner grouped CV to pick Ridge alpha on MAE."""
    if groups is None:
        groups = np.arange(len(y))
    folds = _grouped_folds(groups, n_splits=INNER_FOLDS, seed=seed)
    best = (np.inf, float(RIDGE_ALPHAS[0]))
    for alpha in RIDGE_ALPHAS:
        fold_mae = []
        for tr, va in folds:
            est = Pipeline([("scale", StandardScaler()),
                            ("m", Ridge(alpha=float(alpha)))])
            est.fit(X[tr], y[tr])
            pred = est.predict(X[va])
            fold_mae.append(np.mean(np.abs(pred - y[va])))
        score = float(np.mean(fold_mae))
        if score < best[0]:
            best = (score, float(alpha))
    return best[1]


# =============================================================================
# Grouped CV
# =============================================================================

def _grouped_folds(groups: np.ndarray,
                   n_splits: int = OUTER_FOLDS,
                   seed: int = RANDOM_SEED) -> list[tuple[np.ndarray, np.ndarray]]:
    """Group-aware k-fold: whole groups (typically run_ids) go to one fold.

    Vehicles are NOT used as strata here because build_design_matrix may be
    called on all-vehicles-pooled data for a given policy+scheme. We randomise
    group assignment; each fold has ~n_groups/n_splits groups.
    """
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    n_groups = len(uniq)
    n_splits = min(n_splits, n_groups)
    if n_splits < 2:
        raise ValueError("Need at least 2 groups for CV.")

    rng = np.random.default_rng(seed)
    perm = rng.permutation(uniq)
    bins = np.array_split(perm, n_splits)
    idx = np.arange(len(groups))
    folds = []
    for k in range(n_splits):
        test_set = set(bins[k].tolist())
        test = np.array([g in test_set for g in groups])
        folds.append((idx[~test], idx[test]))
    return folds


def grouped_cv_predict(meta: pd.DataFrame,
                       X: np.ndarray,
                       y: np.ndarray,
                       model_name: str,
                       *,
                       n_splits: int = OUTER_FOLDS,
                       fixed_alpha: Optional[float] = None,
                       seed: int = RANDOM_SEED
                       ) -> tuple[pd.DataFrame, list[float]]:
    """Grouped 10-fold OOF prediction of Y_t. Returns (pred_df, alphas).

    pred_df columns: all selected meta cols plus y_true (=Y_t), y_pred (=hat Y_t),
    fold, plus the price-scale columns S_tilde and S_tilde_lag1 (needed for
    dollar-scale metrics).
    """
    groups = meta["run_id"].to_numpy()
    folds  = _grouped_folds(groups, n_splits, seed=seed)

    S_lag_all = meta["S_tilde_lag1"].to_numpy(float)
    S_all     = meta["S_tilde"].to_numpy(float)

    y_pred = np.full(len(y), np.nan)
    fold_idx = np.full(len(y), -1, dtype=int)
    alphas = []

    for k, (tr, te) in enumerate(folds):
        mdl, info = _fit_model(model_name, X[tr], y[tr],
                               S_tilde_tr=S_all[tr] if model_name == "Base" else None,
                               fixed_alpha=fixed_alpha,
                               groups_tr=groups[tr],
                               seed=seed + 101*k)
        y_pred[te] = _predict_model(mdl, info, X[te],
                                    S_tilde_lag1_te=S_lag_all[te] if model_name == "Base" else None)
        fold_idx[te] = k
        alphas.append(info.get("alpha", np.nan))

    keep_cols = [c for c in ("scheme", "policy", "vehicle_id", "car_name", "run_id",
                             "round", "M", "v", "margin",
                             "B", "S", "B_tilde", "S_tilde", "S_tilde_lag1",
                             "S_tilde_L", "S_tilde_L_lag1")
                 if c in meta.columns]
    out = meta[keep_cols].copy()
    out["y_true"] = y
    out["y_pred"] = y_pred
    out["fold"]   = fold_idx
    return out, alphas


# =============================================================================
# Metrics
# =============================================================================

def _predicted_S_tilde_from_Y(y_pred: np.ndarray, S_tilde_lag1: np.ndarray,
                              eta: float = ETA) -> np.ndarray:
    """Invert the logit-increment to get S_tilde_hat = sigmoid(Y_hat + logit(S_tilde_{t-1}))."""
    S_lag = np.clip(S_tilde_lag1, eta, 1.0 - eta)
    logit_lag = np.log(S_lag / (1 - S_lag))
    z = y_pred + logit_lag
    z = np.clip(z, -40, 40)
    return 1.0 / (1.0 + np.exp(-z))


def cv_metrics(pred_df: pd.DataFrame, eps: float = EPS_MAPE) -> dict:
    """Compute the 4 paper metrics + per-fold MAE for SE/CI, plus bias."""
    y   = pred_df["y_true"].to_numpy(float)
    p   = pred_df["y_pred"].to_numpy(float)
    m   = pred_df["margin"].to_numpy(float)
    S   = pred_df["S_tilde"].to_numpy(float)
    S1  = pred_df["S_tilde_lag1"].to_numpy(float)
    err = p - y

    S_hat = _predicted_S_tilde_from_Y(p, S1)
    S_err = S_hat - S

    per_fold = (pred_df.groupby("fold", observed=True)
                .apply(lambda d: float(np.mean(np.abs(d["y_pred"] - d["y_true"]))),
                       include_groups=False))
    mae    = float(np.mean(np.abs(err)))
    se_mae = float(per_fold.std(ddof=1) / math.sqrt(len(per_fold))) if len(per_fold) > 1 else np.nan

    return {
        "n":         int(len(pred_df)),
        "n_groups":  int(pred_df["run_id"].nunique()),
        "mae":       mae,
        "mae_se":    se_mae,
        "mae_dollar":float(np.mean(np.abs(S_err) * m)),
        "mape":      float(np.mean(np.abs(err) / (np.abs(y) + eps))),
        "mape_dollar": float(np.mean(np.abs(S_err) / (np.abs(S) + eps))),
        "bias":      float(np.mean(err)),
        "rmse":      float(np.sqrt(np.mean(err ** 2))),
    }


# =============================================================================
# Two-stage model selection
# =============================================================================

def fit_theta_ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Fit OLS (no scaling) to get raw coefficient vector including intercept."""
    X_ = np.column_stack([np.ones(len(X)), X])
    theta, *_ = np.linalg.lstsq(X_, y, rcond=None)
    return theta  # theta[0] = intercept, theta[1:] = feature coeffs


# =============================================================================
# Convenience helpers used by downstream experiment notebooks
# =============================================================================

def fit_linear_for_oof(meta: pd.DataFrame, X: np.ndarray, y: np.ndarray,
                       model_name: str = "Ridge",
                       fixed_alpha: Optional[float] = None,
                       seed: int = RANDOM_SEED) -> tuple[pd.DataFrame, list[float]]:
    """Convenience: grouped 10-fold OOF predictions for a linear model on Y_t."""
    return grouped_cv_predict(meta, X, y, model_name=model_name,
                              fixed_alpha=fixed_alpha, seed=seed)


def fit_full_linear(X: np.ndarray, y: np.ndarray, model_name: str = "Ridge",
                    alpha: float = 1.0):
    """Fit a linear model on the full (X, y) and return the fitted Pipeline.

    For inspecting standardized coefficients on the whole data set.
    """
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LinearRegression, Ridge
    from sklearn.pipeline import Pipeline
    if model_name == "OLS":
        return Pipeline([("s", StandardScaler()), ("m", LinearRegression())]).fit(X, y)
    return Pipeline([("s", StandardScaler()), ("m", Ridge(alpha=alpha))]).fit(X, y)


def predicted_S_tilde_from_Y(y_pred: np.ndarray, S_tilde_lag1: np.ndarray,
                             eta: float = ETA) -> np.ndarray:
    """Public wrapper around the sigmoid inversion (used in rollouts/diagnostics)."""
    return _predicted_S_tilde_from_Y(y_pred, S_tilde_lag1, eta=eta)


def add_mode_indicators(meta: pd.DataFrame, X: np.ndarray, cols: list[str],
                        thresh_floor: float = 0.10,
                        thresh_gap:   float = 0.50,
                        thresh_retreat: float = -0.10,
                        floor_interaction: bool = True
                        ) -> tuple[np.ndarray, list[str]]:
    """Append three mode indicators (and optionally one interaction) to a design
    matrix.

      I_at_floor = 1[S_tilde_lag1 < thresh_floor]
      I_big_gap  = 1[S_tilde_lag1 - B_tilde > thresh_gap]
      I_retreat  = 1[dB < thresh_retreat]
      I_floor_x_S_tilde_lag1 = I_at_floor * S_tilde_lag1   (optional)

    Useful for Exp02b -- closing the linear-vs-GBR gap by capturing the
    discrete floor / retreat modes that smooth linear features cannot fit.
    """
    extras, extra_cols = [], []
    I_floor = (meta["S_tilde_lag1"].to_numpy() < thresh_floor).astype(float)
    extras.append(I_floor.reshape(-1, 1));            extra_cols.append("I_at_floor")
    I_gap = ((meta["S_tilde_lag1"].to_numpy() - meta["B_tilde"].to_numpy()) > thresh_gap).astype(float)
    extras.append(I_gap.reshape(-1, 1));              extra_cols.append("I_big_gap")
    I_ret = (meta["dB"].to_numpy() < thresh_retreat).astype(float)
    extras.append(I_ret.reshape(-1, 1));              extra_cols.append("I_retreat")
    if floor_interaction and "S_tilde_lag1" in cols:
        j = cols.index("S_tilde_lag1")
        extras.append((I_floor * X[:, j]).reshape(-1, 1))
        extra_cols.append("I_floor_x_S_tilde_lag1")
    X_aug = np.hstack([X] + extras)
    return X_aug, cols + extra_cols


def setup_matplotlib():
    """Sane defaults for paper figures."""
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.dpi": 110,
        "savefig.dpi": 140,
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "legend.fontsize": 9,
    })


def stage_selection(leaderboard: pd.DataFrame,
                    k_top: int = 3,
                    tol_se: float = 1.0) -> dict:
    """Given a leaderboard with columns
         family, model, mae, mae_se, dim_phi, tau, theta_l1
       do the two-stage selection:
         Stage 1: keep rows with mae <= (best_mae + tol_se * best_mae_se)
                  or, failing that, top-k by mae.
         Stage 2: among linear models (OLS / Ridge*) in the kept set, pick
                  the one minimising (dim_phi, tau, theta_l1) lexicographically.
       Report the performance gap vs. the overall best.
    """
    lb = leaderboard.copy().sort_values("mae").reset_index(drop=True)
    best = lb.iloc[0]
    best_mae = float(best["mae"])
    best_se  = float(best["mae_se"]) if not np.isnan(best["mae_se"]) else 0.0

    # Stage 1: keep within one SE of best, but at least top k_top
    cutoff = best_mae + tol_se * best_se
    kept = lb.loc[lb["mae"] <= cutoff]
    if len(kept) < k_top:
        kept = lb.head(k_top)

    # Stage 2: linear only
    linear = kept.loc[kept["model"].isin(["OLS"]) | kept["model"].str.startswith("Ridge")].copy()
    if len(linear) == 0:
        # Fall back to best overall
        chosen = best
    else:
        linear = linear.sort_values(["dim_phi", "tau", "theta_l1", "mae"],
                                    ascending=[True, True, True, True])
        chosen = linear.iloc[0]

    gap_mae = float(chosen["mae"]) - best_mae
    gap_mae_rel = gap_mae / max(best_mae, 1e-12)

    return {
        "best_row":    dict(best),
        "kept_subset": kept.reset_index(drop=True),
        "chosen_row":  dict(chosen),
        "gap_mae_abs": gap_mae,
        "gap_mae_rel": gap_mae_rel,
    }
