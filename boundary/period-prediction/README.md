# Does CPU period explain optimistic latency prediction?

This separate follow-up adds **actual frozen predictions** to the earlier
[period intervention](../diagnostic/README.md). Two observed delays are not a
prediction error: prediction error requires a forecast made before measurement.

It also checks a competing explanation: **can independent calibration of the
same formula at each CPU period absorb the period effect into its coefficients?**
The formula is not changed and no empirical delay correction is introduced.

## One paired runner block

The [fixed design](design-v0.1.0.json) gives each of four hosted runners:

1. Ten fresh-stack calibrations: checkout CPU 0.30, 0.22, 0.16, 0.12 and 0.08,
   each at checkout CPU periods 100 ms and 20 ms. A hash-fixed interleaved order
   avoids always putting one period first. Each has 180 seconds warmup and one
   60-second measured cohort, containing about 2,400 checkout starts.
2. Two independent fits of the existing shifted M/M/1 p95 surrogate, using the
   unchanged parameter grid, loss, censoring and error guard. Each fit sees
   only calibration data from its own period. There is no model selection.
3. One common physical test quota: the smallest executable 0.001-CPU quota
   permitted by the 100-ms model at the experimental 500-ms limit, bounded
   below by 0.08. If that model abstains, the predeclared diagnostic quota is
   0.14 and the absence of a recommendation remains explicit. The short-period
   calibration cannot influence target selection.
4. Both models, calibration hashes, target and predictions are uploaded before
   either test. Then two fresh-stack static tests use that same quota, one at
   each period, with 180 seconds warmup and two 60-second measured cohorts.
   Test order is counterbalanced across runners. No parameters are updated.

The [workflow](../../.github/workflows/period-model-prediction.yml) runs the four
blocks in parallel. Offered load is 50 minutes per block, plus image pulls,
startup, reset and archival. Expect roughly 60--75 minutes; the job cap is
120 minutes. Runtime execution is restricted to disposable GitHub-hosted
runners. Local work consists only of lightweight tests and saved-data analysis.

## Unchanged controls

Workload: 40 checkout operations/s and 100 advertising requests/s, fixed VUs,
pinned images/actions and unchanged timeout and unsuccessful-operation rules.
Checkout+advertising CPU ceilings remain 0.70; all eleven selected ceilings sum
to 3.4 CPU. Other CPU periods remain 100 ms. RAM ceilings remain fixed. There
is no external background load. Bring the fresh stack to health without CPU
ceilings, apply exact integer working limits, then start offered-load warmup.

20 ms supports the entire existing quota range: 0.08 CPU gives 1,600 us per
period. At 10 ms it would give 800 us, below the 1,000-us minimum described in
the [kernel bandwidth documentation](https://docs.kernel.org/scheduler/sched-bwc.html).
Requested and actual CPU quota/period and RAM/swap limits are recorded and
checked. Sample all running containers and host pressure/CPU components.

The experimental checkout policy remains p95 <=500 ms and unsuccessful
operations <1%; it is not an upstream or customer SLO. OOM/restarts are retained
diagnostics, not exclusions or forced SLO labels. Timeout quantiles remain
lower bounds. Rerun only infrastructure-failed whole blocks, with no splicing
of calibration and test attempts or replacement of unfavorable outcomes.

## Four comparisons, not just a faster response

| Frozen model calibrated at | New test at 100 ms | New test at 20 ms |
| --- | --- | --- |
| 100 ms | Matching-period prediction error | Same forecast under changed period |
| 20 ms | Cross-period prediction error | Matching-period prediction error |

For both matching-period cells report **measured p95 minus predicted p95**.
Positive error is optimism. Also report absolute and absolute log error:
switching from substantial underprediction to still larger overprediction is
not improved accuracy. Compare the period shift predicted by the two fits
with the observed shift. One unchanged forecast evaluated at two periods has
an error difference algebraically equal to the observed latency difference;
that difference alone is not a new accuracy result.

The aggregate job replays raw operations, independently refits calibration
to verify the frozen models and verifies that targets/predictions have not
changed. Both measured test cohorts are pooled at the request level for
session p95; their individual windows remain available. Throttled CPU duration
is also normalized by elapsed wall time, because changing period changes the
denominator of period-frequency counters. Aggregate throttling is not a wall
time percentage and can include parallel throttled entities.

There is no arbitrary campaign success frequency or significance claim from
four runners. Static tests do not validate predictions during a descending
adaptation path and do not identify the cause of every earlier residual.
This campaign uses one calibration window per quota, unlike the earlier
two-window campaign, and is never pooled with it.

## Outputs

- `sessions.csv`: all 48 calibration/test sessions and execution diagnostics.
- `windows.csv`: both streams, warmup and measured cohorts.
- `prediction-errors.csv`: all four model/test combinations per runner.
- `paired-errors.csv`: matched-period errors and predicted/observed shifts.
- `summary.json`, `RESULTS.md`: completeness, measurements and limits.
- Frozen-model artifacts are separate from raw blocks and are uploaded before
  test execution. Raw blocks retain request records, resource samples,
  executable configurations, quota checks, host/image context and failure events.

```sh
python -B -m unittest discover -s boundary/period-prediction/tests -v
python -B boundary/period-prediction/scripts/period_run.py matrix
```
