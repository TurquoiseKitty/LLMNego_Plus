# 0416b negotiation-data regeneration

Revision `b` of the 0416 pipeline, addressing the three follow-up adjustments:

1. **No round or deadline limits** — anywhere.
   * The supplier system prompt does not mention the current round, the
     total number of rounds, remaining rounds, a maximum round count, or
     any deadline phrasing.  Verified by a word-boundary `grep` pass over
     all six strategy prompts.
   * `build_supplier_prompt(...)` no longer takes `current_round` /
     `max_rounds` arguments.
   * No deadline-aware buyer or seller strategy exists in the codebase.

2. **Exactly 6 seller strategies**, chosen for maximum behavioural distance
   and identifiability:

   | strategy | signature |
   | --- | --- |
   | `anchor_high` | high opening price, tiny downward moves, stays near market |
   | `cooperative` | aims for 50/50 split of surplus, meets partway |
   | `boulware_seller` | holds near the top, minuscule per-turn concessions |
   | `conceder_seller` | big generous concessions early, slows as it nears a margin |
   | `tit_for_tat_matcher` | reactive; mirrors the merchant's movements |
   | `relational` | explicit partnership language; moderate price moves |

   The ten buyer strategies are unchanged except that the deadline-aware
   variant (`time_deadline_buyer`) has been removed.

3. **12 notebooks, each < 24 h.**  `n_rounds` was raised to 15 (from 12)
   because removing the deadline cue makes trajectories flatter and longer,
   and more rounds per run help the six strategies separate behaviourally.
   Each notebook is estimated at 16–19 h on `deepseek-reasoner`.

## Notebook layout

| NB | Mode | Conds | Runs | Est. h |
|---|---|---:|---:|---:|
| nb1 | fixed × fixed — `anchor_high` | 10 | 220 | 16.5 |
| nb2 | fixed × fixed — `cooperative` | 10 | 220 | 16.5 |
| nb3 | fixed × fixed — `boulware_seller` | 10 | 220 | 16.5 |
| nb4 | fixed × fixed — `conceder_seller` | 10 | 220 | 16.5 |
| nb5 | fixed × fixed — `tit_for_tat_matcher` | 10 | 220 | 16.5 |
| nb6 | fixed × fixed — `relational` | 10 | 220 | 16.5 |
| nb7 | 2-stage adaptive seller, **switch @ r=5** × 10 fixed buyers | 80 | 240 | 18.0 |
| nb8 | 2-stage adaptive seller, **switch @ r=8** × 10 fixed buyers | 80 | 240 | 18.0 |
| nb9 | 2-stage adaptive seller, **switch @ r=11** × 10 fixed buyers | 80 | 240 | 18.0 |
| nb10 | 3-stage adaptive seller (boundaries r=6, r=11) × 10 fixed buyers | 60 | 240 | 18.0 |
| nb11 | 6 adaptive buyers × 6 fixed sellers | 36 | 252 | 18.9 |
| nb12 | 6 adaptive buyers × 6 adaptive seller schedules (both adaptive) | 36 | 216 | 16.2 |
| **Total** |  | **442** | **2 748** | **206** |

### Where the extra exploration went

* **nb1–nb6**: one notebook per seller strategy rather than lumping two
  together.  Gives **22 runs per (buyer, seller) cell** (vs. 14 in v0416a),
  which matters for fitting a per-cell policy.
* **nb7–nb9**: the same eight seller-schedule pairs are run at three
  different switch-round timings (5, 8, 11 out of 15).  This is the main
  exploration boost: it lets you study at what point in a trajectory a
  strategy transition becomes detectable in the price sequence.
* **nb11**: all six fixed sellers × all six adaptive buyers (dense), so
  every fixed-seller policy gets probed by every adaptive-buyer profile.

## Files

* `exp_runner_0416.py` — core module (continuous product sampler, 10 buyer
  strategies, 6 seller strategies, adaptive buyer/seller, prompt builder,
  single/condition runners, transitions builder).
* `run_all_0416.py` — shared notebook driver: `run_experiment_block` plus
  convenience builders `all_fixed_buyers_for_notebook`,
  `fixed_pairs_for_sellers`.
* `run_all_0416b_nb1.ipynb` … `run_all_0416b_nb12.ipynb` — per-notebook
  `EXPERIMENTS` definitions + a cell that calls `run_experiment_block`.

## Usage

1. Drop `exp_runner_0416.py` and `run_all_0416.py` next to the notebooks,
   using the same folder layout as your 0413 project (NegoLib is picked
   up via `sys.path` at the top of each notebook).
2. Edit `CLIENT = OpenAI(api_key=...)` in each notebook.
3. Open any of the 12 notebooks and run all cells.  Output goes under
   `results_0416b/<notebook_id>/`.
4. The 12 notebooks are independent; run them in parallel on different
   machines / kernels so wall-clock is ≲ 19 h regardless of the 206 h
   serial cost.

The runner is resumable: re-running a notebook skips any condition whose
`.json` already exists and rebuilds the merged transitions file.

## Output layout

    results_0416b/nb1/
      sel_anchor_high__buy_random.json
      sel_anchor_high__buy_budget.json
      ...
      __all_transitions.json
      __manifest.json

Each per-condition file stores the raw per-round transcript with
`buyer_active_strategy`, `supplier_active_strategy`, `supplier_reasoning`,
`template_id`, and the sampled `ProductSpec`.  The merged
`__all_transitions.json` is the flat `(s_{t-1}, m_t) → s_t` table for
analysis, augmented with strategy labels for every side of every step.
