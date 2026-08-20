# Interpretation of the recorded runs

This document connects the committed observations to the claims they can and
cannot support. The source data are the [Probe 1 aggregate](probe1/results/summary.json),
the [Probe 1 replicate table](probe1/results/replicate-level.csv), and the
[Probe 2 aggregate with all block summaries](probe2/results/summary.json).

## The two questions are different

Probe 1 compares **direction with radial magnitude**. It asks whether the size
of a closed reallocation, measured only as distance from a reference, identifies
the operationally risky direction.

Probe 2 compares **one local component with its joint allocation context**. It
asks whether knowing that one service has a particular quota is sufficient when
the same quota can occur in different closed reallocations.

Together they support the narrower empirical statement used by the paper:

> In a closed allocation, radial magnitude does not encode risk direction, and
> one component does not encode joint allocation context.

The statement that a finite closed allocation has a compositional state space is
a mathematical consequence of closure; the runtime probes do not prove that
every Rasmussen-style system is literally a CPU simplex.

## Probe 1: direction versus radial magnitude

### What was compared

The [fixed design](probe1/design.json) starts from the normalized CPU allocation
`(checkout, payment, shipping) = (0.40, 0.30, 0.30)` and compares two endpoints:

| Endpoint | CPU allocation | Euclidean distance | Aitchison radial distance | Risk-directed coordinate |
| --- | --- | ---: | ---: | ---: |
| A5 | `(0.30, 0.62, 0.08)` | 0.401 | 1.448 | -0.008 |
| B5 | `(0.12, 0.44, 0.44)` | 0.343 | 1.296 | 1.296 |

A5 is farther from the reference under both radial distances. Its movement is,
however, almost orthogonal to the predefined checkout-risk direction. B5 is
radially nearer but moves strongly in that direction. This construction tests
whether “more drift” and “more risk-directed drift” are the same statement.

Each of 256 paired replications ran A5 and B5 on fresh stacks. Pair order was
balanced exactly: 128 ran `A5 -> B5` and 128 ran `B5 -> A5`. Of the selected
attempts, 253 completed on the first infrastructure attempt and three on the
second. All 256 pairs passed the validity gates.

### What was observed

The primary paired outcome is `Y = 1` when A5 is SLO-safe and B5 is SLO-unsafe
in the same replication.

| Observation | Count |
| --- | ---: |
| Valid pairs | 256 |
| A5 safe | 256/256 |
| B5 unsafe | 221/256 |
| Full paired reversal (`Y=1`) | 221/256 = 0.863 |
| Exact 95% interval for the fixed-design reversal proportion | 0.815--0.903 |
| B5 safe | 35/256 |

A5's median p95 was 107.3 ms and its maximum p95 was 292.3 ms; no A5 run
crossed either SLO boundary. B5's median p95 was about 10,001 ms, which reflects
the configured request timeout rather than a precisely measured tail beyond ten
seconds. B5 crossed the latency boundary in 220 runs, the error-rate boundary in
209 runs, and at least one boundary in 221 runs.

The median normalized p95 contrast `(B5 p95 - A5 p95) / 500 ms` was 19.685. It
is useful as a scale-free paired contrast, but its magnitude should not be read
as an uncensored latency estimate because many B5 requests reached the timeout.

Every row, order, SLO value, and selected attempt is available in the
[replicate-level CSV](probe1/results/replicate-level.csv); the exact aggregate
and bootstrap output is in [summary.json](probe1/results/summary.json).

### Interpretation

The experiment gives a repeated constructive counterexample to ranking risk by
distance alone. Both Euclidean distance and radial Aitchison distance call A5
the larger change, yet A5 was always safe and B5 was usually unsafe. The
predefined directional balance orders the pair in the operationally relevant
direction.

This is evidence for the usefulness of a **directed compositional coordinate**,
not evidence that Aitchison radial distance is a better detector than Euclidean
distance. In this construction both radial distances fail for the same reason:
they discard direction.

The 35 safe B5 runs matter. They show that the endpoint is not deterministically
unsafe on every GitHub runner. Therefore 221/256 is evidence of recurrence in
this fixed runtime, not a universal reliability estimate and not a production
failure probability.

### Relation to ordinary thresholds

A checkout-quota rule tailored to this exact construction could also distinguish
A5 (`checkout=0.30`) from B5 (`checkout=0.12`). Probe 1 therefore does not show
that the balance is uniquely capable or operationally superior to every local
alert. Its contribution is more specific: the balance derives an interpretable
risk direction from the closed allocation, whereas an undirected drift score
cannot express that direction.

## Probe 2: local quota versus joint context

### Why a second probe was needed

Probe 1 leaves open the objection that a service-specific checkout threshold
could reproduce its ordering. Probe 2 removes that shortcut by holding the
locally observed quota fixed while changing the rest of the allocation.

The [fixed follow-up design](probe2/design.json) starts from
`(checkout, payment, shipping, ad) = (0.30, 0.30, 0.30, 0.10)` and uses four
conditions:

| Condition | CPU allocation `(checkout, payment, shipping, ad)` |
| --- | --- |
| checkout only | `(0.19, 0.30, 0.30, 0.21)` |
| payment only | `(0.30, 0.19, 0.30, 0.21)` |
| shipping only | `(0.30, 0.30, 0.19, 0.21)` |
| joint | `(0.19, 0.19, 0.19, 0.43)` |

Thus, for each critical service, the local value `0.19` appears once in a
singleton allocation and again in the joint allocation. A rule that sees only
that service's quota receives the same input in both contexts.

The confirmation attempted 32 four-condition blocks. Condition order rotated
through four predefined orders, eight blocks per order, and each point used a
fresh stack. Twenty-eight blocks had all four valid points. Four were invalid:
one because the baseline SLO was already unsafe and three because of a
pre-intervention restart/OOM. They were not silently replaced.

### What was observed

| Condition | Valid points | Safe | Unsafe | Median p95 |
| --- | ---: | ---: | ---: | ---: |
| checkout only | 30 | 30 | 0 | 245.2 ms |
| payment only | 31 | 31 | 0 | 128.0 ms |
| shipping only | 31 | 31 | 0 | 115.5 ms |
| joint | 32 | 23 | 9 | 317.4 ms |

The complete within-block witness requires all three singleton conditions to be
safe and the joint condition to be unsafe. It occurred in eight of 28 valid
blocks: `c003`, `c008`, `c014`, `c018`, `c021`, `c025`, `c027`, and `c029`.
The descriptive exact 95% interval is 0.132--0.487.

There were nine unsafe joint points rather than eight. In `c004`, the joint
point was unsafe and the payment-only and shipping-only points were safe, but
checkout-only was invalid after a pre-intervention restart/OOM. That block
cannot establish the complete paired contrast, so it is not counted as a full
witness. Counting every invalid attempted block as a non-witness gives the
conservative sensitivity value 8/32 = 0.25 (exact 95% interval 0.115--0.434).

The joint p95 distribution is visibly bimodal: safe runs are in the hundreds of
milliseconds, while unsafe runs are near the five-second request timeout and
have substantial errors. Consequently, the joint median of 317.4 ms does not
mean that the unsafe observations were marginal. The median within-valid-block
contrast between joint p95 and the largest singleton p95 was 71.9 ms, but this
overall median mixes the two modes and is not the primary result.

All 32 block summaries, validity reasons, per-condition p95 values, error rates,
and pattern labels are in [Probe 2 summary.json](probe2/results/summary.json).

### Interpretation

The eight complete blocks are repeated witnesses to a representational blind
spot: a local quota of 0.19 can occur with a safe SLO when only one critical
service is reduced and with an unsafe SLO when the critical services are reduced
together. A detector whose complete state is only that one local quota cannot
distinguish those two cases.

The group balance changes by 0.774 in a singleton condition and by 1.659 in the
joint condition. It therefore retains the joint context in one interpretable
coordinate. No alert threshold was fitted or evaluated on this coordinate.

Probe 2 is not a failed detector trial because it was not designed to estimate
classifier accuracy. It also does not establish that the joint condition is
unsafe in most runs: only 9/32 joint points were unsafe. If the claim were
“joint allocation fails more than half the time,” these data would not support
it. The actual claim is existential and constructive: the blind spot occurred
repeatedly under new follow-up runs.

### Relation to ordinary thresholds

A univariate quota threshold for one service cannot reproduce the full witness,
because the local quota is identical in the singleton and joint conditions. A
multivariate rule, a group-sum rule, or an application-specific combination of
CPU alerts could distinguish them. The probe therefore supports the balance as
a compact and principled compositional representation; it does not claim that
the balance is the only possible detector or that it has demonstrated better
precision or recall.

## Selection provenance for Probe 2

The [pilot summary](probe2/pilot-provenance.json) records 12 pilot replications
over six candidate windows. No candidate met the pilot's formal eligibility
rule. The 0.19-CPU, 40-requests/s window was the sole observed interaction
window: it had one complete pattern replication and one pattern-consistent but
invalid replication. That window was fixed for the separate 32-block follow-up;
none of the pilot observations is included in 8/28 or 9/32.

This separation avoids reusing the same observations as confirmation, but the
data-dependent choice still limits generalization. The follow-up demonstrates
that the phenomenon can recur at that constructed boundary; it does not estimate
how often such a boundary appears in production systems.

## Bottom line

- Probe 1 strongly supports the fixed-runtime claim that radial magnitude can
  mis-rank operational risk and that a directed balance captures the relevant
  direction in the constructed pair.
- Probe 2 supports the existence of a local-threshold blind spot through eight
  complete new within-block witnesses, while showing that the phenomenon is
  variable at the selected boundary.
- Neither probe demonstrates predictive superiority over all CPU alerting,
  production prevalence, or a universal mapping from Rasmussen's model to CPU
  allocations.

The executable definitions are in [Probe 1's workflow](.github/workflows/probe1.yml)
and [Probe 2's workflow](.github/workflows/probe2.yml). Runtime integrity checks
are in the [verification workflow](.github/workflows/verify.yml).
