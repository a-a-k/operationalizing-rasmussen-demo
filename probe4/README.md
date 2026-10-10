# Fixed allocation scenarios and threshold comparison

This is a small new descriptive series, separate from all previous observations.
It compares a directed compositional balance with local quota thresholds, the
minimum quota, group sum, reduced-service count, and both radial distances. It
also exhausts combinations of separate local thresholds joined with OR.
No scenario is assigned an expected safe or unsafe outcome.

## Fixed scope

There are 12 allocations, two fixed checkout loads (40 and 64 iterations/s),
and three repetitions: 72 fresh-stack point trials in 12 parallel jobs. Each
job measures six points in a deterministic hash-randomized order. It starts a
new stack and storage, measures the reference baseline, then applies one CPU
allocation for every point. Order is randomized, not exactly position-balanced.
There is no search, replacement, automatic extension, or optional extra wave.

The configured ceilings always sum to 1 CPU across checkout, payment, shipping
and ad. This is not a reservation of physical host capacity. Ad is the recipient
outside the measured checkout operation; its own performance is not evaluated.

| Family | Allocations | What it varies |
| --- | --- | --- |
| Joint | Reference plus equal checkout/payment/shipping ceilings of 0.24, 0.19, 0.14, 0.10 and 0.07 CPU | Resource transfer out of the operation at several fixed magnitudes |
| Selective | One of the three services at 0.07 CPU, the other two at 0.30 | Which local component is restricted, with an identical group minimum |
| Same sum, unequal parts | Permutations of 0.07/0.17/0.18 CPU | Allocation identity and unevenness at the same group sum as the joint 0.14 point |

These are independently sampled allocation states. The paths can be reconstructed
geometrically, but this series does not observe a temporal adaptation process,
demonstrate an incentive to reallocate, or measure alert lead time.

The group balance is the signed loss relative to the reference of
`sqrt(3/4) * log(geometric_mean(checkout,payment,shipping) / ad)`.
Groups are inherited from the tested operation's structure, not fitted to outcomes.
Permuting the three participants keeps this balance unchanged; any outcome
differences between those permutations are retained as limitations of the score.

## Runtime and outcome

[design-v0.1.0.json](design-v0.1.0.json) fixes scenarios, timings, loads, repeats
and analysis. [runtime-v0.1.0.json](runtime-v0.1.0.json) inherits the pinned
deployment and corrected 800-VU measurement path from the preceding follow-up.
The separate [memory overlay](memory-v0.1.0.yaml) gives checkout a fixed 256-MiB
limit and GOMEMLIMIT=192MiB for all new observations. This reduces dependence on
the historical 20-MiB ceiling; it does not guarantee freedom from OOM or isolate
every possible failure mechanism. All other image digests and restart policies
remain unchanged. Rendered Compose, image inspection and resource samples are
retained.

Every point uses 60 s warmup, 90 s reference baseline, 30 s loaded stabilization,
and 90 s test, with up to 30 s graceful completion per phase. There are two
sequential HTTP requests per iteration, each with a 5 s timeout. The static
800-VU capacity covers 64 * 2 * 5 * 1.25 occupied VUs. At least 99% of scheduled
iterations must start in both measured windows; invalid outcomes remain visible.

The SLO is unchanged: checkout-request p95 <= 500 ms and unsuccessful scheduled
iterations < 1%. Failed, dropped and unfinished attempts are counted without
double counting. Post-intervention restart/OOM is diagnostic only and never
changes the SLO label or causes replacement. A failed baseline prevents the test
and is reported. The separate reference test is a sham intervention, not a
forced-safe observation.

## Analysis, deliberately simple

There is no calibration/test split, bootstrap, significance test, majority rule
or binary scientific success criterion. The two loads are analyzed separately.
Every deterministic threshold is shown; equal scores are never split by outcome.
The local-OR comparator exhausts independent per-service quota cutoffs and can
disable any channel. It is a flexible in-sample oracle, not a deployed detector.

The comparison reports the most unsafe observations detected at every maximum
false-alarm count, including zero. That count is a display axis, not an arbitrary
experimental pass mark. Crossing curves are trade-offs, not universal superiority.
A better curve describes these observations only; it is not held-out prediction,
production reliability, or an alert on measured CPU utilization.

The automatic result artifact contains:

- `RESULTS.md`: scenario outcomes and complete false-alarm-budget tables;
- `comparison.json`: all rules, confusion counts and envelopes;
- `thresholds.csv`: every threshold and its TP/FP/FN/TN counts;
- `point-level.csv`: all 72 planned observations, including missing/invalid points.

Valid outcomes and all recoverable outcomes are reported separately. Nothing is
pooled with previous probes. Raw k6 streams and diagnostic traces are retained
in each job artifact, separately from the compact comparison.

## Execution

Run `allocation-threshold-scenarios` in GitHub Actions with `expected_sha` set
to the exact input commit and `execute=true`. Static tests and an end-to-end
smoke precede the fixed matrix; `execute=false` performs only that verification.
The workflow does not launch additional campaigns. Local work is limited to:

```bash
python -B -m unittest discover -s probe4/tests -v
python -B probe4/scripts/scenarios.py verify
```
