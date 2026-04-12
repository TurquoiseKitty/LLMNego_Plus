# EXP/0413 — Fractional Model Validation

## Goal

Final validation of the fractional markup model:

    s_t = v + (market - v) * [β₀ + β₁·frac(m_t) + β₂·frac(s_{t-1})]

where frac(x) = (x - v) / (market - v).

## Changes from 0412

1. **Template randomization**: buyer message template is randomly selected
   each round (not cycling with `round % 5`), fixing the template-round
   confound discovered in 0412.

2. **Five buyer types** to stress-test the model under diverse input regimes.

3. **Multiple seller strategies** to measure strategy-dependent coefficients.

4. **12 rounds** per run (up from 8-10) for more transitions per run.

## Design

### Fixed parameters

- Model: `deepseek-reasoner`
- Rounds per run: 12
- Runs per condition: 5
- Transitions per condition: 5 × 11 = 55

### Products × Suppliers (6 v-values)

| Product | Cost | Market | S1 v | S2 v |
|---------|------|--------|------|------|
| Sparkling water | 0.18 | 1.20 | 0.22 | 0.30 |
| Cola | 0.30 | 1.50 | 0.34 | 0.42 |
| Protein bar | 1.10 | 3.00 | 1.15 | 1.22 |

### Buyer types (9)

| Type | Description | Price range |
|------|-------------|-------------|
| `random` | Uniform(cost, market) | Within negotiation zone |
| `wild` | Uniform(0, 2×market) | Includes below-v and above-market |
| `persistent_frac0.2` | Fixed at 20% of market | Very low, often below v |
| `persistent_frac0.4` | Fixed at 40% of market | Low |
| `persistent_frac0.6` | Fixed at 60% of market | Mid-range |
| `persistent_frac0.8` | Fixed at 80% of market | Reasonable |
| `persistent_frac1.2` | Fixed at 120% of market | Above market (generous) |
| `concession` | Starts at 10%, linearly → 60% of zone | Classic concession |
| `anchor_drag` | Starts at 5%, +3% per round of zone | Low anchor, tiny steps |

### Seller strategies (6)

All 6 strategies are tested with all buyer types:
cooperative, anchor_high, gradual_conceder,
tit_for_tat_matcher, fairness_responder, walk_away_shutdown

### Scale

- Per seller strategy: 9 buyers × 3 products × 2 suppliers = 54 conditions
- Per strategy: 54 × 5 runs × 12 rounds = 3,240 API calls
- Total (6 strategies): 324 conditions, 19,440 API calls

## Output layout

```
results/
├── cooperative/
│   ├── random__cola__S1.json
│   ├── random__cola__S2.json
│   ├── random__sparkling__S1.json
│   ├── ...
│   ├── random__all_transitions.json      ← merged for this buyer type
│   ├── wild__cola__S1.json
│   ├── ...
│   └── anchor_drag__all_transitions.json
├── anchor_high/
│   └── ...
└── ...
```

## Running

```bash
# Start with cooperative (recommended first):
python run_all_0413.py cooperative

# Run a specific buyer type within cooperative:
python run_all_0413.py cooperative random

# Run all strategies (long!):
python run_all_0413.py
```
