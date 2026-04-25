# Buyer-scheme negotiation sweep (NeurIPS 2026 paper, Section 2.2)

Data-generation pipeline for the main experiment in
*Prompt-Induced Linearity: Recovering Negotiation Policies in LLMs*.

One dealer (6 prompted-policy flavors) negotiates with a hard-coded random
buyer (4 generating schemes) over 5 vehicles, 50 independent cycles per
(policy, scheme, vehicle) cell, T = 12 turns per cycle.  All negotiations
go to T = 12; the analysis pipeline discards post-agreement turns
downstream.

**Total:** 6 × 4 × 5 × 50 = 6,000 cycles × 12 turns = 72,000 seller calls.

## Contents

| file | purpose |
|---|---|
| `config.py` | DeepSeek API key / endpoint / model, retry policy, sample sizes. |
| `plan.py` | The 120-cell grid (6 policies × 4 schemes × 5 vehicles), deterministic seeding, user/cooperator partition. |
| `buyer_schemes.py` | **The four buyer-generation schemes (A, B, C, D) from Appendix B.1.** |
| `seller_prompt_ensemble.py` | Six seller personas + scenario template. |
| `fleet.py` | Five used cars spanning cost/market = 0.20 → 0.80. |
| `negotiation.py` | One-negotiation loop: buyer → message → seller LLM → [PRICE] parse. |
| `proc_state.py` | Atomic state-file IO, stall detection, launcher state. |
| `worker.py` | Run one (policy, scheme, vehicle) cell. 50 runs × 12 rounds = 600 API calls. |
| `launcher.py` | Spawn N parallel workers across a side's 60 cells. |
| `status.py` | Live status report over `state/`. |
| `merge_results.py` | Combine user + cooperator JSONs into one unified dataset. |
| `smoke_test.py` | Mock / API / full smoke test before launching the sweep. |

## Design: 6-hour wall-clock budget

DeepSeek-reasoner calibration (observed): ~200 seller calls / hour / worker.
- **One cell:** 50 runs × 12 turns = 600 calls ≈ 3 h wall clock.
- **One side:** 60 cells × 600 calls = 36,000 calls.
- **Parallelism:** 30 workers × 2 cells in series = ~6 h wall clock per side.

DeepSeek billing is **per-token, not per-call**, so parallelism does not
increase cost — only rate-limit risk, which at 30 concurrent requests is
well within deepseek-reasoner's capacity.

## Splitting the work with a cooperator

The full sweep is split **by buyer scheme**:

| side | schemes | cells | approx time at 30 parallel |
|---|---|---|---|
| **user** | A, B | 60 | ~6 h |
| **cooperator** | C, D | 60 | ~6 h |

Seeds are deterministic and **non-overlapping** across sides
(see `plan.run_seed`), so the two output directories merge cleanly with
no duplicate or conflicting runs.  The cooperator runs the same code
with `--side cooperator`.

## Quick start

### 0. Install dependencies

```bash
pip install openai
```

Python 3.10+ required.  Set your API key in the environment or edit
`config.py`:

```bash
export NEGO_API_KEY="sk-..."
```

### 1. Pre-flight sanity checks (costs < $0.10 total)

```bash
# instant: mock seller, validates the pipeline end-to-end (no API)
python smoke_test.py --mode mock

# ~10 s: one real API call, validates credentials
python smoke_test.py --mode api

# ~3 min: one real negotiation across 12 rounds, validates live pipeline
python smoke_test.py --mode full --scheme A
python smoke_test.py --mode full --scheme B
python smoke_test.py --mode full --scheme C
python smoke_test.py --mode full --scheme D
```

Fix any parse failures or API errors before launching the full sweep.

### 2. Dry-run the plan

```bash
python launcher.py --side user --dry-run
```

Should list exactly 60 cells with tags like
`user_A_patient_value_defender_v1` through `user_B_market_expert_value_justifier_v5`.

### 3. Launch the sweep (detached, in background)

```bash
mkdir -p results state logs
nohup python launcher.py --side user > launcher.out 2>&1 &
```

Default parallelism is 30.  Override with `--parallelism N` if you want a
lower API concurrency.

### 4. Watch progress

```bash
python status.py --side user --watch
```

Each state line shows that worker's cell tag, PID, status, runs completed,
progress %, last round touched, and heartbeat age.

### 5. Resuming after a crash

Every cell writes a self-contained `results/<tag>.json`.  Re-launching the
launcher with `--skip-finished` skips cells whose state file reports
`status=finished`:

```bash
python launcher.py --side user --skip-finished
```

To force a full rerun of a specific cell, delete its state file and its
results JSON, then rerun the launcher (or call `worker.py` directly):

```bash
rm results/user_A_patient_value_defender_v1.json state/user_A_patient_value_defender_v1.state.json
python worker.py --side user --cell-index 0
```

### 6. After both sides finish: merge

Assuming the cooperator shipped their `results/` directory as
`coop_results/`:

```bash
python merge_results.py \
    --user-dir        results \
    --cooperator-dir  coop_results \
    --out-dir         merged_results \
    --manifest        merged_manifest.csv
```

This validates all 120 tags are present, that there are no duplicates, and
copies everything into `merged_results/` plus a CSV manifest for
downstream analysis notebooks.

## Killing a runaway sweep

```bash
python status.py --side user --kill-all   # sends SIGTERM to every live
                                            # worker + the launcher
```

Workers catch SIGTERM, write a final checkpoint and flip status to `killed`
in their state file.  On SIGTERM, the launcher also forwards to all children
before exiting cleanly.

## Output schema

Each `results/<tag>.json` contains:

```json
{
  "experiment": {
    "tag":           "user_A_patient_value_defender_v1",
    "side":          "user",
    "policy":        "patient_value_defender",
    "buyer_scheme":  "A",
    "vehicle_idx":   0,
    "vehicle_name":  "2014 Mercedes-Benz S550",
    "n_rounds":      12,
    "runs_per_car":  50,
    "n_runs_total":  50,
    "model":         "deepseek-reasoner",
    "base_seed":     20260425,
    ...
  },
  "fleet": [ ... 5 car records ... ],
  "runs": [
    {
      "car":            {car_name, public_description, market_price_new, dealer_cost},
      "rng_seed":       20260425 + ...,
      "n_rounds":       12,
      "policy":         "patient_value_defender",
      "buyer_scheme":   "A",
      "buyer_state":    { ... per-run state snapshot ... },
      "model":          "deepseek-reasoner",
      "rounds": [
        {
          "round":                1,
          "buyer_price":          14321.55,
          "buyer_message":        "... [PRICE] line",
          "buyer_template_id":    2,
          "seller_system_prompt": "<full prompt on round 1 only, null otherwise>",
          "seller_answer":        "... [PRICE] line",
          "seller_reasoning":     "... deepseek chain-of-thought ...",
          "seller_price":         22499.00
        },
        ... x12 rounds
      ]
    },
    ... x50 runs
  ]
}
```

## File naming convention

Tag format: `<side>_<scheme>_<policy>_v<vehicle_idx+1>`
- `side`      ∈ {`user`, `coop`}
- `scheme`    ∈ {`A`, `B`, `C`, `D`}
- `policy`    = one of the six canonical policy keys
- `vehicle_idx+1` ∈ {1..5}

Examples:
- `user_A_patient_value_defender_v1`
- `user_B_market_expert_value_justifier_v5`
- `coop_C_reciprocal_fairness_keeper_v3`
- `coop_D_friendly_rapport_builder_v2`

## Seeding

```
run_seed(policy, scheme, vehicle_idx, run_idx) =
    BASE_SEED
    + POLICY_IDX[policy]  * 10_000_000
    + SCHEME_IDX[scheme]  *  1_000_000
    + vehicle_idx         *    100_000
    + run_idx
```

Distinct powers of 10 per factor guarantee zero collisions for up to
10^5 = 100,000 runs per (policy, scheme, vehicle), which comfortably
covers N_RUNS_PER_CAR = 50 plus any pilot or replication work.
