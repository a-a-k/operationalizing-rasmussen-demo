# Efficiency-driven boundary migration

This series tests a constructed Rasmussen-style mechanism: output pressure motivates
successive reallocations under a fixed resource budget; an operation that remains
acceptable before each decision may eventually cross its performance boundary.
The mapping is explicit and limited:

- Efficiency pressure: continuously backlogged advertising requests and measured
  successful advertising responses per second. This is goodput, not money.
- Operational constraint: four configured CPU ceilings sum to 1 CPU. They do not
  reserve a physical core; other services and both generators share the host.
- Acceptable-performance boundary: externally measured checkout request p95 at
  most 500 ms and unsuccessful scheduled iterations below 1%.
- Local adaptation: when the preceding checkout window is safe and advertising
  was CPU-throttled, transfer 0.04 CPU from the next donor to advertising.
- Migration: allocations and the running system actually persist across decisions.
  The path is measured in time, not reconstructed from independent static points.

## Small fixed execution

Twenty independent GitHub runners each execute two fresh-stack histories: adaptive
redistribution and an unchanged allocation control. Their order is exactly balanced
ten/ten by a fixed hash ordering. Both histories run the same checkout arrival
rate (40/s), advertising concurrency (8 VUs), warmup, baseline and epoch timings.
There are at most 18 round-robin moves from checkout, payment and shipping to ad.
Every measurement window lasts 60 seconds after 15 seconds of stabilization.

The adaptive history stops after the first unsafe checkout outcome, nonbinding
advertising pressure, missing pressure observations, a technical failure, or the
move limit. The control performs all 18 sham-update epochs unless its measurement
infrastructure fails. Unsafe control outcomes remain recorded. A move's realized
output gain can be positive, zero or negative; none is deleted or used to select
which runs enter the evidence. There is no fitted cutoff, success fraction,
replacement campaign, or automatic extension.

Fixed memory reserves are checkout/product-catalog 256 MiB, database 1 GiB and ad
512 MiB. They address observed low-memory baseline failures and provision the
newly loaded recipient. They do not rule out downstream memory failures.
Post-adaptation restart/OOM never overrides the externally measured SLO or excludes
an otherwise readable measurement. Events and cgroup samples remain available.

## What the evidence can establish

The main result is the measured sequence of incentive, decisions, recipient output,
checkout performance and crossing (or its absence), alongside the unchanged control.
Report every epoch and history. For each common epoch, compare goodput changes from
each history's own baseline and checkout latency. Contrasts at the first observed
crossing are descriptive, outcome-selected contrasts, not a fixed-time causal effect.

The risk-group balance is an allocation coordinate contrasting controlled checkout
participants with the advertising recipient. It exposes cumulative relative
redistribution, but does not model unequal service sensitivities or estimate the
distance to an unknown SLO boundary. Each quota and its cumulative loss, group sum,
minimum, reduced count and Euclidean/Aitchison radial displacement are also retained.
Along one monotone path, component thresholds can encode the same crossing as a
balance threshold. This series does not claim unique detection, superior alarm
accuracy, or an independently validated early-warning threshold.

This is a technical analogue of one adaptation mechanism, not an experiment on
human behavior, a reproduction of an entire socio-technical model, an autonomous
production optimizer, or evidence of a natural production incident. It is separate
from all earlier observations; those observations are neither replaced nor pooled.

## Reproduction and artifacts

Run `adaptive-boundary-migration` with the exact commit in `expected_sha` and
`execute=true`. Its initial engineering gate verifies both simultaneous workloads,
an initially safe reference, positive advertising output and measured recipient
CPU-throttling. This gate is outside the scientific replication set.

Locally, run only the lightweight tests:

```bash
python -B -m unittest discover -s probe5/tests -v
python -B probe5/scripts/drift.py verify
```

The execution archives rendered Compose, image inspections, both workload windows,
native advertising aggregate counters, losslessly compressed checkout raw streams,
every effective quota check, container events, segmented resource counters and
short/invalid history results. Advertising per-request traces are not retained;
its primary output is the native counter summary, with in-window completions
explicitly distinguished from the graceful-stop tail. Actual workload-window overlap
is reported. Full artifacts are retained for 14 days and compact results for 90 days;
download them for archival before expiration.

The compact result contains `summary.json`, `trajectory-level.csv`,
`paired-epochs.csv` and `RESULTS.md`. Digest-pinned images, full action SHAs and
the pinned upstream RPC definition are inherited and checked before execution.
