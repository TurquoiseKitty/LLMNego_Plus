# Selection notes for the 12 prompt strategies

The uploaded paper argues that prompted seller behavior is often specified as
an implicit strategic style or persona rather than as an explicit update rule.
Table 1 in Appendix A lists representative prompt patterns used in recent
negotiation work.

For this package, the target experiment is narrower than the full survey:
- the seller has **no time-pressure constraint** in its prompt,
- the buyer is an **automatic pricing script** rather than a rich agent,
- the goal is to study **seller price-proposal patterns**, not social influence
  on the buyer.

## Included

These 12 were selected because they span distinct pricing logics:

1. `fu_high_price_brief_anchor`
   - persistent high anchor + brief replies
2. `deng_patient_rational_extractor`
   - patient, rational surplus extraction
3. `vaccaro_warm_high_dominance`
   - warm tone but dominant pricing / ignore first offer
4. `liu_mental_model_tactician`
   - explicit internal opponent-modeling and tactic selection
5. `chatterjee_aggressive_high_ask`
   - aggressive probing with repeated high asks
6. `chatterjee_fair_midpoint`
   - midpoint-seeking closure
7. `chatterjee_passive_gradual`
   - small-step gradual concessions
8. `kong_stochastic_sampler`
   - irregular / sampled counteroffers
9. `kwon_competitive_reactive_guard`
   - aggressive early offers + no-concession response to weak buyer movement
10. `mangla_mirroring_responder`
   - proportional reaction to the buyer's last move
11. `mazur_grim_trigger_punisher`
   - permanent punishment after one off-limits lowball
12. `mazur_corridor_keeper`
   - corridor-based stability with punishment outside range

## Excluded

These were left out because they were less aligned with the current setup or
were too redundant with stronger included variants:

- `Bianchi et al. [protocol]`
  - mostly about prompt structure / capped proposals rather than seller pricing logic
- `Jeon and Suh [competitive]`
  - generic persona family; overlaps with stronger aggressive / dominant variants already kept
- `Vaccaro et al. [warm-lowdom]`
  - primarily rapport-oriented; less central when the buyer is a script
- `Liu et al. [BEG]`
  - emotionally distinctive, but more about language than a stable pricing rule
- `Kwon et al. [RC/LGR/MGF]`
  - logrolling / mutual-gain ideas are less informative in a single-price negotiation
- `Oh et al. [OAR]`
  - close in spirit to the stronger included mental-model prompt
