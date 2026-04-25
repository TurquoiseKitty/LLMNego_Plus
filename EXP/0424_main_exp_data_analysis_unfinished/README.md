# Section 2.2 / Appendix B.1 — v7 notebook package

Updated Jupyter notebooks that match `NegotiatorFollowLinear__7_.pdf`
(Appendix B.1, paper v7).

## What changed vs v4

| Area | v4 (old) | v7 (this package) |
|---|---|---|
| Data filtering | only drop parse failures | truncate $S_t \in [v, M]$ → agreement when $S_t \le 1.01 B_t$ → drop all turns *after* first agreement |
| Round restriction | all turns after lag window | rounds `3 ≤ t ≤ 12` for model fitting |
| Feature specs | Families `A`/`B`/`BC`/`BCD` × τ∈{1,2,3} | Specs `I`–`X` plus `Base`, as in paper's enumeration |
| Training target | $\tilde S_t$ directly | `Y_t = logit(clip(S̃_t, η, 1-η))` with η=1e-4, σ(·) back to [0,1]. `Base` alone stays on $\tilde S_t$ |
| CV | 5-fold grouped | **10-fold** grouped + **vehicle-stratified** |
| Metrics | MAE, R², $MAE | **5 metrics**: MAE(norm), MAE(\$), RMSE, MAPE, Bias, plus R² + SE(MAE) |
| Model selection | hardcoded Family B τ=2 Ridge | two-stage: Stage 1 — 1-SE rule within linear; Stage 2 — prefer smaller `dim(ϕ)`, smaller `τ`, smaller standardized `‖θ‖₁` |

## File layout

```
negolin_section22_v7/
    negolin_utils.py                                  # v7 pipeline module
    Exp01_dataset_audit_and_boundedness.ipynb         # Tables 3 + 4 + trajectory plot
    Exp02_feature_family_and_model_comparison.ipynb   # Main selection pipeline
    Exp03_reader_visible_fit_diagnostics.ipynb        # pred-vs-actual + residuals + calibration
    Exp04_variable_importance_and_interpretation.ipynb
    Exp05_lag_sufficiency.ipynb
    Exp06_margin_normalization_ablation.ipynb
    Exp07_cross_product_stability.ipynb
    Exp08_time_homogeneity.ipynb
    Exp09_cross_policy_distinctiveness.ipynb
    Exp10_buyer_template_sensitivity.ipynb
    Exp11_rollout_fidelity.ipynb
    Exp12_transfer_to_llm_buyer.ipynb
    Exp13_backend_robustness.ipynb                    # needs GPT-4o dataset
    Exp14_controlled_state_sweep.ipynb                # emits spec; needs replay data
    Exp15_negative_controls.ipynb                     # needs new non-linear policies
    Exp16_noise_floor_estimation.ipynb                # emits spec; needs replay data
```

## Expected data paths

```
../data/0421_redo_previous_exp/results/     # randomized-buyer dataset (default)
../data/0423_strategic_buyer/results/       # LLM-buyer (natural + mirror), used by Exp12
```

Override at the top of any notebook if your data is elsewhere:

```python
from pathlib import Path
nu.RAND_BUYER_DIR = Path('/abs/path/to/0421_redo_previous_exp/results')
nu.LLM_BUYER_DIR  = Path('/abs/path/to/0423_strategic_buyer/results')
```

Use `Path(...)` — not a bare string — because some notebooks use the
`dir / filename` operator.

## Recommended run order

1. **Exp01** (audit) — produces Tables 3 and 4 and the trajectory panel.
2. **Exp02** (main) — produces `selected_linear_models.csv` with the
   Stage-2 winner per policy. Takes a few minutes.
3. **Exp03–Exp12** — downstream analyses. Every one of them reads
   `selected_linear_models.csv` and falls back to `(Feature II, Ridge)`
   if the file isn't present, so they all run standalone.
4. **Exp13–Exp16** — gated on new data (GPT-4o backend, anchor replays,
   grim-trigger/corridor prompts, state-replay noise floor). Each
   notebook prints a clear "skipping; data not available" message if
   the expected files aren't present, so it's safe to run them
   blind.

## How the v7 pipeline is wired

`negolin_utils.py` exposes the key entry points:

```python
raw = nu.load_all_fixed_policies(nu.RAND_BUYER_DIR)
_, turns = nu.preprocess_turns(raw)                    # truncation + agreement cutoff
meta, X, y, cols = nu.build_design_matrix(
    turns, policy='PVD', feature_name='II')            # restrict to rounds 3..12
pred_df, alphas = nu.grouped_cv_predict(
    meta, X, y, model_name='Ridge', n_splits=10)       # logit target → σ back to [0,1]
metrics = nu.cv_metrics_full(pred_df)                  # MAE(norm), MAE($), RMSE, MAPE, bias, R²

# Stage 1 + Stage 2
stage1   = nu.stage1_within_1se(model_grid)            # full grid across all (policy, feat, model)
selected = nu.stage2_select_linear(stage1, turns)      # one linear winner per policy
```

## Headline sanity-check results

After running Exp01 on `0421_redo_previous_exp/results/`:
- Raw turns: **14,400** (6 policies × 150 runs × 16 rounds)
- Dropped post-agreement: **8,148** (~57%)
- Clean analysis turns: **6,234** (~1,040 per policy)

After running Exp02's selection pipeline (reduced grid, smoke-tested):
- PVD → Feature II / Ridge — **MAE = 0.058, R² = 0.93, bias ≈ −0.02**
- IC  → Feature II / Ridge — **MAE = 0.072, R² = 0.87**

The full 6 × 10 × 5 grid + Base baseline runs in ~5–10 minutes; smaller
grids (drop MLP/GAM) cut this to ~1–2 minutes.

## Notes on the GPT-generated notebook

The uploaded `Exp02_gpt_version.ipynb` has been replaced by
`Exp02_feature_family_and_model_comparison.ipynb` in this package. Key
differences:

- All data-loading, preprocessing, feature construction, CV, and metrics
  live in `negolin_utils.py` rather than duplicated in the notebook.
- Stage-2 selection is done *within* the linear-model subset (so it
  always returns a well-defined winner, even when GBR dominates Stage 1
  — which is typical on this data).
- Notebook is ~13 cells instead of 35; the heavy lifting is one function
  call at a time.
- All downstream notebooks (Exp03–Exp12) read the resulting
  `selected_linear_models.csv`, so a single Exp02 run propagates to
  every downstream analysis.

## Legacy compatibility

The v4 helpers (`normalize_prices`, `clean_parse_failures`,
`build_turn_features`, `FEATURE_SPECS`) are still present in
`negolin_utils.py` so any old notebook that referenced them will still
load. The v7 pipeline is strictly additive.
