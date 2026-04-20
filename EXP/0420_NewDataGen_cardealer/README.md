# Used-Car Dealer Negotiation Data Generation  (DeepSeek-reasoner edition)

One launcher, 12 parallel worker processes, each ~12 hours of wall-clock on
`deepseek-reasoner`, yielding 12 × 150 = **1,800 complete negotiations** and
**28,800 seller LLM calls** in total.

## Files

| File | Purpose |
|---|---|
| `config.py` | DeepSeek API key, base URL, model, call params, retry policy, workload calibration. Edit to change the key. |
| `seller_prompt_ensemble.py` | Strategy catalog and system-prompt builder (unchanged from your upload). |
| `fleet.py` | The 5 concrete used cars, cost/M ratio spread from **~20 %** to **~80 %**. |
| `seller_schedule.py` | Per-round strategy schedules: `fixed_schedule`, `two_phase_schedule`, `three_phase_schedule`. |
| `negotiation.py` | Buyer sampler, buyer message builder, seller price parser, **DeepSeek reasoner call** (exact 0416b params, with retry), `[buyer]` / `[seller]` history format, one-negotiation loop. |
| `experiments.py` | The 12 experiments (6 fixed + 3 × transition A + 3 × transition B). |
| `worker.py` | Subprocess entry point: runs ONE experiment (5 cars × 30 runs × 16 rounds), checkpoints after each car. |
| `launcher.py` | Spawns 12 subprocess workers, streams their output with `[tag]` prefixes, mirrors to per-worker log files. |

## The fleet (cost / M ratios span 20 % -> 80 %)

| Car | M (new MSRP) | dealer_cost | ratio |
|---|---:|---:|---:|
| 2014 Mercedes-Benz S550 | $96,000 | $19,000 | **19.8 %** |
| 2016 Cadillac CTS 3.6 Luxury | $45,000 | $15,750 | **35.0 %** |
| 2019 Honda Accord Sport 1.5T | $28,000 | $14,000 | **50.0 %** |
| 2022 Toyota RAV4 XLE AWD | $32,000 | $20,800 | **65.0 %** |
| 2023 Ford Mustang GT Premium | $45,000 | $36,000 | **80.0 %** |

## The 12 experiments

| idx | tag | schedule |
|---:|---|---|
| 00 | `exp00_fixed_patient_value_defender`      | fixed 16 rounds |
| 01 | `exp01_fixed_busy_impatient_closer`       | fixed 16 rounds |
| 02 | `exp02_fixed_friendly_rapport_builder`    | fixed 16 rounds |
| 03 | `exp03_fixed_reciprocal_fairness_keeper`  | fixed 16 rounds |
| 04 | `exp04_fixed_opponent_aware_diagnostic`   | fixed 16 rounds |
| 05 | `exp05_fixed_market_expert_value_justifier` | fixed 16 rounds |
| 06 | `exp06_transitionA_rep1` | `friendly_rapport_builder` → `patient_value_defender` @ r9 |
| 07 | `exp07_transitionA_rep2` | same schedule |
| 08 | `exp08_transitionA_rep3` | same schedule |
| 09 | `exp09_transitionB_rep1` | `opponent_aware_diagnostic` (1-5) → `market_expert_value_justifier` (6-11) → `reciprocal_fairness_keeper` (12-16) |
| 10 | `exp10_transitionB_rep2` | same schedule |
| 11 | `exp11_transitionB_rep3` | same schedule |

Each experiment explores **all 5 cars × 30 runs × 16 rounds = 2,400 seller
calls**, targeting ~12 h on `deepseek-reasoner` at the calibrated 0416b rate
of ~200 calls/hour.

## The buyer (fixed across all experiments)

```
round 1:       buyer_price ~ Uniform(0, market_price_new)
round t >= 2:  buyer_price ~ Uniform(0, min(market_price_new, prev_seller_price) - 0.01)
```
The $0.01 offset keeps the buyer strictly below the seller's last quote, so
the buyer can never "accept by coincidence". Each buyer turn ends with a
`[PRICE] <car_name>: $X.XX` line so the seller can parse it cleanly.

## How the LLM call is done  (matches 0416b)

For `deepseek-reasoner` (default):

```python
client.chat.completions.create(
    model="deepseek-reasoner",
    messages=[system_with_history_block, user_prompt],
    max_tokens=4096,
    extra_body={"enable_thinking": True, "thinking_budget": 8192},
)
```

The reply's `.content` is stored as `seller_answer`; the separate
`.reasoning_content` attribute is stored as `seller_reasoning`.  History is
serialised directly into the system prompt with lowercase bracketed labels:

```
[buyer]
I'd be willing to pay $27,500.00 for the 2019 Honda Accord Sport 1.5T.
[PRICE] 2019 Honda Accord Sport 1.5T: $27500.00

[seller]
I appreciate the offer, but ...
[PRICE] 2019 Honda Accord Sport 1.5T: $25,999.00

...
```

An OpenAI / GPT fallback path is also implemented (uses `<think>` tags and
`max_completion_tokens=8192`); it kicks in automatically when the model
name starts with `gpt`, `o1`, `o3`, or `o4`.

## Running the full sweep

The DeepSeek API key is already embedded in `config.py` (copied from your
0416b notebook). **No env var is required** to run the default workload:

```bash
python launcher.py
```

That's it. Output lands in `results/` and `logs/`.

### Overrides via environment

Any config key can be overridden without editing the file:

```bash
NEGO_API_KEY=sk-new-key  python launcher.py
NEGO_MODEL=gpt-4o        python launcher.py        # auto-uses <think> tags
NEGO_RUNS_PER_CAR=10     python launcher.py        # quick smoke test (~4 h)
```

### Running a single experiment

```bash
python worker.py --experiment-index 9
```

### Re-running a subset

```bash
python launcher.py --only 6 7 8           # rerun transition A only
python launcher.py --only 11              # rerun one experiment
```

### Rate-limit-friendly ramp-up

```bash
python launcher.py --stagger 2.0          # 2 s between spawns
```

## Checkpointing

After every car completes (every 30 runs, roughly every 2.4 h), the worker
atomically rewrites `results/<tag>.json` with everything produced so far.
If a worker is killed mid-experiment, you keep all finished cars' runs;
rerun with `python launcher.py --only N` to complete that experiment.

## Output schema

One JSON per experiment, e.g. `results/exp00_fixed_patient_value_defender.json`:

```
{
  "experiment": {
    "index": 0,
    "tag":   "exp00_fixed_patient_value_defender",
    "group": "fixed", "replicate": 0,
    "seller_schedule": {
      "label": "fixed__patient_value_defender",
      "schedule": ["patient_value_defender", ... x16],
      "is_adaptive": false,
      "switch_points": [],
      "unique_strategies": ["patient_value_defender"]
    },
    "n_rounds": 16, "n_cars": 5, "runs_per_car": 30, "n_runs_total": 150,
    "model": "deepseek-reasoner",
    "base_url": "https://api.deepseek.com",
    "base_seed": 20260420,
    "total_seconds": ..., "total_hours": ..., "timestamp": "..."
  },
  "fleet": [ {car records including cost_over_market_ratio}, ... ],
  "runs": [
    {
      "car":              {car_name, public_description, market_price_new, dealer_cost},
      "rng_seed":         ...,
      "n_rounds":         16,
      "seller_schedule":  {...},
      "model":            "deepseek-reasoner",
      "rounds": [
        {
          "round": 1,
          "buyer_price": 14321.55,
          "buyer_message": "...ending with [PRICE] line",
          "buyer_template_id": 2,
          "seller_active_strategy": "patient_value_defender",
          "seller_strategy_changed": true,
          "seller_system_prompt": "<full system prompt on rounds where strategy changes, null otherwise>",
          "seller_answer": "... ending with [PRICE] line",
          "seller_reasoning": "... deepseek-reasoner chain-of-thought ...",
          "seller_price": 22499.00
        },
        ... x16 rounds
      ]
    },
    ... x150 runs (= 5 cars x 30 runs)
  ]
}
```

## One command to start everything

```bash
cd used_car_negotiation
python launcher.py
```
