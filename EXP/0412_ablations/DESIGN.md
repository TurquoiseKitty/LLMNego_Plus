# EXP/0412 — Simplicity of Seller Price Dynamics

## Goal

Test whether an LLM seller's next proposed price is a simple function of observable inputs, by using a **programmatic random buyer** that eliminates buyer-side confounds.

Core regression model:

    s_t = f(m_t, s_{t−1}, v, [t])

where
- `s_t`   — seller's proposed price in round t
- `m_t`   — buyer's proposed price in round t (the message the seller is replying to)
- `s_{t−1}` — seller's proposed price in the previous round
- `v`     — seller's internal valuation = production_cost + internal_fulfillment_cost
- `t`     — round index (included in ablation only)

---

## Design

### Random buyer

The buyer is **programmatic** (no LLM).  Each round it draws a price uniformly from **[production_cost, market_price]** and sends a simple natural-language
message.  This:
1. Guarantees true randomness
2. Removes buyer-side LLM confounds
3. Ensures the seller faces diverse price signals, not a convergent sequence

The buyer uses 5 rotating message templates for variety.

### Improved price extraction

The supplier prompt now ends with:

    At the very end of your response, on a new line, state your price offer
    using EXACTLY this tag format:
    [PRICE] <product>: $X.XX per unit

The extractor first looks for `[PRICE]` tags.  If that fails, it falls back
to the general `$X.XX per unit` regex.  Both regex patterns are broadened to
handle comma separators and missing decimals.

### Rounds & runs

- **8 rounds** per run (enough data, short enough to avoid seller frustration)
- **5 runs** per condition (provides within-condition variance)
- Each run yields 7 usable transitions (rounds 2–8, since round 1 has no s_{t-1})

---

## Sweeps

### Sweep A — Valuation (v) sweep

**Varies**: product × supplier (16 conditions)
**Fixes**: strategy = cooperative, model = deepseek-reasoner

Products (4):
| Product | Category | Cost | Market |
|---|---|---|---|
| Sparkling water | Beverage | 0.18 | 1.20 |
| Cola | Beverage | 0.30 | 1.50 |
| Energy drink | Beverage | 0.65 | 2.50 |
| Protein bar | Snack | 1.10 | 3.00 |

Suppliers (4):
| Supplier | Bev | Snack | Conv |
|---|---|---|---|
| LOCAL | 0.04 | 0.05 | 0.40 |
| NATIONAL | 0.12 | 0.12 | 0.15 |
| HEALTH | 0.15 | 0.03 | 0.35 |
| COMPLIANCE | 0.22 | 0.25 | 0.60 |

This gives 16 distinct v values spanning 0.21 to 1.35.

**Purpose**: test whether v (the seller's valuation) is a necessary feature
in the regression.  If including v significantly improves the fit, the seller's
behavior depends on its private valuation.

Runs: 16 × 5 = 80 runs = 640 API calls.

### Sweep B — Strategy sweep

**Varies**: supplier strategy (6 strategies)
**Fixes**: product = Cola, supplier = LOCAL, model = deepseek-reasoner

Strategies:
- cooperative
- anchor_high
- gradual_conceder
- tit_for_tat_matcher
- fairness_responder
- walk_away_shutdown

**Purpose**: test whether a single linear model fits across strategies, or
whether each strategy needs its own model (evidence for latent tactic z_t).

Runs: 6 × 5 = 30 runs = 240 API calls.

### Sweep C — Model sweep

**Varies**: LLM backend (3 models)
**Fixes**: product = Cola, supplier = LOCAL, strategy = cooperative

Models:
- deepseek-reasoner
- gemini-2.5-flash  (via OpenAI-compatible API)
- gpt-4o

**Purpose**: test whether the linear structure is model-universal or
model-specific.

Runs: 3 × 5 = 15 runs = 120 API calls.

---

## Regression ablations

For each sweep, fit four models via OLS and compare with leave-one-run-out CV:

| Label | Features |
|---|---|
| M1 | intercept, m_t, s_{t−1} |
| M2 | intercept, m_t, s_{t−1}, v |
| M3 | intercept, m_t, s_{t−1}, t |
| M4 | intercept, m_t, s_{t−1}, v, t |

Metrics: RMSE (in-sample and LOOCV), R², coefficient estimates ± SE.

Cross-condition analyses:
- **Per-strategy fit**: fit M2 separately per strategy, report whether
  coefficients differ significantly.
- **Pooled + dummies**: fit M2 with strategy dummies to see if adding
  strategy improves the pooled model.
- **Per-model fit**: same idea for the model sweep.

---

## File layout

```
EXP/0412/
├── DESIGN.md                  ← this file
├── exp_runner_0412.py         ← random-buyer experiment runner
├── analyze_0412.py            ← regression + plotting utilities
├── run_sweep_A.py             ← valuation sweep
├── run_sweep_B.py             ← strategy sweep
├── run_sweep_C.py             ← model sweep
├── run_analysis.py            ← unified analysis across all sweeps
└── results/                   ← all outputs land here
    ├── sweep_A/
    ├── sweep_B/
    ├── sweep_C/
    └── summary/
```
