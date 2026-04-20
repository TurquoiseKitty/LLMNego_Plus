# 0418 follow-up sweep

Successor to the 0416b sweep, designed for the follow-up analysis on the
`Low` / `Negotiation` region structure and strategy-switching dynamics.

## What changed from 0416b

1. **16 rounds per run** (up from 15).
2. **Three seller strategies only**: `cooperative`, `tit_for_tat_matcher`,
   `anchor_high`.
3. **One buyer strategy**: random uniform in `[cost, s_prev)` every round.
4. **Continuous product economics**:
   ```
   c, v − c, M − v   ~ iid Uniform(0, 5)
   ```
   so `c` (production cost), `v` (break-even), `M` (market price) cover
   a continuous range, with `c < v < M` by construction.
5. **One deterministic switching rule**, applied identically in all 9
   adaptive notebooks:
   ```python
   g = (s_prev - m_t) / s_prev
   next_strategy = cooperative          if g < 0.25
                 = anchor_high          if g > 0.60
                 = previous_strategy    otherwise
   ```
   The rule depends on all three of (previous strategy, current buyer
   price `m_t`, previous seller price `s_prev`), as requested. Rationale:
   - `g` is the merchant's offer gap as a fraction of the seller's last
     quote — a scale-free measure of how aggressive the offer is.
   - Small `g` means the merchant is close to accepting → reward with
     `cooperative`.
   - Large `g` means lowballing → punish with `anchor_high`.
   - Middle `g` keeps the previous strategy → creates persistence so the
     analysis can distinguish *momentum* from *reactive switches*.
   - Thresholds `(0.25, 0.60)` make the three outcomes roughly balanced
     under uniform `m_t`: ≈ 25% cooperative, 35% keep, 40% anchor_high.

## Notebook layout

| NB | Mode | Seller | Initial | Adaptive | N runs | Budget |
|---|---|---|---|:-:|---:|---:|
| nb1 | fixed | cooperative | cooperative | ✗ | 130 | ~10 h |
| nb2 | fixed | tit_for_tat_matcher | tit_for_tat_matcher | ✗ | 130 | ~10 h |
| nb3 | fixed | anchor_high | anchor_high | ✗ | 130 | ~10 h |
| nb4 | adaptive | switching rule | tit_for_tat_matcher | ✓ | 130 | ~10 h |
| nb5 | adaptive | switching rule | cooperative | ✓ | 130 | ~10 h |
| nb6 | adaptive | switching rule | anchor_high | ✓ | 130 | ~10 h |
| nb7 | adaptive | switching rule | tit_for_tat_matcher | ✓ | 130 | ~10 h |
| nb8 | adaptive | switching rule | cooperative | ✓ | 130 | ~10 h |
| nb9 | adaptive | switching rule | anchor_high | ✓ | 130 | ~10 h |
| nb10 | adaptive | switching rule | tit_for_tat_matcher | ✓ | 130 | ~10 h |
| nb11 | adaptive | switching rule | cooperative | ✓ | 130 | ~10 h |
| nb12 | adaptive | switching rule | anchor_high | ✓ | 130 | ~10 h |

Each notebook has a distinct `BASE_SEED` (6000–17000) so the 12 sweeps
produce independent trajectories. The 9 adaptive notebooks implement the
**same** rule — their purpose is to accumulate statistical power (9 ×
130 = 1170 adaptive runs total) while each individual notebook stays
under 12 hours of wall-clock.

Budget: 16 rounds × ~0.3 min/round ≈ 4.8 min/run → 130 runs ≈ 10.4 h per
notebook, comfortably under the 12 h target.

## Files

- `exp_runner_0418.py` — product sampling, buyer sampler, switching rule,
  supplier prompt (deadline-free, 3 strategies), price extraction,
  `run_single` (works for fixed and adaptive modes).
- `run_all_0418.py` — `run_block(...)` driver; writes one JSON per run
  (crash-resistant) plus `__manifest.json` per notebook.
- `run_all_0418_nb{1..12}.ipynb` — 12 independent notebooks.

## Output layout

    results_0418/
      nb1/
        run_000_seed6000.json
        run_001_seed6001.json
        ...
        run_129_seed6129.json
        __manifest.json
      nb2/ ...
      ...

Each run JSON stores: the sampled `ProductSpec` (continuous `c, v-c, M-v`
values), the merchant/seller history, per-round active strategy (crucial
for the adaptive notebooks!), and the full `seller_config` including the
active switching-rule thresholds.

## Usage

1. Drop `exp_runner_0418.py` and `run_all_0418.py` next to the 12 notebooks
   in the same folder layout as your 0416b project.
2. Edit `CLIENT = OpenAI(api_key=...)` in each notebook.
3. Run all 12 notebooks in parallel. Wall-clock ≈ 10.4 h.

The runner is resumable: re-executing a notebook skips runs whose JSON
already exists, so a crashed notebook can be re-started without redoing
work.
