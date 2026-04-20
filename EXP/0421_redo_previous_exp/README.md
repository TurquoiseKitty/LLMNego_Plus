# Used-Car Dealer Negotiation Data Generation (v2, process-state-tracked)

One launcher, 12 parallel worker processes, each aiming for ~10-12 hours
on `deepseek-reasoner`, **with per-process state files so you can always
tell what's running, what finished, what crashed, and what silently died.**

## What's new in v2

* `state/<tag>.state.json` per worker: PID, hostname, status, timestamps,
  runs completed, rounds completed, last car/run/round touched, error or
  traceback on failure.  Rewritten atomically after every round, run, and
  car checkpoint.
* `state/_launcher.state.json`: the launcher PID plus every worker PID,
  so `pkill` / `kill` is a last resort -- you usually just read PIDs.
* `status.py`: one-shot or `--watch` table of every worker's state,
  including a derived `stalled` status (= "claims to be running but
  hasn't written a heartbeat in 10 minutes; process likely died without
  an obituary").
* `status.py --kill-all`: reads PIDs out of the state files and SIGTERMs
  every live worker plus the launcher.
* Worker signal handling: SIGTERM / SIGINT flip status to `killed` with
  the signal name in the error field.  Uncaught exceptions flip it to
  `crashed` with the full traceback.  Both paths save a partial results
  JSON before exiting, so no in-progress data is lost.
* Launcher SIGTERM handling: `kill <launcher_pid>` now cleanly terminates
  all children (previously only Ctrl+C worked).

## Files

| File | Purpose |
|---|---|
| `config.py` | DeepSeek API key, base URL, model, call params, retry policy, workload calibration. |
| `seller_prompt_ensemble.py` | Strategy catalog and system-prompt builder (unchanged). |
| `fleet.py` | The 5 concrete used cars, cost/M ratio spread from ~20% to ~80%. |
| `seller_schedule.py` | Per-round strategy schedules: fixed, two-phase, three-phase. |
| `negotiation.py` | Buyer sampler, buyer message builder, seller price parser, DeepSeek call with retry, `[buyer]` / `[seller]` history format, one-negotiation loop. |
| `experiments.py` | The 12 experiments (6 fixed + 3 x transition A + 3 x transition B). |
| `proc_state.py` | **NEW.** Atomic state-file IO, stall detection, launcher state. |
| `worker.py` | Subprocess entry point. Writes heartbeats and status to its state file at every boundary. |
| `launcher.py` | Spawns 12 workers, records their PIDs, handles SIGINT/SIGTERM. |
| `status.py` | **NEW.** CLI for inspecting and killing the running sweep. |
| `smoke_test.py` | Pre-flight DeepSeek check (1 API call) or full-negotiation check. |

## Running the full sweep

```bash
cd used_car_negotiation

# 1. optional pre-flight (~20 s, 1 API call)
python smoke_test.py

# 2. launch, detached from the terminal
nohup python launcher.py > launcher.out 2>&1 &

# 3. watch progress
python status.py --watch
```

Three directories populate as the workers run:
* `results/<tag>.json`  -- 12 files, atomically rewritten after each car completes
* `logs/<tag>.log`      -- 12 files, one clean log per worker
* `state/<tag>.state.json` + `_launcher.state.json` -- 13 state files

## `status.py` -- the piece you wanted for last time

```bash
python status.py                   # one-shot snapshot
python status.py --watch           # refresh every 10 s
python status.py --kill-all        # SIGTERM every live worker + launcher
```

Sample output:

```
================================================================================================
Launcher: pid=12345  status=running  host=node07  started=2026-04-20T10:00:00+00:00  hb_age=8s
================================================================================================
tag                                               pid status          runs  progress  car round     hb alive
------------------------------------------------------------------------------------------------
exp00_fixed_patient_value_defender              12401 running       45/150     32.3%  2/5    12    4s   yes
exp01_fixed_busy_impatient_closer               12402 finished     150/150    100.0%  5/5    16   2.3h   no
exp02_fixed_friendly_rapport_builder            12403 running       38/150     28.0%  2/5     9    6s   yes
exp03_fixed_reciprocal_fairness_keeper          12404 stalled       22/150     15.1%  1/5    16  24.0m    no
exp04_fixed_opponent_aware_diagnostic           12405 crashed       31/150     22.3%  2/5     7  1.2h    no
...
------------------------------------------------------------------------------------------------
Totals:  live=9  finished=1  crashed=1  killed=0  stalled=1  no_state_file=0
```

Status meanings:
* **spawned**   -- worker booted but hasn't made its first API call yet
* **running**   -- actively working, heartbeat fresh
* **finished**  -- normal successful exit
* **crashed**   -- uncaught Python exception (traceback in state file's `traceback` field)
* **killed**    -- SIGTERM / SIGINT received (signal name in `error` field)
* **stalled**   -- status claims running but heartbeat is > 10 min old; the process most likely died without getting to write its obituary (the case your last sweep was in when you opened the rar)

## Killing running processes

Any of these works:

```bash
# Nicest: read PIDs from state/, SIGTERM each, workers mark themselves killed
python status.py --kill-all

# Equivalent:
kill <launcher_pid>     # launcher signal handler SIGTERMs its children

# Blunt:
pkill -f "used_car_negotiation/worker.py"
pkill -f "used_car_negotiation/launcher.py"

# Second Ctrl+C at an attached launcher = hard SIGKILL
```

## Re-running a subset

Since the last sweep left 40 % or 60 % of each experiment complete, you can
wipe the old results and rerun everything, or rerun a subset:

```bash
# rerun only the stalled ones (for example)
python launcher.py --only 0 3 4 5 9 10 11

# rerun one
python worker.py --experiment-index 9
```

A rerun **overwrites** the existing JSON from scratch; there is no
mid-experiment resume.  Per-car checkpoints (every ~2.4 h) mean the worst-case
data loss on a mid-run kill is one car's worth of runs (at 30 runs/car,
16 rounds each, ~1-2 h of calls).

## State-file schema

One `state/<tag>.state.json` per worker.  Fields:

| field | meaning |
|---|---|
| `tag` | e.g. `exp00_fixed_patient_value_defender` |
| `experiment_index` | 0..11 |
| `pid`, `parent_pid` | OS process IDs |
| `hostname`, `cwd`, `cmdline` | where it's running |
| `config_summary` | model, base_url, runs_per_car, n_rounds, base_seed |
| `status` | spawned \| running \| finished \| crashed \| killed |
| `spawned_at`, `started_at`, `heartbeat_at`, `ended_at` | ISO-8601 UTC timestamps |
| `exit_code` | 0 finished, 1 crashed, 128 killed, null if still running |
| `error` | short error string (signal name, exception msg) on non-finished exit |
| `traceback` | full traceback string on crashed |
| `planned_runs`, `planned_rounds` | `5 * runs_per_car`, `planned_runs * n_rounds` |
| `runs_completed`, `rounds_completed` | running counters |
| `last_car_idx` (0..4), `last_run_idx`, `last_round` (1..16) | location of the last heartbeat |
| `last_checkpoint_at` | UTC timestamp of last per-car JSON save |

And `state/_launcher.state.json`:

| field | meaning |
|---|---|
| `launcher_pid`, `hostname`, `cwd` | where the launcher runs |
| `status` | running \| finished \| interrupted |
| `started_at`, `heartbeat_at`, `ended_at` | timestamps |
| `workers` | `[{tag, experiment_index, pid}, ...]` for every child spawned |

## The 12 experiments

| idx | tag | schedule |
|---:|---|---|
| 00 | `exp00_fixed_patient_value_defender`      | fixed |
| 01 | `exp01_fixed_busy_impatient_closer`       | fixed |
| 02 | `exp02_fixed_friendly_rapport_builder`    | fixed |
| 03 | `exp03_fixed_reciprocal_fairness_keeper`  | fixed |
| 04 | `exp04_fixed_opponent_aware_diagnostic`   | fixed |
| 05 | `exp05_fixed_market_expert_value_justifier` | fixed |
| 06..08 | `exp06/07/08_transitionA_rep{1,2,3}` | `friendly_rapport_builder` -> `patient_value_defender` @ r9 |
| 09..11 | `exp09/10/11_transitionB_rep{1,2,3}` | `opponent_aware_diagnostic` (1-5) -> `market_expert_value_justifier` (6-11) -> `reciprocal_fairness_keeper` (12-16) |

Each: all 5 cars x 30 runs x 16 rounds = 2,400 seller calls ≈ 10-12 h on
`deepseek-reasoner`.

## Results schema (unchanged from v1)

Each `results/<tag>.json` has:

```
{
  "experiment": { ... metadata, now also includes pid, hostname ... },
  "fleet":      [ 5 car records ],
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
          "buyer_message": "... [PRICE] line",
          "buyer_template_id": 2,
          "seller_active_strategy": "patient_value_defender",
          "seller_strategy_changed": true,
          "seller_system_prompt": "<full system prompt on strategy-change rounds, null otherwise>",
          "seller_answer": "... [PRICE] line",
          "seller_reasoning": "... deepseek chain-of-thought ...",
          "seller_price": 22499.00
        },
        ... x16 rounds
      ]
    },
    ... x150 runs (5 cars x 30 runs)
  ]
}
```
