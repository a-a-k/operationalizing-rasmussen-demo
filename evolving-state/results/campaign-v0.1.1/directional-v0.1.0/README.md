# Conditional directional diagnosis, version 0.1.0

## Outcome in plain language

The saved histories support an additional diagnostic beyond checking whether
the current retry policy is satisfied: **which constraints the measured motion
approaches, and where continuing that direction would leave the current
admissible region**.

The calculation was implemented for both the latest increment and its existing
EWMA. All 119 available report-level calculations for each direction agreed
with an independent calculation on the original parts. No new workload ran,
and the original online observer, policies and recorded histories were not changed.
This is a retrospective functional and numerical verification, not a new
confirmation campaign or a test of future violation prediction.

## What was calculated

Let `n = (F_catalog, R_catalog, F_currency, R_currency)` contain the four
positive attempt counts, `x = n/sum(n)`, and `z = ilr(x)`. The existing observer
retained both `v = z_t-z_(t-1)` and its EWMA with `alpha=0.2`.
They are evaluated separately, not selected according to which gives a preferred result.

For nonzero `v`, normalize it to `d = v/||v||` and continue the ray

```text
z(s) = z + s*d,  s >= 0
x(s) = inverse_ilr(z(s)).
```

The parameter `s` is **Aitchison distance along this ray**, not seconds,
observation cycles, requests, or an amount of resource that can safely be removed.
Normalizing `v` separates direction from measured speed. The unnormalized
velocity norm is retained in every report.

The policy for each group is `R/(F+R) <= rho`, equivalently
`log(R/F) <= log(rho/(1-rho))`. Both policies effective at the current report
are held fixed for this conditional calculation.

If `a_g` is the ILR normal for `log(R_g/F_g)`, the signed directional
projection is `a_g dot d`. Positive means toward increasing retry fraction;
negative means decreasing fraction; zero means tangent to this constraint.
For a currently satisfied constraint with positive projection,

```text
s_g = max(0, log(rho_g/(1-rho_g)) - a_g dot z) / (a_g dot d).
s_first = min of the finite s_g values.
```

All tied first constraints are reported. Per-constraint signed perpendicular
distance, `gap/sqrt(2)`, is also retained and is distinct from distance along
the chosen ray.

An already violated policy is reported as a current violation with zero
remaining admissible distance, not a forecast of a later first crossing.
On a boundary, outward motion exits immediately; inward or tangent motion
does not exit that constraint along the positive ray.
`no_forward_crossing` means no exit at finite distance along this particular
fixed-policy ray. Its null distance represents infinity, not missingness or
permanent safety. `stationary` is a separate status.

## Independent check

The analytic calculation uses the recorded ILR state and directions.
The verifier instead:

1. Recounts individual request events by logical operation, without the
   observer's component-to-group mapping.
2. Computes centered logarithms of those original counts and their increments
   and EWMA without applying an ILR transform.
3. Normalizes that velocity and continues the parts multiplicatively,
   `x_i(s) proportional to n_i*exp(s*w_i)`.
4. Finds each policy crossing by bracketing and bisection of the direct
   `R/(F+R)` expression, without the analytic crossing formula.
5. Compares orientations, first constraints, distances, and intersection
   compositions. Actual applied policy versions come from configuration events.

This is the **same physical path in two representations**. A linear
extrapolation of raw retry fractions would be a different continuation model,
not an independent computation of this path.

Absolute and relative comparison tolerances are `1e-9`; the numerical
zero/direction tolerance is `1e-12`. The largest observed absolute difference
in crossing distance was **5.60e-14**; the largest difference in intersection
composition was **3.69e-15**. All 238 available direction/report checks passed.
These are numerical agreement results, not prediction errors against future execution.

The unit tests additionally cover analytic examples, two constraints and ties,
boundary contact, outward/inward motion, stationary states, current violations,
positive scaling, 300 seeded random paths, missingness, repeated windows and
complete archived replay. Input hashes bind the analysis to the original data.

## Coverage and all-history results

There are eight runner histories and 181 emitted report batches. Reports can
repeat a completed measurement window when its policy or metadata changes;
they are not independent replications or 181 distinct measurement windows.

| Coverage | Report batches |
|---|---:|
| Complete positive composition | 135 |
| Direction and policies available | 119 |
| Direction available and both policies currently satisfied | 85 |
| Direction available but at least one policy already violated | 34 |
| Missing component lineage | 16 |
| Zero parts | 30 |
| Positive composition but no adjacent comparable direction | 16 |

No pseudocount, retrospective interpolation, or smoothing across a gap was
introduced. Re-emitting the same window retains rather than refilters its
direction. A restored state does not immediately restore a lost movement history.

Among the **85 currently admissible reports**:

| Conditional result | Latest increment | Smoothed increment |
|---|---:|---:|
| Finite forward exit | 51 | 52 |
| No finite forward exit | 34 | 33 |
| Catalog first | 19 | 24 |
| Currency first | 31 | 28 |
| Both tied first | 1 | 0 |

The three named-constraint rows partition finite exits, not all admissible reports.
The two direction estimates gave the same first constraint in 34 finite-exit
reports and different first-constraint sets in 13. Five reports had an exit
only for the smoothed direction; four only for the latest increment; 29 for neither.
This is a sensitivity description, not evidence that either direction predicts better.

Across all 238 available group/report combinations, the latest and smoothed
directions differed in 48, with strictly opposite signs in 43. The other five
were tangent-versus-nontangent differences. Smoothing must not be presented as
the latest observed motion: its memory can preserve an earlier direction.
These counts do not establish that each difference was an actual persistent reversal.

## Same local state, different motion

Exhaustive matching found **30 pairs** with exactly equal local `F`, `R` and
`rho`, but opposite last-increment directions. In **26 pairs**, both policies
were satisfied in both observations. These pairs overlap and are not independent
replications. They match one group's state, not the complete four-part composition.
All pairs, including the four outside that joint-admissibility subset, are retained.

The previously identified example remains a retrospective illustration:

| Catalog diagnostic | history-01, window 10, policy 4 | history-03, window 14, policy 4 |
|---|---:|---:|
| First attempts / retries | 100 / 20 | 100 / 20 |
| Current retry fraction | 16.67% | 16.67% |
| Current allowed fraction | 50% | 50% |
| Previous-window retry fraction | 35.48% | 15.25% |
| Latest catalog motion | Away | Toward |
| First forward policy exit | None | Catalog |
| Distance along the latest direction | No finite exit | 1.393814 |

Both directions give the same qualitative contrast. The second history's
smoothed direction was restarted after a metadata gap; its agreement here is
not independent evidence of a long persistent trend. In the first history both
groups move away; in the second, currency is tangent.

The additional answer is not simply "the policy is satisfied." It distinguishes
decreasing from increasing retry pressure and identifies the constraint reached
by the stated continuation. The current local slice alone cannot recover that
history; a direct observer supplied with the same history can.

## Moving the policy without moving the observed point

All **13** same-window policy-only comparisons retain the same measured
directions. Five change the current policy-satisfaction status, as in the
original analysis. Four other comparisons shorten an existing finite forward
distance while both the old and new current states remain admissible.

For example, `history-03`, window 14, report 15 to 16 changes policy 4 to 5.
The catalog limit changes from 50% to 20%; counts, composition and direction
are unchanged. The conditional distance falls from **1.393814 to 0.193248**.
The current ratio, 16.67%, still satisfies both limits.
This is a changed boundary, not movement of the observed state.

## Interpretation and limits

The implemented readout links current state, measured motion and versioned
constraints, while retaining the original component-continuity and availability
checks. It adds an executable diagnostic to the current-policy table.

The updated direct calculation agrees even with multiple constraints.
This analysis therefore does not establish uniquely better CoDA policy detection.
It checks a coherent relative continuation and its interpretation, rather than
requiring a direct comparator to discard history or use a different path.

The boundaries are explicit retry policies, not validated physical failure
surfaces. Future policy changes and changes of direction can invalidate the
conditional continuation. Neither time-to-violation accuracy nor operator
benefit was measured. All data were already inspected; no confirmatory
significance test or reliability claim is attached to the descriptive counts.

## Reproduce and inspect

- [Analysis definition](../../../directional-design-v0.1.0.json).
- [All report-level calculations and independent checks](reports.json).
- [Aggregate and per-history results, examples and policy-only changes](summary.json).
- [Every matched local-state pair](matched-local-states.json).
- [Input and definition hashes](provenance.json).
- [Original runtime results and primary inputs](../README.md).

From the repository root, without starting containers:

```sh
python -B evolving-state/scripts/directional.py --output artifacts/directional-replay
python -B -m unittest discover -s evolving-state/tests -p test_directional.py -v
```

The tests compare numerical outputs with the declared tolerance to accommodate
platform-level floating-point differences; primary input hashes must match exactly.
