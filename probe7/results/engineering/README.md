# Technical feasibility, separate from main observations

These observations commission instrumentation and resource eligibility. They
are not pooled into any main estimate or used as main replications. Each trial
returns to the same allocation; resource order is reversed across two fresh
runners, at 24 and 40 checkout operations/s respectively. Advertising uses
eight closed-loop VUs.

## First attempt: v0.1.0

Execution identifier: 38458668550; implementation b75dba696b49c2c83cfaedd9a926e00f1bfa3c07.
The [first runner](first-pilot-01.json) passed warmup but the advertising process
restarted during baseline. Its unavailable-PID resource frame exposed a parser
error. Primary files were retained; this is not a completed main history.
The [second runner](first-pilot-02.json) completed all four trials and restores.
The cause of the advertising restart was not established: a restart is not
proof of OOM. No outcome is recoded merely because a process restarted.

The revised engineering setup raised the advertising reserve from 384 to
512 MiB, lengthened warmup from 60 to 120 seconds, tolerated missing diagnostic
frames, recorded container events and bounded failed-RPC retries. Requirements
and image digests were not changed to make failures disappear.

## Revised attempt: v0.1.1

Execution identifier: 38461125667; implementation ddfe9184d3ab1fb996e89d09085ddff198d21864.
Both [runner 1](revised-pilot-01.json) and [runner 2](revised-pilot-02.json)
completed baseline and four trial/restore windows. All ten windows were
measurement-valid and met all three external requirements. Warmup is not one
of these ten evaluation windows.

| Checkout load | Window | Advertising goodput (responses/s) |
| --- | --- | ---: |
| 24/s | Baseline | 677.6 |
| 24/s | CPU +0.08 | 1053.2 |
| 24/s | Restore | 738.7 |
| 24/s | RAM +64 MiB | 795.6 |
| 24/s | Restore | 792.3 |
| 40/s | Baseline | 586.5 |
| 40/s | RAM +64 MiB | 743.7 |
| 40/s | Restore | 786.7 |
| 40/s | CPU +0.08 | 1058.2 |
| 40/s | Restore | 792.4 |

CPU trial goodput exceeded the average of its adjacent baseline/restore windows
by about 48.7% and 34.0%. CPU throttling supplied an independent receiver-demand
signal. These are commissioning observations, not population effect estimates.

The RAM trial was only about 4.0% and 8.3% above adjacent-window averages,
respectively; restoring the original memory ceiling did not undo the apparent
improvement. Time/JVM warmup remains a plausible explanation. Observed memory
peaks stayed below 80% of the 512-MiB baseline ceiling, and the image has a fixed
200-MiB JVM heap ceiling. A useful RAM transfer was not established.

Decision made before main execution: retain all eleven CPU and RAM allocations
in the state description, use three different initial CPU/RAM contexts, and
permit only CPU transfers. Do not claim a jointly moving CPU/RAM experiment.
The finalized main/runtime inputs are v0.2.0. No arbitrary scientific pass rate
or deliberate SLO violation is introduced.

The linked JSON files preserve recorded block-level observations and failures.
Native generator streams and order/commit joins are separate execution artifacts,
not reconstructed by those compact records.
