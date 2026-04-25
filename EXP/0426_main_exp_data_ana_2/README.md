# negolin_v15 — full notebook bundle for v15 of *Prompt-Induced Linearity*

## Layout

```
negolin_v15.py        # core pipeline (loaders, preprocess, features I-VII, CV, selection)
run_analysis.py       # helper used by Exp02 (build_leaderboard_for_group)

Exp01_dataset_audit.ipynb                       # counts, truncation, agreement, Y-distribution
Exp02_feature_family_and_model_comparison.ipynb # main sweep + Stage1+Stage2 selection
Exp02b_enhanced_linear_vs_gbr.ipynb             # mode indicators close the linear-vs-GBR gap
Exp03_reader_visible_fit_diagnostics.ipynb      # pred-vs-actual, residuals, calibration
Exp04_variable_importance.ipynb                 # std coefs + drop-column + permutation
Exp05_lag_sufficiency.ipynb                     # tau=1 vs tau=2 across pairs
Exp06_margin_normalization_ablation.ipynb       # raw $ vs M-norm vs (M-v)-norm
Exp07_cross_product_stability.ipynb             # per-vehicle fits + transfer matrix
Exp08_time_homogeneity.ipynb                    # early/middle/late coefficient drift
Exp09_cross_policy_distinctiveness.ipynb        # 6x6 policy transfer matrix per scheme
Exp10_buyer_scheme_distinctiveness.ipynb        # 4x4 scheme transfer per policy (v15-specific)
Exp11_rollout_fidelity.ipynb                    # closed-loop simulation against the 4 schemes
```

Not included (require additional data the user did not upload):
- `Exp12_transfer_to_llm_buyer.ipynb`     -- needs strategic-buyer dataset
- `Exp13_backend_robustness.ipynb`        -- needs GPT-4o regenerated runs
- `Exp14_controlled_state_sweep.ipynb`    -- needs anchor-replay data
- `Exp15_negative_controls.ipynb`         -- needs grim-trigger / corridor prompts
- `Exp16_noise_floor_estimation.ipynb`    -- needs replay data

These can be added when the corresponding datasets are generated.

## Run order

1. **Exp01** — preprocessing diagnostics. Verifies parse-failure rate, agreement/floor rates, D_persist vs D_negotiation sizes.
2. **Exp02** — main sweep (~12-15 min on 2 cores). Produces `out/leaderboard_full.csv` and `out/selected_linear.csv`. Every downstream notebook reads `selected_linear.csv` (with a sensible fallback if it's missing).
3. **Exp02b - Exp11** — order is independent. Each one is self-contained: it loads the data, runs preprocess, reads selected_linear.csv, and produces a CSV + figure.

Set `DATA_DIR` at the top of each notebook to your unzipped `merged_results/` folder.

## Key v15 conventions encoded in `negolin_v15.py`

- **Agreement**: `S_t <= 1.005 * B_t`
- **Floor**: `S_t <= v` ends the cycle's modellable region too
- **Drop rows strictly after** the first terminal turn (the terminal turn itself is kept)
- **eta = 1e-4** for logit clipping
- **D_persist** = `|Y_t| <= 1e-2` (paper says it'll be used "in future" -- placeholder)
- **D_negotiation** = `|Y_t| > 1e-2` -- everything trains and validates here
- **Round range**: `t in [3, 12]`  (because Y_{t-1} is now a candidate feature)
- **Component-wise StandardScaler** is fit on training folds only -- no leakage
- **Models**: Base, OLS, Ridge-lambda, GBR  (MLP omitted for runtime)
- **Two-stage selection**: Stage 1 keeps within ~1 SE of best; Stage 2 picks linear with smallest (dim phi, tau, ||theta||_1)

## Mapping to paper sections

| Paper section          | Notebook(s)                                                                   |
|------------------------|-------------------------------------------------------------------------------|
| §2.1 Setup             | Exp06 (margin-normalization ablation)                                         |
| §2.2 Empirical results | Exp01, Exp02, Exp02b, Exp03, Exp04, Exp08, Exp09, Exp10                       |
| §3.2 Fixed Policy      | Exp02, Exp03, Exp04, Exp05, Exp07                                             |
| §3.3 Adaptive Policy   | Exp08 (the residual time-drift is the adaptive component)                     |
| §3.4 Empirical Eval    | Exp03, Exp11 (one-step + closed-loop)                                         |
| §4 Counter-strategy    | Exp11 sets up the rollout machinery; §4 builds optimization on top of it      |
