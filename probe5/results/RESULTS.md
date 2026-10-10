# Adaptive boundary migration

The tested mechanism is a reward-seeking sequence under a fixed configured CPU budget, not a static detector contest or a validation of human adaptation.

Received 19/20 paired runners. Missing: ['migration-006'].

| History | Initially valid | Valid histories | Histories with a valid unsafe epoch |
| --- | ---: | ---: | ---: |
| drift | 19 | 19 | 19 |
| control | 19 | 19 | 0 |

## Descriptive contrasts at the first observed drift crossing

These epochs are selected by the observed drift outcome. They are not a fixed-time causal estimand or a pass criterion.

| Runner | Crossing epoch | Matched control safe | Valid pair | Goodput change difference (responses/s) |
| --- | ---: | --- | --- | ---: |
| migration-001 | 11 | True | True | 1588.63 |
| migration-002 | 13 | True | True | 3698.41 |
| migration-003 | 10 | True | True | 1425.51 |
| migration-004 | 13 | True | True | 2413.83 |
| migration-005 | 8 | True | True | 1166.14 |
| migration-007 | 11 | True | True | 1782.14 |
| migration-008 | 11 | True | True | 1996.10 |
| migration-009 | 13 | True | True | 2578.94 |
| migration-010 | 13 | True | True | 2754.51 |
| migration-011 | 10 | True | True | 1462.82 |
| migration-012 | 13 | True | True | 2697.30 |
| migration-013 | 10 | True | True | 1421.54 |
| migration-014 | 11 | True | True | 1594.21 |
| migration-015 | 10 | True | True | 1394.29 |
| migration-016 | 10 | True | True | 1443.97 |
| migration-017 | 10 | True | True | 1563.80 |
| migration-018 | 13 | True | True | 2575.48 |
| migration-019 | 11 | True | True | 1718.11 |
| migration-020 | 13 | True | True | 4036.71 |

## Interpretation

Evidence for the constructed mechanism requires actual recipient output gains and deterioration of checkout relative to the unchanged control. Neither gain nor crossing is assumed. All negative/zero moves, control failures, short histories and invalid measurements remain visible.

A monotone path is not evidence that a balance uniquely detects the crossing: a suitably chosen component threshold can encode that same path. Balance is reported as an interpretable cumulative allocation coordinate; no tuned warning rule, general superiority, monetary benefit or human behavior is claimed.

Full measured trajectories and matched contrasts are in trajectory-level.csv and paired-epochs.csv. Native counters, checkout raw streams, quota checks, container events and cgroup observations are retained in the execution artifacts.
