# Bounded CPU/memory adaptation follow-up

This is the active joint-resource follow-up. The original v0.1.0 engineering
execution and the nine-condition RAM calibration remain immutable and separate.
Neither is pooled with the new observations. The earlier campaign never started
because its memory ceiling did not bind. The calibration subsequently observed
safe outcomes with memory-cap events at 32/28 MiB and unsafe outcomes at 24/20 MiB,
each from one runner. These are engineering observations, not certified limits.

## Fixed paths

Twenty fresh GitHub runners each execute four fresh-stack sequential histories:
control, CPU-only, RAM-only and joint. The deterministic order is position-balanced:
each history occupies each position in exactly five blocks. There are no extra
engineering waves, automatic replacements, extensions or parameter search.

All histories begin at checkout/payment/shipping 0.30 CPU each and advertising
0.10 CPU. After the pinned stack starts at its unchanged 256/512-MiB memory
ceilings, apply the common checkout 48-MiB / advertising 720-MiB baseline, warm
up for 60 seconds and measure the baseline for 90 seconds. An invalid or unsafe
baseline prevents adaptations in that history, not replacement of its block.

Each CPU transfer is 0.03; each RAM transfer is 4 MiB. In the joint history:

| Step | Checkout CPU | Checkout RAM MiB |
| --- | ---: | ---: |
| Baseline | 0.30 | 48 |
| 1 | 0.27 | 44 |
| 2 | 0.24 | 40 |
| 3 | 0.21 | 36 |
| 4 | 0.18 | 32 |
| 5 | 0.15 | 28 |
| 6 | 0.12 | 24 |

CPU-only follows the CPU column with RAM held at 48 MiB. RAM-only follows the
RAM column with CPU held at 0.30. The control performs unchanged sham updates.
Both closed configured budgets are preserved separately: 1 CPU over four
services and 768 MiB over checkout/advertising. These are ceilings, not physical
reservations. CPU and RAM are never summed into one composition. Log-ratio
coordinates are recorded separately for the two allocations.

The six-step schedule was fixed after engineering observations: 48 MiB provided
headroom; 32/28 MiB bound without violating the SLO; 24 MiB caused errors. The
earlier CPU-only path first violated the SLO at 0.12 CPU after remaining safe at
0.14 CPU. Six 0.03-CPU moves traverse that region alongside the RAM path. These
choices do not guarantee a joint-only contrast, and this follow-up is exploratory.
Execution identifiers and commits are recorded in the new design provenance.

## Adaptation and outcomes

Checkout load stays 40 scheduled operations/s; generator capacity stays 800 VUs.
Advertising uses 8 VUs against the pinned native RPC. Workloads, images, source,
application settings including GOMEMLIMIT, restart policy and other services are
unchanged. Each measured adaptation has 15 seconds of stabilization followed by
a 60-second measurement.

An adaptive history transfers only while the preceding external checkout SLO is
safe, instrumentation is valid and advertising CPU throttling is positive. It
stops after its first valid unsafe epoch, absent/unobserved recipient pressure,
a technical failure or six steps. Advertising goodput is the observed reward;
all negative and zero changes remain. Extra RAM is not presumed useful to a
CPU-limited advertising service. This is an output-pressure-motivated transfer
heuristic, not an optimizer or evidence that a real operator made the decision.
Control performs all six sham epochs unless instrumentation fails.

A joint-context witness is a matched, valid within-block step where control,
CPU-only and RAM-only are safe while joint is unsafe. Each of their baselines
must be valid and initially safe. Report all other observed patterns, missing
steps and invalid observations too. Later steps after stopping are never imputed.
Equal step index does not equalize queue state or remove sequential-history effects.

Safe means checkout request p95 <= 500 ms and unsuccessful scheduled iterations
< 1%, exclusively from external measurements. Restart/OOM is diagnostic, not a
label override or exclusion. All update commands are journaled and both sides
are attempted even after a client error. Actual persisted/live CPU, RAM and swap
limits determine manipulation validity before and after measurement; swap is
disabled. Cgroup counter differences require matching identities. Lost primary
data, stable-live instrumentation failure or resource mismatch are technical
failures; retain every readable outcome and never replace based on its value.

The fraction of witnessed blocks and its exact interval are descriptive for
these bounded paths, not predictive accuracy or reliability. No majority
criterion, arbitrary statistical null or scientific pass/fail proportion exists.
A witness supports joint-context-dependent safety of these adaptations. It does
not establish a simplicial complex, downward closure, a balance-only detector,
or superiority over ordinary multivariate rules. A zero-witness execution is a
readable negative result, not grounds for silently tuning and rerunning.

## Execution and evidence

Run `joint-cpu-memory-followup` with the exact commit as `expected_sha`. Lightweight
verification precedes the fixed twenty-job matrix. Each job has a 100-minute
timeout; a full four-history schedule contains 40 minutes of warmup/baseline/
stabilization/measurement, plus stack startup and artifact collection. Real
workloads run only in Actions. Locally:

```bash
python -B -m unittest discover -s probe6/tests -v
python -B probe6/scripts/bounded_resources.py verify
```

The new inputs are `design-v0.2.0.json` and `runtime-v0.2.0.json`; execution and
analysis use separate scripts. Previously executed inputs and scripts are not
modified. Preserve rendered Compose, image inspections, update journals,
effective limits, raw primary observations, container events and resource samples.
Raw artifacts last 14 days; compact artifacts last 90 days. Archive before expiry.
The compact summary also contains the complete block records so its descriptive
analysis can be recomputed without relying on expiring raw-stream artifacts.
