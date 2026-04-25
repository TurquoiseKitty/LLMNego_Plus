# 0423 LLM-buyer sweep

Twelve LLM-vs-LLM used-car negotiation experiments. The seller side is
**identical** to the 0421 sweep (same 6 dealer-style strategies, same
system prompt, same DeepSeek-reasoner call path). The buyer side has been
upgraded from a uniform-random price sampler to a **proper LLM agent**
with its own system prompt.

## What's new vs. 0421

| | 0421 | 0423 (this sweep) |
|---|---|---|
| Seller | DeepSeek-reasoner, 6 strategies | Same |
| Buyer | `random.uniform(0, min(M, prev_seller) - 0.01)` | LLM agent with its own system prompt |
| Experiments | 6 fixed + 6 with strategy transitions | 6 seller strategies × natural buyer, then 6 seller strategies × mirror buyer |
| Runs / car | 30 | 15 (halved to keep per-experiment wall clock at ~12 h) |
| Base seed | 20260420 | 20260423 |

## Experiment layout

All 12 experiments use a fixed seller strategy for all 16 rounds. The
variable across the sweep is the **buyer**.

**Group A — `natural_buyer` (exp 00..05)**: each of the 6 seller strategies
paired with a single plain, price-conscious buyer persona. This is the
closest analogue to the 0421 fixed-seller experiments; the only systematic
difference per experiment is the seller strategy.

| idx | tag |
|---|---|
| 00 | `exp00_fixed_patient_value_defender__vs__natural_buyer` |
| 01 | `exp01_fixed_busy_impatient_closer__vs__natural_buyer` |
| 02 | `exp02_fixed_friendly_rapport_builder__vs__natural_buyer` |
| 03 | `exp03_fixed_reciprocal_fairness_keeper__vs__natural_buyer` |
| 04 | `exp04_fixed_opponent_aware_diagnostic__vs__natural_buyer` |
| 05 | `exp05_fixed_market_expert_value_justifier__vs__natural_buyer` |

**Group B — mirror buyer (exp 06..11)**: each of the 6 seller strategies
paired with the same-name buyer-side mirror persona (e.g. seller
`patient_value_defender` against buyer `patient_value_defender`). The
mirror prompts are *not* copy-ports of the seller prompts — each is
re-written from a buyer's perspective (no talk of margin/floor/dealer cost,
etc.).

| idx | tag |
|---|---|
| 06 | `exp06_fixed_patient_value_defender__vs__mirror_patient_value_defender` |
| 07 | `exp07_fixed_busy_impatient_closer__vs__mirror_busy_impatient_closer` |
| 08 | `exp08_fixed_friendly_rapport_builder__vs__mirror_friendly_rapport_builder` |
| 09 | `exp09_fixed_reciprocal_fairness_keeper__vs__mirror_reciprocal_fairness_keeper` |
| 10 | `exp10_fixed_opponent_aware_diagnostic__vs__mirror_opponent_aware_diagnostic` |
| 11 | `exp11_fixed_market_expert_value_justifier__vs__mirror_market_expert_value_justifier` |

## Buyer invariants (important)

The buyer system prompt is built by `buyer_prompt_ensemble.build_buyer_prompt`.
By construction, across **all 7** buyer strategies (natural + 6 mirrors):

- The buyer **does NOT know the dealer's true cost v**. The buyer prompt contains no PRIVATE-INFORMATION / PROFIT-RULE section and no dealer cost number; the buyer is told explicitly not to claim or invent one.
- The buyer **does NOT walk away early**. Every buyer turn must end with a `[PRICE]` line. The GLOBAL NEGOTIATION RULES block says there is no quit option and forbids declaring the negotiation over.
- The buyer is **not informed of the round limit**. No turn count is mentioned anywhere in the buyer prompt.

`smoke_test.py` has an automated check that the dealer cost string is not
present anywhere in any buyer prompt for any car.

## File layout

```
0423_llm_buyer_exp/
├── config.py                    # API + workload config
├── fleet.py                     # The 5 cars (unchanged from 0421)
├── seller_prompt_ensemble.py    # 6 seller strategies (byte-exact w/ 0421)
├── buyer_prompt_ensemble.py     # natural_buyer + 6 mirror buyers  [NEW]
├── seller_schedule.py           # Per-round seller strategy lookup (unchanged)
├── buyer_schedule.py            # Per-round buyer strategy lookup   [NEW]
├── negotiation.py               # One trajectory: LLM buyer + LLM seller
├── experiments.py               # The 12-experiment manifest
├── worker.py                    # Run ONE experiment in one process
├── launcher.py                  # Spawn all 12 workers in parallel
├── proc_state.py                # State/heartbeat file format (unchanged)
├── status.py                    # Poll state files; report status (unchanged)
├── smoke_test.py                # Preflight checks (offline + optional API)
├── state/                       # state/<tag>.state.json per worker (runtime)
├── logs/                        # logs/<tag>.log per worker (runtime)
└── results/                     # results/<tag>.json per experiment (runtime)
```

## How to run

### Preflight (no API needed)

```bash
cd 0423_llm_buyer_exp
python smoke_test.py
```

This verifies: imports, all 6 seller + 7 buyer prompts build for all 5 cars,
the buyer prompt never leaks the dealer cost, the 12-experiment manifest
shape, and the `[PRICE]` parser.

### Preflight (with API)

```bash
python smoke_test.py --api 1          # one tiny round-trip
python smoke_test.py --negotiate      # one full 3-round negotiation (~1-2 min)
```

### Run the whole sweep

```bash
# 12 workers in parallel, ~12 h each. Separate log per experiment.
python launcher.py
```

### Run a subset

```bash
python launcher.py --only 0 6               # one from each group
python launcher.py --only 3                 # just exp03
```

### Run one experiment directly (no launcher)

```bash
python worker.py --experiment-index 0
```

### Monitor progress

```bash
python status.py
```

## Per-round log fields

Each entry in `results/<tag>.json → runs[i].rounds[j]` now includes both
sides:

```python
{
  "round": 1,

  # Buyer
  "buyer_active_strategy":  "natural_buyer",
  "buyer_strategy_changed": True,
  "buyer_system_prompt":    "...",       # only on change; None otherwise
  "buyer_message":          "...",
  "buyer_reasoning":        "...",       # DeepSeek reasoner CoT
  "buyer_price":            24000.00,
  "buyer_parse_attempts":   1,           # >1 if we had to re-prompt for format

  # Seller
  "seller_active_strategy":  "patient_value_defender",
  "seller_strategy_changed": True,
  "seller_system_prompt":    "...",
  "seller_answer":           "...",
  "seller_reasoning":        "...",
  "seller_price":            34000.00,
}
```

Buyer parse-failure policy: if the buyer LLM fails to produce a valid
`[PRICE]` line, we re-prompt with a terse correction up to
`_BUYER_PARSE_RETRIES = 2` more times (so three attempts total). If all
three fail, `buyer_price` is stored as `null`, the raw answer is kept in
`buyer_message`, and the sweep moves on.

## Configuration knobs

All are `config.py` constants, each overridable via an env var:

| env var | default | meaning |
|---|---|---|
| `NEGO_API_KEY` | hardcoded | DeepSeek API key |
| `NEGO_BASE_URL` | `https://api.deepseek.com` | API endpoint |
| `NEGO_MODEL` | `deepseek-reasoner` | Seller model (also default buyer model) |
| `NEGO_BUYER_MODEL` | `$NEGO_MODEL` | Override buyer model independently |
| `NEGO_RUNS_PER_CAR` | 15 | Runs per car per experiment |
| `NEGO_N_ROUNDS` | 16 | Rounds per run |
| `NEGO_BASE_SEED` | 20260423 | Seed base (run-level seed = BASE + exp_idx*100000 + car_idx*1000 + run_idx) |

## Downstream analysis tips

- Exp 00..05 vs. exp 06..11: holding seller strategy fixed, does a mirrored buyer change seller outcome (final price, price path, round of first meaningful seller concession, etc.)?
- Within each group: the seller-strategy axis is the same as in 0421; re-running any 0421 seller-side analysis against exp 00..05 should give broadly similar seller behavior (same seller prompt verbatim) with a more realistic conversation partner.
- Symmetric-roles diagnostic: for exp 06..11, because buyer and seller have the *same-name* persona (but different-content prompts), divergence between buyer and seller paths isolates what the persona prescribes for each side, not the persona itself.

## Where the seller prompt is guaranteed identical to 0421

`seller_prompt_ensemble.build_prompt(...)` output has been verified
byte-for-byte against every `seller_system_prompt` stored in the 0421
results JSON, across all 6 strategies × 5 cars (30/30 match). This means
any change in seller behavior between 0421 and 0423 is attributable to the
new buyer side, not to drift in the seller prompt.
