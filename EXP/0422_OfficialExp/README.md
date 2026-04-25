# Used-Car Dealer Negotiation Data Generation — 12 Representative Single-Strategy Prompts

This package keeps the original code structure, but changes the seller prompt
catalog and the experiment list so you can run **12 single-strategy seller
experiments** directly from `launcher.py`.

The core loop is unchanged:
- same fleet,
- same buyer script,
- same negotiation runner,
- same worker / launcher structure,
- same output JSON schema.

What changed:
- `seller_prompt_ensemble.py` now contains **12 representative seller prompts** selected from Appendix A / Table 1 of the uploaded paper.
- `experiments.py` now defines **12 fixed schedules only** (one prompt per experiment, all 16 rounds).
- `smoke_test.py` was updated so its assumptions match the new fixed-only setup.

## Why these 12?

The selection focuses on seller-side price-updating behavior in a **single-issue,
price-only** negotiation, where the buyer is an automatic script rather than a
rich conversational agent.

So the kept prompt families emphasize pricing logic such as:
- anchoring,
- patience,
- aggression,
- fairness vs. passivity,
- opponent modeling,
- stochastic pricing,
- reactive concession rules,
- threshold-triggered punishment.

The intentionally excluded families are the ones that are less informative for
this specific setup, such as:
- protocol / proposal-cap limits,
- rapport-only low-dominance prompts,
- multi-issue logrolling / mutual-gain prompts,
- near-duplicate reservation-inference prompts once a stronger mental-model
  version is already present.

## Files

| File | Purpose |
|---|---|
| `config.py` | API key / base URL / model / retry / workload settings. |
| `seller_prompt_ensemble.py` | The 12 selected seller prompt templates and system-prompt builder. |
| `fleet.py` | The 5 used cars spanning cost / market ratios from ~20% to ~80%. |
| `seller_schedule.py` | Schedule helpers. Still present, but all experiments now use `fixed_schedule(...)`. |
| `negotiation.py` | Buyer sampler, seller API call, price parser, and one-negotiation loop. |
| `experiments.py` | The 12 fixed single-strategy experiments. |
| `worker.py` | Runs one experiment end-to-end. |
| `launcher.py` | Spawns all 12 experiment workers. |
| `smoke_test.py` | Quick pre-flight API check. |

## The 12 seller strategies

| idx | strategy key | source idea |
|---:|---|---|
| 00 | `fu_high_price_brief_anchor` | Fu et al. [high-price] |
| 01 | `deng_patient_rational_extractor` | Deng et al. [patient] |
| 02 | `vaccaro_warm_high_dominance` | Vaccaro et al. [warm-highdom] |
| 03 | `liu_mental_model_tactician` | Liu et al. [mental-model] |
| 04 | `chatterjee_aggressive_high_ask` | Chatterjee et al. [aggressive] |
| 05 | `chatterjee_fair_midpoint` | Chatterjee et al. [fair] |
| 06 | `chatterjee_passive_gradual` | Chatterjee et al. [passive] |
| 07 | `kong_stochastic_sampler` | Kong et al. [sampler] |
| 08 | `kwon_competitive_reactive_guard` | Kwon et al. [AEO/NCR/RNC] |
| 09 | `mangla_mirroring_responder` | Mangla et al. [mirroring] |
| 10 | `mazur_grim_trigger_punisher` | Mazur et al. [grim-trigger] |
| 11 | `mazur_corridor_keeper` | Mazur et al. [corridor] |

Every experiment is fixed for all 16 rounds, so the prompt-induced pricing
pattern is easier to attribute to a single prompt family.

## Python dependency

This package expects the OpenAI Python client to be installed because the
runner uses the OpenAI-compatible chat completion interface:

```bash
pip install -r requirements.txt
```

## Running

### Run all 12 experiments

```bash
python launcher.py
```

### Run one experiment

```bash
python worker.py --experiment-index 7
```

### Run a subset

```bash
python launcher.py --only 0 1 2
```

### Quick API smoke test

```bash
python smoke_test.py
python smoke_test.py --full
```

## Output

The output format is the same as in the original package.
Each worker writes:

```text
results/expXX_fixed_<strategy>.json
```

Each JSON contains:
- experiment metadata,
- fleet metadata,
- all negotiation runs,
- per-round seller prompt info,
- per-round buyer / seller prices,
- raw seller answers and reasoning fields.

## Notes on comparability

Because the buyer script and all other infrastructure are unchanged, the main
cross-experiment difference is the **seller system prompt**. That makes this
package appropriate for studying how different implicit seller instructions map
to different seller price trajectories.
