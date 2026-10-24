# Reduced log-odds consistency check

Two causal histories, `q_catalog=log(R_catalog/F_catalog)` and
`q_currency=log(R_currency/F_currency)`, reproduce every policy orientation and
first constraint of the complete-state calculation: **238 comparisons, zero
disagreements**, over eight histories and both latest/smoothed directions.

The [definition](../../../../reduced-log-odds-v0.1.0.json) fixes the common
availability mask, `alpha=0.2`, repeated-window handling and resets after gaps.
Counts are independently reconstructed from request events. Both methods use
the same effective limits and semantic group knowledge.

For each group, the policy is `q_g <= log(rho_g/(1-rho_g))`. Under the same
proportional continuation, the sign of `delta_q_g` gives orientation and the
smallest nonnegative contact parameter identifies the first constraint.
This equivalence is expected mathematically and observed in the replay.

The complete state has an additional between-group coordinate. Its norm is
needed for full-state Aitchison distance, but not these policy orientations or
the identity of the first boundary. A parameter obtained from only two
unnormalized log-odds increments is not reported as that full-state distance.

The comparison deliberately uses the complete-state availability mask; it
does not claim that reduced ratios require all four positive parts in every
possible deployment. Missingness counts in [the summary](summary.json) count
both direction estimates. [Every comparison](comparisons.json) remains available.

```sh
python -B evolving-state/scripts/reduced.py --output artifacts/reduced-log-odds
```

This is retrospective saved-data verification and starts no workload. It adds
an executable check of the simpler baseline, not a new benefit claim.
