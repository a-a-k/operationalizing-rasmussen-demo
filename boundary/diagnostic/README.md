# CPU context diagnostic

A separate small intervention asks **why a fixed-quota performance curve can
underpredict checkout latency**. It does not change or rerun the frozen boundary
prediction campaigns and does not fit a replacement model.

## What changes

Checkout retains **0.14 CPU** and advertising **0.56 CPU** in every condition;
all eleven selected service ceilings still sum to **3.4 CPU**. RAM ceilings and
the controlled 40/s checkout and 100/s advertising workloads are unchanged.
The experimental checkout requirement remains p95 <=500 ms and errors <1%.
This is an experimental policy, not an upstream or customer SLO.

| Condition | Checkout period | CPU time per period | External background |
| --- | ---: | ---: | --- |
| long-idle | 100 ms | 14 ms | Sleeping shell |
| short-idle | 10 ms | 1.4 ms | Sleeping shell |
| long-busy | 100 ms | 14 ms | Busy shell, limited to 0.5 CPU |
| short-busy | 10 ms | 1.4 ms | Busy shell, limited to 0.5 CPU |

The average checkout ceiling is identical. Shortening the period changes how
that allowance is delivered, not its amount. All other service periods remain
100 ms. Docker describes quota/period controls in its
[resource documentation](https://docs.docker.com/engine/containers/resource_constraints/).
Limits are explicit integers in the executable Compose configuration and are
checked against actual `cpu.max`; no NanoCPU conversion or rounding is assumed.

The auxiliary shell uses the existing digest-pinned workload image, no network,
32 MiB RAM and the same 0.5-CPU ceiling in both background conditions. It is
**outside** the SUT allocation: this is an external contention intervention,
not another closed redistribution. Its achieved CPU usage is measured. A
0.5-CPU ceiling does not guarantee that contention exhausts the host, or that
the shell actually consumes that amount on every runner.

## Size and execution

The [design](design-v0.1.0.json) contains four runner blocks. Each executes all
four conditions with a fresh stack and fresh volumes, 180 seconds of warmup
and two 60-second measured start cohorts. The order is counterbalanced: every
condition occupies each position once and every directed adjacent pair occurs
once. No adaptive point selection, outcome-driven stopping or model fitting.

The [workflow](../../.github/workflows/cpu-context-diagnostic.yml) runs the four
blocks in parallel, only on disposable GitHub-hosted runners. Local work is
limited to unit checks. At roughly 20 minutes of offered load per runner plus
startup, pulls and archival, expect approximately 30--45 minutes wall time.
The job cap is 75 minutes. Existing runtime versions, image digests, health
checks, load generator, censoring rules and SLO scoring are reused.

Every completed condition is retained, whether safe or unsafe. SUT restart/OOM
is diagnostic, not an exclusion or an automatic SLO failure. Infrastructure
failures may be rerun with the same design; latest whole-block attempt is used,
with earlier artifacts retained. No individual conditions are spliced together.

## Measurements and interpretation

Raw operation records are independently rescored by the aggregate job. A
session p95 is computed from the **pooled requests** in both measured cohorts,
not by averaging their p95 values. Both original windows are also reported.
All running containers are sampled, including previously unobserved auxiliaries.
Host CPU components (including steal), pressure files, CPU counters, memory,
actual limits, generator activity and container OOM/death events are archived.
Throttled microseconds are aggregate cgroup counters, not a wall-time percentage.

For each runner report four paired latency effects: short minus long period at
each background level, and busy minus idle at each period; also report their
interaction. Report actual load and throttling alongside latency. Censored
quantiles remain lower bounds and have no exact numeric latency contrast.
Four runners are the replication units; minute windows are not extra runners.
All outcomes and telemetry failures remain visible. There is no arbitrary
pass/fail frequency or new inferential claim from four blocks.

A period effect would implicate the delivery schedule of the same CPU ceiling.
A background effect would demonstrate sensitivity to this controlled external
load. Their absence would not rule out all scheduling or contention mechanisms.
Neither result alone establishes the complete cause of earlier model residuals,
a safe future transfer, CoDA superiority or a universal boundary. This campaign
narrows the diagnosis before any proposed model revision.

## Files and lightweight checks

- `sessions.csv`: all sixteen session outcomes, rates, CPU and throttling.
- `windows.csv`: warmup and individual measured windows, both request streams.
- `paired-contrasts.csv`: within-runner effects, with missing/censored pairs explicit.
- `summary.json` and `RESULTS.md`: completeness and descriptive interpretation.
- Per-block raw artifacts: executable Compose, primary operations, raw k6
  output, resource samples, container events, image/host context and readbacks.

```sh
python -B -m unittest discover -s boundary/diagnostic/tests -v
python -B boundary/diagnostic/scripts/diagnostic_run.py matrix
```
