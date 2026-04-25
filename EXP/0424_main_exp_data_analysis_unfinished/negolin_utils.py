"""
negolin_utils.py  (v7 paper spec)
=================================

Shared pipeline for Appendix B.1 of "Prompt-Induced Linearity: Recovering
Negotiation Policies in LLMs".

What the v7 pipeline does, end-to-end:

    raw JSON logs
        -> load_policy_runs(...)                one row per (run, round)
        -> preprocess_turns(...)                truncate S to [v,M];
                                                detect agreement (S <= 1.01 B);
                                                drop post-agreement turns;
                                                normalize; build 1- and 2-step lags
        -> build_design_matrix(...)             restrict to rounds [3,12];
                                                materialize one of the 10 feature
                                                specs I..X (or 'Base')
        -> grouped_cv_predict(...)              10-fold CV, runs grouped, vehicles
                                                stratified; returns OOF predictions
                                                on the normalized [0,1] scale
        -> cv_metrics_full(...)                 MAE (norm), MAE ($), RMSE, MAPE, bias
        -> stage_selection(...)                 Stage 1: 1-SE rule
                                                Stage 2: linear pref, then smaller
                                                           dim(phi) / lag / ||theta||_1

All training for non-Base models happens on the logit-clipped target
    Y_t = logit(clip(S_tilde_t, eta, 1-eta)),   eta = 1e-4
and predictions are converted back with the sigmoid before metric computation.

Backwards-compatible helpers (normalize_prices, clean_parse_failures, FEATURE_SPECS,
build_turn_features, FAMILY_TAU grid) are preserved so Exp03-Exp16 notebooks
built under the v4 spec still run.  See the `# --- legacy --- ` sections.
"""

from __future__ import annotations

import os
import json
import math
from pathlib import Path
from collections import OrderedDict
from typing import Callable, Iterable, Optional, Sequence

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.base import BaseEstimator
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, SplineTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.metrics import r2_score

# =============================================================================
# Constants
# =============================================================================

RAND_BUYER_DIR = Path("../data/0421_redo_previous_exp/results")
LLM_BUYER_DIR  = Path("../data/0423_strategic_buyer/results")

POLICIES = ("PVD", "IC", "FRB", "RFK", "OADS", "MEVJ")

FIXED_POLICY_FILES = OrderedDict([
    ("PVD",  "exp00_fixed_patient_value_defender.json"),
    ("IC",   "exp01_fixed_busy_impatient_closer.json"),
    ("FRB",  "exp02_fixed_friendly_rapport_builder.json"),
    ("RFK",  "exp03_fixed_reciprocal_fairness_keeper.json"),
    ("OADS", "exp04_fixed_opponent_aware_diagnostic.json"),
    ("MEVJ", "exp05_fixed_market_expert_value_justifier.json"),
])

LLM_BUYER_NATURAL_FILES = OrderedDict(
    (pol, fn.replace(".json", "__vs__natural_buyer.json"))
    for pol, fn in FIXED_POLICY_FILES.items()
)
LLM_BUYER_MIRROR_FILES = OrderedDict([
    ("PVD",  "exp06_fixed_patient_value_defender__vs__mirror_patient_value_defender.json"),
    ("IC",   "exp07_fixed_busy_impatient_closer__vs__mirror_busy_impatient_closer.json"),
    ("FRB",  "exp08_fixed_friendly_rapport_builder__vs__mirror_friendly_rapport_builder.json"),
    ("RFK",  "exp09_fixed_reciprocal_fairness_keeper__vs__mirror_reciprocal_fairness_keeper.json"),
    ("OADS", "exp10_fixed_opponent_aware_diagnostic__vs__mirror_opponent_aware_diagnostic.json"),
    ("MEVJ", "exp11_fixed_market_expert_value_justifier__vs__mirror_market_expert_value_justifier.json"),
])

ETA                 = 1.0e-4
AGREEMENT_MULT      = 1.01
MODEL_ROUND_MIN     = 3
MODEL_ROUND_MAX     = 12
OUTER_FOLDS         = 10
INNER_FOLDS         = 5
RIDGE_ALPHAS        = np.logspace(-3, 1, 5)
RANDOM_SEED         = 2026

# =============================================================================
# Loading
# =============================================================================

def load_policy_runs(policy: str,
                     data_dir: os.PathLike = RAND_BUYER_DIR,
                     file_map: dict = FIXED_POLICY_FILES) -> pd.DataFrame:
    """Flatten one policy JSON file into a (run, round)-level table."""
    data_dir = Path(data_dir)
    fp = data_dir / file_map[policy]
    with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Runs can be either a flat list (v7 schema) or grouped by car (v4 schema).
    def _to_float(x):
        try:    return float(x)
        except: return np.nan
    def _to_int(x, default=-1):
        try:    return int(float(x))
        except: return default

    rows = []
    if "runs" in data and isinstance(data["runs"], list) and data["runs"] \
       and "car" in data["runs"][0]:
        # v7 flat schema
        for gid, run in enumerate(data["runs"]):
            car = run["car"]
            car_name = car["car_name"]
            M        = _to_float(car.get("market_price_new", car.get("market_price")))
            v        = _to_float(car.get("dealer_cost"))
            for rd in run.get("rounds", []):
                rows.append({
                    "policy":                  policy,
                    "car_name":                car_name,
                    "M":                       M,
                    "v":                       v,
                    "run_id":                  gid,
                    "run_idx":                 gid,
                    "round":                   _to_int(rd.get("round")),
                    "buyer_price_raw":         _to_float(rd.get("buyer_price")),
                    "seller_price_raw":        _to_float(rd.get("seller_price")),
                    "seller_answer":           rd.get("seller_answer", "") or "",
                    "seller_active_strategy":  rd.get("seller_active_strategy", "") or "",
                    "buyer_template_id":       _to_int(rd.get("buyer_template_id"), -1),
                    "buyer_message":           rd.get("buyer_message", "") or "",
                })
    else:
        # v4 grouped-by-car schema
        gid = 0
        for car_block in data.get("results", []):
            car_name = car_block["car_name"]
            M        = _to_float(car_block.get("market_price"))
            v        = _to_float(car_block.get("dealer_cost"))
            for run_idx, run in enumerate(car_block["runs"]):
                for rd in run["rounds"]:
                    rows.append({
                        "policy":                  policy,
                        "car_name":                car_name,
                        "M":                       M,
                        "v":                       v,
                        "run_id":                  gid,
                        "run_idx":                 run_idx,
                        "round":                   _to_int(rd.get("round")),
                        "buyer_price_raw":         _to_float(rd.get("buyer_price")),
                        "seller_price_raw":        _to_float(rd.get("seller_price")),
                        "seller_answer":           rd.get("seller_answer", "") or "",
                        "seller_active_strategy":  rd.get("seller_active_strategy", "") or "",
                        "buyer_template_id":       _to_int(rd.get("buyer_template_id"), -1),
                        "buyer_message":           rd.get("buyer_message", "") or "",
                    })
                gid += 1
    return pd.DataFrame(rows)


def load_all_fixed_policies(data_dir: os.PathLike = RAND_BUYER_DIR) -> pd.DataFrame:
    dfs = [load_policy_runs(p, data_dir=data_dir) for p in POLICIES]
    return pd.concat(dfs, ignore_index=True)


def load_llm_buyer_runs(policy: str,
                        kind: str = "natural",
                        data_dir: os.PathLike = LLM_BUYER_DIR) -> pd.DataFrame:
    fmap = LLM_BUYER_NATURAL_FILES if kind == "natural" else LLM_BUYER_MIRROR_FILES
    return load_policy_runs(policy, data_dir=data_dir, file_map=fmap)


def assign_vehicle_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Add a 'vehicle' column with 'Vehicle 1'..'Vehicle 5' keyed by v/M ratio."""
    car_info = (df.groupby("car_name")
                  .agg(v=("v", "first"), M=("M", "first"))
                  .assign(ratio=lambda x: x["v"] / x["M"])
                  .sort_values("ratio"))
    car_info["vehicle"] = [f"Vehicle {i+1}" for i in range(len(car_info))]
    label = car_info["vehicle"].to_dict()
    out = df.copy()
    out["vehicle"] = out["car_name"].map(label)
    return out

# =============================================================================
# v7 Preprocessing  --  the canonical pipeline
# =============================================================================

def preprocess_turns(raw: pd.DataFrame,
                     agreement_mult: float = AGREEMENT_MULT,
                     keep_agreement_turn: bool = True
                     ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Preprocess raw turns per paper v7 Appendix B.1.

    Returns
    -------
    all_marked : DataFrame
        Every raw turn, with diagnostic flags (parse_fail, lower_truncated,
        upper_truncated, agreement_flag, first_agreement_round,
        after_agreement).  Useful for Table 3 (turn counts) and Table 4
        (truncation rates).
    turns : DataFrame
        Analysis-ready table.  Post-agreement rows are dropped; seller price
        is truncated to [v, M]; normalized prices and one-/two-step lags are
        included.  Parse-failure rows are retained so lag construction stays
        aligned with the round index, but their 'parse_fail' flag is True.
    """
    out = raw.copy()
    out = assign_vehicle_labels(out)

    out["B"]                = pd.to_numeric(out["buyer_price_raw"],  errors="coerce")
    out["S_raw"]            = pd.to_numeric(out["seller_price_raw"], errors="coerce")
    out["parse_fail"]       = out["S_raw"].isna()
    out["lower_truncated"]  = out["S_raw"] < out["v"]
    out["upper_truncated"]  = out["S_raw"] > out["M"]
    out["S"]                = out["S_raw"].clip(lower=out["v"], upper=out["M"])

    out["agreement_flag"] = (~out["parse_fail"]) & (out["S"] <= agreement_mult * out["B"])
    first_ag = (out.loc[out["agreement_flag"]]
                     .groupby("run_id", observed=True)["round"]
                     .min()
                     .rename("first_agreement_round"))
    out = out.merge(first_ag, on="run_id", how="left")

    if keep_agreement_turn:
        out["after_agreement"] = (out["first_agreement_round"].notna()
                                  & (out["round"] > out["first_agreement_round"]))
    else:
        out["after_agreement"] = (out["first_agreement_round"].notna()
                                  & (out["round"] >= out["first_agreement_round"]))

    turns = out.loc[~out["after_agreement"]].copy()
    turns["margin"] = turns["M"] - turns["v"]
    turns["B_norm"] = (turns["B"] - turns["v"]) / turns["margin"]
    turns["S_norm"] = (turns["S"] - turns["v"]) / turns["margin"]

    turns = turns.sort_values(["policy", "vehicle", "run_id", "round"]).reset_index(drop=True)
    g = turns.groupby("run_id", sort=False, observed=True)
    for k in (1, 2):
        turns[f"B_lag{k}"]      = g["B_norm"].shift(k)
        turns[f"S_lag{k}"]      = g["S_norm"].shift(k)
        turns[f"round_lag{k}"]  = g["round"].shift(k)

    turns["dB"]      = turns["B_norm"] - turns["B_lag1"]
    turns["dS_lag1"] = turns["S_lag1"] - turns["S_lag2"]
    turns["A"]       = turns["S_lag1"] - turns["B_norm"]
    turns["A_lag1"]  = turns["S_lag2"] - turns["B_lag1"]

    for col in ("B_norm", "B_lag1", "dB", "dS_lag1"):
        turns[f"{col}_pos"] = np.maximum(turns[col],  0.0)
        turns[f"{col}_neg"] = np.maximum(-turns[col], 0.0)

    return out, turns

# =============================================================================
# v7 Feature specifications  (I..X, plus Base)
# =============================================================================

FEATURE_SPECS_V7 = OrderedDict([
    ("I",    {"desc": r"(1, B_t)",
              "cols": ["B_norm"],
              "lag":  0}),
    ("II",   {"desc": r"(1, B_t, S_{t-1}, B_{t-1})",
              "cols": ["B_norm", "S_lag1", "B_lag1"],
              "lag":  1}),
    ("III",  {"desc": r"(1, B_t, S_{t-1}, B_{t-1}, S_{t-2}, B_{t-2})",
              "cols": ["B_norm", "S_lag1", "B_lag1", "S_lag2", "B_lag2"],
              "lag":  2}),
    ("IV",   {"desc": r"(1, A_t, S_{t-1})",
              "cols": ["A", "S_lag1"],
              "lag":  1}),
    ("V",    {"desc": r"(1, A_t, S_{t-1}, A_{t-1}, S_{t-2})",
              "cols": ["A", "S_lag1", "A_lag1", "S_lag2"],
              "lag":  2}),
    ("VI",   {"desc": r"(1, B_t^+, B_t^-)",
              "cols": ["B_norm_pos", "B_norm_neg"],
              "lag":  0}),
    ("VII",  {"desc": r"(1, B_t^+, B_t^-, S_{t-1}, B_{t-1}^+, B_{t-1}^-)",
              "cols": ["B_norm_pos", "B_norm_neg", "S_lag1", "B_lag1_pos", "B_lag1_neg"],
              "lag":  1}),
    ("VIII", {"desc": r"(1, B_t, S_{t-1}, dB_t)",
              "cols": ["B_norm", "S_lag1", "dB"],
              "lag":  1}),
    ("IX",   {"desc": r"(1, B_t^+, B_t^-, S_{t-1}, dB_t^+, dB_t^-)",
              "cols": ["B_norm_pos", "B_norm_neg", "S_lag1", "dB_pos", "dB_neg"],
              "lag":  1}),
    ("X",    {"desc": r"(1, B_t^+, B_t^-, S_{t-1}, dB_t^+, dB_t^-, dS_{t-1}^+, dS_{t-1}^-)",
              "cols": ["B_norm_pos", "B_norm_neg", "S_lag1", "dB_pos", "dB_neg",
                       "dS_lag1_pos", "dS_lag1_neg"],
              "lag":  2}),
])

BASELINE_SPEC = {"desc": r"Base: theta_0 + theta_1 * S_{t-1} (normalized scale)",
                 "cols": ["S_lag1"],
                 "lag":  1}

def feature_spec(name: str) -> dict:
    return BASELINE_SPEC if name == "Base" else FEATURE_SPECS_V7[name]


def feature_summary_table() -> pd.DataFrame:
    rows = []
    for name, spec in FEATURE_SPECS_V7.items():
        rows.append({"feature":    name,
                     "description": spec["desc"],
                     "lag_order":  spec["lag"],
                     "dim_phi":    len(spec["cols"]) + 1})
    return pd.DataFrame(rows)


def build_design_matrix(turns: pd.DataFrame,
                        policy: str,
                        feature_name: str,
                        round_min: int = MODEL_ROUND_MIN,
                        round_max: int = MODEL_ROUND_MAX
                        ) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, list[str]]:
    """Build meta/X/y/cols for one (policy, feature spec) pair."""
    spec = feature_spec(feature_name)
    cols = list(spec["cols"])
    lag  = int(spec["lag"])

    sub = turns.loc[(turns["policy"].astype(str) == policy)
                  & turns["round"].between(round_min, round_max)
                  & (~turns["parse_fail"])].copy()

    required = cols + ["S_norm", "margin", "run_id", "vehicle", "round"]
    if lag >= 1: required.append("round_lag1")
    if lag >= 2: required.append("round_lag2")

    mask = sub[required].notna().all(axis=1)
    if lag >= 1: mask &= sub["round_lag1"].eq(sub["round"] - 1)
    if lag >= 2: mask &= sub["round_lag2"].eq(sub["round"] - 2)
    sub = sub.loc[mask].copy()

    X = sub[cols].to_numpy(dtype=float)
    y = sub["S_norm"].to_numpy(dtype=float)
    return sub, X, y, cols

# =============================================================================
# Models
# =============================================================================

def sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.asarray(z, dtype=float)
    return 1.0 / (1.0 + np.exp(-np.clip(z, -40, 40)))


def logit_clip(p: np.ndarray, eta: float = ETA) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), eta, 1.0 - eta)
    return np.log(p / (1.0 - p))


def _stratified_grouped_folds(groups: np.ndarray,
                              strata: np.ndarray | None = None,
                              n_splits: int = OUTER_FOLDS,
                              seed: int = RANDOM_SEED
                              ) -> list[tuple[np.ndarray, np.ndarray]]:
    """Group-aware k-fold split with optional stratification.

    Whole groups (typically run_ids) go to exactly one fold.  Within each
    stratum (typically vehicle), groups are shuffled and round-robined across
    folds so each fold is balanced on the stratum.
    """
    groups = np.asarray(groups)
    if strata is None:
        strata = np.full(len(groups), "all")
    strata = np.asarray(strata)

    gdf = (pd.DataFrame({"g": groups, "s": strata})
             .drop_duplicates("g"))
    n_groups = gdf["g"].nunique()
    n_splits = min(n_splits, n_groups)
    if n_splits < 2:
        raise ValueError("Need at least 2 groups for CV.")

    rng = np.random.default_rng(seed)
    bins: list[list] = [[] for _ in range(n_splits)]
    for _, blk in gdf.groupby("s", sort=False):
        gs = blk["g"].to_numpy().copy()
        rng.shuffle(gs)
        for i, g in enumerate(gs):
            bins[i % n_splits].append(g)

    idx = np.arange(len(groups))
    folds = []
    for k in range(n_splits):
        test_set = set(bins[k])
        test = np.array([g in test_set for g in groups])
        folds.append((idx[~test], idx[test]))
    return folds


def _fit_one(model_name: str,
             X_tr: np.ndarray,
             y_tr_norm: np.ndarray,
             *,
             groups_tr: np.ndarray | None = None,
             strata_tr: np.ndarray | None = None,
             fixed_alpha: Optional[float] = None,
             seed: int = RANDOM_SEED):
    """Fit one estimator.  Non-Base models train on the logit target."""
    if model_name == "Base":
        m = LinearRegression()
        m.fit(X_tr, y_tr_norm)
        return m, {"scale": "normalized", "alpha": np.nan}

    y_tr_logit = logit_clip(y_tr_norm)

    if model_name == "OLS":
        m = Pipeline([("scale", StandardScaler()), ("m", LinearRegression())])
        m.fit(X_tr, y_tr_logit)
        return m, {"scale": "logit", "alpha": np.nan}

    if model_name in ("Ridge", "GAM"):
        alpha = fixed_alpha if fixed_alpha is not None else _inner_alpha(
            model_name, X_tr, y_tr_norm, groups_tr, strata_tr, seed=seed)
        if model_name == "Ridge":
            m = Pipeline([("scale", StandardScaler()), ("m", Ridge(alpha=alpha))])
        else:
            m = Pipeline([("scale", StandardScaler()),
                          ("spline", SplineTransformer(n_knots=6, degree=3,
                                                        include_bias=False)),
                          ("m", Ridge(alpha=alpha))])
        m.fit(X_tr, y_tr_logit)
        return m, {"scale": "logit", "alpha": float(alpha)}

    if model_name == "GBR":
        m = GradientBoostingRegressor(n_estimators=300, max_depth=3,
                                       learning_rate=0.05, subsample=0.85,
                                       random_state=seed)
        m.fit(X_tr, y_tr_logit)
        return m, {"scale": "logit", "alpha": np.nan}

    if model_name == "MLP":
        m = Pipeline([("scale", StandardScaler()),
                      ("m", MLPRegressor(hidden_layer_sizes=(64,), activation="relu",
                                          early_stopping=True, validation_fraction=0.15,
                                          max_iter=600, learning_rate_init=1e-3,
                                          random_state=seed))])
        m.fit(X_tr, y_tr_logit)
        return m, {"scale": "logit", "alpha": np.nan}

    raise ValueError(f"Unknown model: {model_name}")


def _predict_one(model, X: np.ndarray, info: dict) -> np.ndarray:
    raw = model.predict(X)
    if info.get("scale") == "normalized":
        return np.clip(raw, 0.0, 1.0)
    return sigmoid(raw)


def _inner_alpha(model_name: str,
                 X: np.ndarray, y_norm: np.ndarray,
                 groups: np.ndarray, strata: np.ndarray | None,
                 seed: int = RANDOM_SEED) -> float:
    """Grouped inner CV to pick Ridge/GAM penalty, scored on normalized MAE."""
    if strata is None:
        strata = np.full(len(groups), "all")
    folds = _stratified_grouped_folds(groups, strata, INNER_FOLDS, seed=seed)
    y_logit = logit_clip(y_norm)

    best = (np.inf, float(RIDGE_ALPHAS[0]))
    for alpha in RIDGE_ALPHAS:
        fold_mae = []
        for tr, va in folds:
            if model_name == "Ridge":
                est = Pipeline([("scale", StandardScaler()),
                                ("m", Ridge(alpha=float(alpha)))])
            else:
                est = Pipeline([("scale", StandardScaler()),
                                ("spline", SplineTransformer(n_knots=6, degree=3,
                                                             include_bias=False)),
                                ("m", Ridge(alpha=float(alpha)))])
            est.fit(X[tr], y_logit[tr])
            pred = sigmoid(est.predict(X[va]))
            fold_mae.append(np.mean(np.abs(pred - y_norm[va])))
        score = float(np.mean(fold_mae))
        if score < best[0]:
            best = (score, float(alpha))
    return best[1]


def grouped_cv_predict(meta: pd.DataFrame,
                       X: np.ndarray,
                       y_norm: np.ndarray,
                       model_name: str,
                       *,
                       n_splits: int = OUTER_FOLDS,
                       fixed_alpha: Optional[float] = None,
                       seed: int = RANDOM_SEED
                       ) -> tuple[pd.DataFrame, list[float]]:
    """10-fold grouped+stratified OOF prediction on normalized [0,1] scale."""
    groups = meta["run_id"].to_numpy()
    strata = meta["vehicle"].astype(str).to_numpy()
    folds  = _stratified_grouped_folds(groups, strata, n_splits, seed=seed)

    pred = np.full(len(y_norm), np.nan)
    fold = np.full(len(y_norm), -1, dtype=int)
    alphas = []
    for k, (tr, te) in enumerate(folds):
        mdl, info = _fit_one(model_name, X[tr], y_norm[tr],
                             groups_tr=groups[tr], strata_tr=strata[tr],
                             fixed_alpha=fixed_alpha, seed=seed + 101*k)
        pred[te] = _predict_one(mdl, X[te], info)
        fold[te] = k
        alphas.append(info.get("alpha", np.nan))

    keep_cols = [c for c in ("policy", "vehicle", "car_name", "run_id", "round",
                             "M", "v", "margin", "B", "S", "B_norm", "S_norm",
                             "S_lag1", "B_lag1", "A") if c in meta.columns]
    out = meta[keep_cols].copy()
    out["y_true"] = y_norm
    out["y_pred"] = pred
    out["fold"]   = fold
    return out, alphas

# =============================================================================
# Metrics
# =============================================================================

def cv_metrics_full(pred_df: pd.DataFrame) -> dict:
    """The 5 paper metrics + R^2 + SE(MAE)."""
    y = pred_df["y_true"].to_numpy(float)
    p = pred_df["y_pred"].to_numpy(float)
    m = pred_df["margin"].to_numpy(float)
    err = p - y

    per_fold = (pred_df.groupby("fold", observed=True)
                .apply(lambda d: float(np.mean(np.abs(d["y_pred"] - d["y_true"]))),
                       include_groups=False))
    mae_norm = float(np.mean(np.abs(err)))
    se = float(per_fold.std(ddof=1) / math.sqrt(len(per_fold))) if len(per_fold) > 1 else np.nan

    return {
        "n":            int(len(pred_df)),
        "n_groups":     int(pred_df["run_id"].nunique()),
        "mae_norm":     mae_norm,
        "mae_norm_se":  se,
        "mae_dollar":   float(np.mean(np.abs(err) * m)),
        "rmse_norm":    float(np.sqrt(np.mean(err**2))),
        "mape":         float(np.mean(np.abs(err) / (np.abs(y) + ETA))),
        "bias":         float(np.mean(err)),
        "r2":           float(r2_score(y, p)),
    }

# =============================================================================
# Two-stage model selection
# =============================================================================

def stage1_within_1se(grid: pd.DataFrame,
                      key_cols: Sequence[str] = ("policy",),
                      score_col: str = "mae_norm",
                      se_col: str = "mae_norm_se"
                      ) -> pd.DataFrame:
    grid = grid.dropna(subset=[score_col]).copy()
    best = (grid.sort_values(score_col)
                 .groupby(list(key_cols), observed=True)
                 .head(1)[list(key_cols) + [score_col, se_col]]
                 .rename(columns={score_col: "best_mae", se_col: "best_se"}))
    merged = grid.merge(best, on=list(key_cols), how="left")
    keep = merged[score_col] <= merged["best_mae"] + merged["best_se"].fillna(0.0)
    merged["within_1se"] = keep
    return merged


def refit_coef_l1(turns: pd.DataFrame, policy: str, feature_name: str,
                  model_name: str, alpha: Optional[float]) -> float:
    """Fit a final linear (OLS/Ridge) on all data and return ||theta_{-1}||_1
    on the standardized feature scale.  Used for Stage-2 sparsity tiebreak."""
    meta, X, y, cols = build_design_matrix(turns, policy, feature_name)
    if len(X) < 20:
        return float("nan")
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)
    y_logit = logit_clip(y)
    if model_name == "OLS":
        m = LinearRegression().fit(Xs, y_logit)
    elif model_name == "Ridge":
        a = alpha if (alpha is not None and np.isfinite(alpha)) else 1.0
        m = Ridge(alpha=float(a)).fit(Xs, y_logit)
    else:
        return float("nan")
    return float(np.sum(np.abs(m.coef_)))


def stage2_select_linear(stage1: pd.DataFrame,
                         turns: pd.DataFrame,
                         linear_models: Sequence[str] = ("OLS", "Ridge")
                         ) -> pd.DataFrame:
    """Among linear (OLS / Ridge) candidates per policy, apply the 1-SE rule
    within the linear subset and then the parsimony tiebreak (smaller dim
    phi, then smaller lag, then smaller standardized ||theta||_1).

    Rationale: the paper's "Stage 2" is a selection over linear models; the
    non-parametric baselines serve as an accuracy ceiling that appears in
    Stage 1 output but is not eligible for Stage-2 interpretation.  If the
    1-SE rule is applied *only* over linear candidates, the pipeline always
    returns a well-defined linear winner per policy.
    """
    candidates = stage1[stage1["model"].isin(linear_models)].copy()
    if candidates.empty:
        return candidates

    # Recompute 1-SE within the linear subset per policy
    best = (candidates.sort_values("mae_norm")
                      .groupby("policy", observed=True).head(1)
                      [["policy", "mae_norm", "mae_norm_se"]]
                      .rename(columns={"mae_norm": "lin_best_mae",
                                       "mae_norm_se": "lin_best_se"}))
    candidates = candidates.merge(best, on="policy", how="left")
    candidates["within_1se_linear"] = (
        candidates["mae_norm"]
        <= candidates["lin_best_mae"] + candidates["lin_best_se"].fillna(0.0)
    )
    survivors = candidates[candidates["within_1se_linear"]].copy()

    survivors["dim_phi"] = survivors["feature"].apply(
        lambda f: len(feature_spec(f)["cols"]) + 1)
    survivors["lag"]     = survivors["feature"].apply(lambda f: feature_spec(f)["lag"])

    l1 = []
    for row in survivors.itertuples(index=False):
        alpha = getattr(row, "alpha", np.nan)
        l1.append(refit_coef_l1(turns, row.policy, row.feature, row.model, alpha))
    survivors["theta_l1"] = l1

    survivors = survivors.sort_values(
        ["policy", "dim_phi", "lag", "theta_l1", "mae_norm"])
    return (survivors.groupby("policy", observed=True).head(1)
             .reset_index(drop=True))

# =============================================================================
# Plotting helpers
# =============================================================================

def setup_matplotlib():
    plt.rcParams.update({
        "figure.dpi":         110,
        "savefig.dpi":        140,
        "axes.spines.top":    False,
        "axes.spines.right":  False,
        "axes.grid":          True,
        "grid.alpha":         0.3,
        "font.size":          10,
    })


def pred_vs_actual_plot(y_true, y_pred, title: str = "", ax=None):
    if ax is None:
        _, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(y_true, y_pred, alpha=0.25, s=10)
    ax.plot([0, 1], [0, 1], "k--", lw=1)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel(r"observed $\tilde S_t$")
    ax.set_ylabel(r"predicted $\tilde S_t$")
    ax.set_title(title)
    return ax


def residual_hist(y_true, y_pred, title: str = "", ax=None, bins: int = 40):
    if ax is None:
        _, ax = plt.subplots(figsize=(5, 3))
    r = np.asarray(y_pred) - np.asarray(y_true)
    ax.hist(r, bins=bins, alpha=0.8, edgecolor="white")
    ax.axvline(0, color="k", lw=1)
    ax.set_xlabel("residual"); ax.set_ylabel("count"); ax.set_title(title)
    return ax

# =============================================================================
# --- legacy v4 helpers (kept so pre-v7 Exp01/03-16 notebooks still run) -----
# =============================================================================

def normalize_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Legacy helper: add s_norm/b_norm columns (no truncation, no lag)."""
    out = df.copy()
    denom = out["M"] - out["v"]
    out["s_norm"] = (out["seller_price_raw"] - out["v"]) / denom
    out["b_norm"] = (out["buyer_price_raw"]  - out["v"]) / denom
    return out


def clean_parse_failures(df: pd.DataFrame, verbose: bool = False) -> pd.DataFrame:
    """Legacy helper: drop NaN seller_price_raw rows (no truncation)."""
    before = len(df)
    out = df.dropna(subset=["seller_price_raw"]).copy()
    if verbose:
        print(f"dropped {before - len(out):,} / {before:,} parse failures")
    return out


FEATURE_SPECS = OrderedDict([
    ("A_tau1",  ("A", 1)), ("A_tau2",  ("A", 2)), ("A_tau3",  ("A", 3)),
    ("B_tau1",  ("B", 1)), ("B_tau2",  ("B", 2)), ("B_tau3",  ("B", 3)),
    ("BC_tau2", ("BC", 2)), ("BC_tau3", ("BC", 3)),
    ("BCD_tau2",("BCD", 2)), ("BCD_tau3",("BCD", 3)),
])

def _pos(x): return np.maximum(x, 0.0)
def _neg(x): return np.maximum(-x, 0.0)

def build_turn_features(df: pd.DataFrame, tau: int = 2, family: str = "B"
                        ) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Legacy feature builder used by Exp03-Exp16 generator scripts."""
    if "s_norm" not in df.columns:
        df = normalize_prices(df)
    df = df.sort_values(["run_id", "round"]).reset_index(drop=True)

    g = df.groupby("run_id", sort=False)
    cols = {"s_norm": df["s_norm"], "b_norm": df["b_norm"]}
    for k in range(1, tau + 1):
        cols[f"s_lag{k}"] = g["s_norm"].shift(k)
        cols[f"b_lag{k}"] = g["b_norm"].shift(k)

    feat = {"intercept": np.ones(len(df))}
    if family == "A":
        feat["b_t_pos"] = _pos(cols["b_norm"])
        for k in range(1, tau + 1):
            feat[f"s_lag{k}_pos"] = _pos(cols[f"s_lag{k}"])
            feat[f"b_lag{k}_pos"] = _pos(cols[f"b_lag{k}"])
    elif family in ("B", "BC", "BCD"):
        feat["b_t"] = cols["b_norm"]
        for k in range(1, tau + 1):
            feat[f"s_lag{k}"] = cols[f"s_lag{k}"]
            feat[f"b_lag{k}"] = cols[f"b_lag{k}"]
        if family in ("BC", "BCD"):
            for k in range(1, tau):
                feat[f"ds_lag{k}"] = cols[f"s_lag{k}"] - cols[f"s_lag{k+1}"]
                feat[f"db_lag{k}"] = cols[f"b_lag{k}"] - cols[f"b_lag{k+1}"]
        if family == "BCD":
            for k in range(1, tau + 1):
                feat[f"gap_lag{k}"] = cols[f"s_lag{k}"] - cols[f"b_lag{k}"]
    else:
        raise ValueError(f"Unknown family {family}")

    feat_df = pd.DataFrame(feat)
    keep = feat_df.notna().all(axis=1) & df["s_norm"].notna()
    feat_df = feat_df.loc[keep]
    y       = df.loc[keep, "s_norm"].to_numpy()
    groups  = df.loc[keep, "run_id"].to_numpy()
    names   = list(feat_df.columns)
    return feat_df.to_numpy(), y, groups, names


def ridge_factory(alpha: float = 1.0):
    return lambda: Ridge(alpha=alpha, fit_intercept=False)

def ols_factory():
    return lambda: LinearRegression(fit_intercept=False)

def mean_factory():
    class _M:
        def fit(self, X, y): self.mu_ = float(np.mean(y)); return self
        def predict(self, X): return np.full(len(X), self.mu_)
    return _M

def persistence_factory(s_lag1_col: int):
    class _P:
        def fit(self, X, y): return self
        def predict(self, X): return np.asarray(X)[:, s_lag1_col]
    return _P
