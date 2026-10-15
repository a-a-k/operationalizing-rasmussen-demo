# Fixed-load static CPU calibration: interpretation

The experiment observed a coarse, repeatable separation on its tested grid:
checkout was SLO-safe at 0.16 CPU and above in all three runners per quota,
and unsafe at 0.08 CPU in all three runners. At 0.12 CPU, two runners stayed
safe and one stayed unsafe. This supports a useful transition region under
the controlled load, not an exact universal CPU boundary.

## What was compared

Eighteen fresh-runner trials covered six checkout CPU quotas and three
repetitions. The ad quota absorbed the difference, keeping the eleven-part
configured CPU sum at 3.4 cores. All other CPU quotas and all RAM ceilings
remained fixed. Each trial used a continuous 40 order operations/s and
100 ad requests/s, with 180 seconds of warmup followed by three 60-second
measurement windows. There was no adaptation or quota change under load.

All 18 trials completed on their first attempt. All 54 post-warmup checkout
windows delivered exactly 40 operations/s; all 54 advertising windows delivered
exactly 100 requests/s. Neither stream dropped an iteration or left an
operation unfinished after graceful stop. A completed timeout is still a
failed operation, not a successful or unfinished one. All advertising attempts
in the measured windows were successful within the 200-ms deadline.

## Observed outcomes

One runner, not one window, is the independent repetition. Each runner retained
the same SLO label across its three measured windows. These are three minutes
of observation after fixed warmup, not proof of an asymptotic steady state.

| Checkout CPU | Runners safe in all 3 windows | Runners unsafe in all 3 windows | p95 range across all 9 windows (ms) |
|---|---:|---:|---:|
| 0.45 | 3/3 | 0/3 | 95–128 |
| 0.30 | 3/3 | 0/3 | 108–327 |
| 0.22 | 3/3 | 0/3 | 159–196 |
| 0.16 | 3/3 | 0/3 | 282–410 |
| 0.12 | 2/3 | 1/3 | 279–669 |
| 0.08 | 0/3 | 3/3 | 598–5,002 |

At 0.08 CPU, two runners reached repeated five-second checkout timeouts with
100% unsuccessful operations in their measured windows. The third completed
operations successfully, but its p95 remained above 500 ms. The unsafe label
therefore does not depend exclusively on the timeout cases.

At 0.12 CPU, the three runners' last-window p95 values were approximately
668, 481 and 279 ms. A quota-only point estimate cannot reproduce all three
sampled outcomes. Hosted runners had different processor models, but this
does not establish the cause of variability; even the same processor model
does not identify identical effective performance or execution state.

One diagnostic matters: the ad container in `cpu-300-r3` was OOM-killed about
74 seconds into the 180-second warmup and restarted once. Its checkout warmup
windows were degraded; all three measured checkout windows were safe, with
p95 falling from 327 to 266 to 232 ms. The trial is retained, not replaced.
No container failure events occurred in any post-warmup measurement period,
and the 0.08/0.12/0.16-CPU trials had no such failure events under load.
The declining latency also illustrates why fixed warmup is not proof of
equilibration, even when the subsequent SLO label remains unchanged.

The separate trials do not form a longitudinal trajectory. Repetition ID 1
at one quota is not the same host or system history as repetition ID 1 at
another quota. No paired causal estimate across these separate hosts is implied.

## What can be concluded

The tested endpoints 0.08 and 0.16 CPU give an observed transition bracket;
0.12 CPU lies in a mixed-outcome region across runners. This is a descriptive
bracket on a coarse grid, not a confidence interval or a guaranteed safe quota.
It justifies a small next test of a model or a transfer into these allocations.

This experiment has not fitted or validated a queueing model, calculated a
reliable number of remaining adaptation steps, or compared CoDA with another
representation. It also does not establish recipient benefit: the offered ad
load was deliberately fixed and all measured ad requests met their deadline.
That controlled condition isolates this calibration from earlier closed-loop
advertising campaigns; their numerical boundaries cannot be substituted here.

The next distinct question is whether arrival at the same allocation from
different prior allocations changes the subsequent outcome. Static separation
alone does not validate boundary calculations during adaptation.

## Evidence

- [All windows, including warmup](evaluation/windows.csv)
- [All eighteen runner outcomes](evaluation/trials.csv)
- [Quota-level descriptive summary](evaluation/quotas.csv)
- [Machine-readable aggregate and attempts](evaluation/summary.json)
- [Primary start/finish records and runtime context](evidence/)
- [Container-failure diagnostics](diagnostics.json)
- [Checksums of retained evidence](evidence-sha256.json)

Aggregation recomputes every window from retained primary events. Raw k6 metric
streams, generator logs, complete container logs, rendered Compose and image
inspection are additionally preserved in the runtime artifacts and the local
download. Runtime artifacts expire after 90 days; the evidence above is retained
in this repository. No failed trials, adverse windows or repeated attempts
were removed.
