# Recorded adaptive-migration results

These results belong only to the separate adaptive-migration series. They are not
pooled with earlier probes and do not change their findings.

## What was compared

Each runner executed two fresh-stack histories in balanced order. Both histories
received simultaneous checkout and advertising workloads. The adaptive history
transferred 0.04 configured CPU at a time from checkout, payment or shipping to
advertising, provided the preceding checkout window was safe and measured
advertising CPU throttling showed binding demand. The control kept the initial
allocation and performed sham updates with the same workload and epoch timings.

Unlike a sweep of independent static points, allocations and the running system
persisted throughout each history. The competing objectives were measured
advertising output and acceptable checkout performance. Advertising output is
successful nonempty responses per second, not revenue or an observed human goal.
The CPU ceilings form an administrative budget, not a reserved physical core.

## Observations

| Observation | Result |
| --- | --- |
| Planned / retained paired runners | 20 / 19 |
| Retained pairs with initially valid, safe baselines and valid histories | 19 / 19 |
| Adaptive histories with an observed SLO crossing | 19 / 19 retained |
| Unchanged control histories with an unsafe epoch | 0 / 19 retained |
| Crossing epoch counts | step 8: 1; step 10: 6; step 11: 5; step 13: 7 |
| Common measured epochs | 214, all technically valid |
| Adaptive moves increasing / decreasing / leaving advertising goodput unchanged | 198 / 16 / 0 |
| Recorded system-failure measurement windows | 0 |

All crossings were latency violations: request p95 exceeded 500 ms; error rates
at crossing ranged from 0 to 0.0833%, below the 1% error boundary. The SLO label
was not assigned from allocation, balance, restart or OOM information.

At each adaptive history's first crossing, the matched control remained safe:

| Measurement at the crossing epoch | Median | Range |
| --- | ---: | ---: |
| Adaptive checkout p95 (ms) | 648.51 | 512.58--984.67 |
| Matched control checkout p95 (ms) | 106.05 | 80.67--122.90 |
| Adaptive advertising goodput (responses/s) | 1973.38 | 1449.58--4556.05 |
| Matched control advertising goodput (responses/s) | 303.08 | 261.43--511.02 |
| Adaptive minus control goodput changes from their respective baselines (responses/s) | 1718.11 | 1166.14--4036.71 |

The last contrast accounts for output changes also observed under the unchanged
allocation, including warmup. It was positive in all 19 crossing pairs. Crossing
epochs are selected by the observed adaptive outcome: these are descriptive
matched contrasts, not a preselected fixed-time causal effect. Individual moves
were not guaranteed to improve output; the 16 negative changes remain visible.

## Interpretation

A separate [retrospective step-6 analysis](history-v0.1.0/README.md) now
compares both baseline-relative goodput and p95 changes with control, before
the SLO crossing. All 19 pairs were still safe; both contrasts were positive.
Its [per-pair inputs](history-v0.1.0/step6-pairs.csv) and
[full-coordinate history](history-v0.1.0/ilr-history.csv) are versioned post-run
outputs, not a change to the frozen experiment.

The constructed runtime mechanism occurred: measured output pressure motivated
successive reallocations while checkout was still acceptable at each decision;
the recipient's measured output increased, and checkout eventually crossed its
externally measured boundary. Unchanged controls with the same competing load
remained safe. This supplies the adaptation-and-migration evidence absent from a
static threshold comparison. It does not validate human behavior, production
prevalence, or the entire socio-technical model.

A balance records cumulative relative redistribution along these histories.
This result does not establish that a balance detects crossings better than
local or combined quota thresholds. A component threshold can encode the same
crossing along a single monotone path. No warning cutoff was fitted and no
detector accuracy or binary scientific pass criterion is reported.

## Missing runner and execution provenance

- Design version: `adaptive-migration-0.1.0`.
- Execution commit: `2ef95678d96df210bfa7694be12d5f08c1890c9f`.
- Actions run identifier: `38076702646`.
- Workflow: [migration.yml](../../.github/workflows/migration.yml).
- Missing block: `migration-006`; job identifier `114286399871`.
- Provider diagnostic: the hosted runner lost communication with the server.
  The diagnostic mentions possible runner termination, resource starvation or
  network loss; the actual cause cannot be established without the lost data.
- No artifact or reconstructable primary outcome was available for that block.
  It was not assigned safe/unsafe, silently excluded from a complete-campaign
  denominator, or replaced. Its outcome remains unknown.
- The run concluded with failure and the aggregate completeness assertion failed.
  The compact summary correctly records `status: incomplete` and 19/20 receipt.
  This is a missing-data/completeness failure, not evidence that a scientific
  crossing criterion failed. There is no such binary criterion in the design.

The 19/19 observation is conditional on retained pairs, not an estimate of
reliability across all environments. Including the unknown planned pair,
19/20 have an observed adaptive crossing with a safe matched control and 1/20
has unknown outcomes.

## Files and verification

- [summary.json](summary.json): planned and received counts, missing block,
  per-history validity, stopping reasons, gains/losses and crossing contrasts.
- [trajectory-level.csv](trajectory-level.csv): every retained baseline and epoch,
  both measured objectives, SLO labels, quotas and allocation coordinates.
- [paired-epochs.csv](paired-epochs.csv): every common epoch's matched contrasts.
- [RESULTS.md](RESULTS.md): unmodified execution-generated aggregate.

After download, all 594 trajectory rows and 214 matched rows were independently
checked for SLO labels, output-counter normalization, positive closed allocations,
donor sequence, preceding safe state and recipient pressure, recorded output
changes and baseline-normalized contrasts. All checks passed. The full execution
artifacts include native primary data, effective-quota checks, resource samples
and container events; these compact files do not replace those raw artifacts.
