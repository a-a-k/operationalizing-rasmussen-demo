# Fixed experimental follow-up (0.1.1)

This is a separate, new series. It does not replace or pool observations with
[Probe 1](../probe1/) or [Probe 2](../probe2/). Execution is exclusively in GitHub Actions.

The [machine-readable design](design-v0.1.1.json), [runtime overlay](runtime-v0.1.1.json)
and execution commit fix every point, repetition and comparison before measurement.
The overlay references the historical digest-pinned runtime by checksum. All
containers, health rules, image digests and Actions SHAs are inherited unchanged;
the generator and observation code are new. Changes to a frozen study require a
new version. There is no pilot search, replacement, automatic extension or
outcome-dependent selection.

Revision 0.1.1 fixes a setup error: uppercase endpoint identifiers A/B were used
verbatim in Compose project names, which require lowercase. The initial matrix
was stopped for this implementation defect; its observations are not pooled
with the corrected series. The points, count, salt/order and analysis did not
change. [Execution provenance](execution-provenance.json) records both setup
attempts without linking to an identifying hosting account.

## Questions and fixed scope

The A/B arm consists of 16 paired blocks, each with two fresh-stack trials.
It repeats the original endpoints at 32 scheduled operations/s, with **800 VUs**
instead of 320 and a generator gate on the actual execution path. The original
checkout-versus-payment/shipping direction is inherited to replicate the pair;
it is not independent evidence that this grouping is universally appropriate.

The context arm consists of 12 blocks of six fresh-stack trials at 40/s.
Checkout, payment and shipping are the selected controlled participants in the
checkout operation; ad is the recipient outside that tested operation. This
structural grouping is fixed before new observations. It does not label other
checkout dependencies non-critical or identify a universal direction of risk.

| Point | checkout | payment | shipping | ad |
| --- | ---: | ---: | ---: | ---: |
| balanced_021 | 0.21 | 0.21 | 0.21 | 0.37 |
| checkout_015 | 0.15 | 0.24 | 0.24 | 0.37 |
| payment_015 | 0.24 | 0.15 | 0.24 | 0.37 |
| shipping_015 | 0.24 | 0.24 | 0.15 | 0.37 |
| anchor_019 | 0.19 | 0.19 | 0.19 | 0.43 |
| payment_011 | 0.19 | 0.11 | 0.27 | 0.43 |

The first four points have the same group sum, recipient quota and number of
services reduced relative to the reference. Balanced versus concentrated
reductions change the geometric mean and therefore the balance. The last pair
additionally holds checkout's quota fixed. The three permutations at 0.15 have
the same minimum, group balance and both radial distances, but allocate the
small quota to different services. They explicitly test information lost by
those scalar descriptions as well.

The 0.19 anchor comes from the previously disclosed Probe 2 window. The new
points are fixed contrasts around it, not candidates in an undisclosed search.
The 0.21 balanced point applies a milder joint reduction than that anchor.
Whether it exhibits non-restarting SLO degradation is an empirical question;
the study does not guarantee a favorable result or add points to obtain one.

All 104 point trials run once. The 16/12 block counts are a bounded descriptive
follow-up budget, not a power calculation or a promised precision target.
With these counts intervals may be wide, especially for context contrasts.
Condition order is reproducibly randomized under an exact position-balance
constraint: eight A-first/eight B-first blocks, and every context condition
occupies each of six positions twice. Each point starts a new stack and volume.
There is no sequential allocation trajectory within a point.

## What comparison can establish

The features are checkout quota, group sum, minimum group quota, reduced-service
count, recipient quota, Euclidean distance, Aitchison distance and the group
balance change. Positive balance change means the geometric mean in the selected
group fell relative to the recipient group; it is not itself an observed failure.

Paired SLO discordance at equal sums/counts would show that these summaries lose
outcome-relevant allocation context. A different balance at those points does
not prove that it predicts the outcome better than minimum quota or a full-vector
rule. Discordance at equal balance would establish a limitation of that balance.
Both contrast directions are reported; discordance in a single block is not
proof of a deterministic quota-to-SLO mapping in a variable runner environment.
Within-condition recurrence and repetition of contrasts matter for interpretation.

There is **no fitted alert threshold, arbitrary majority test, unmotivated null
hypothesis, accuracy estimate, or binary scientific success criterion**. SLO boundaries
(500 ms and 1%) are explicitly the experiment's operating policy, not a universal
standard. Negative and inconclusive observations are retained.

## Generator and measurement contract

Both arms use `preAllocatedVUs=maxVUs=800`, `timeUnit=1s`, `gracefulStop=30s`.
Each operation makes two sequential HTTP requests. Their timeout budget is
20 s in A/B and 10 s in context, so the worst timeout-based occupancy is
`max(32*20,40*10)=640` VUs. Eight hundred supplies a fixed 25% allowance, not a
guarantee about generator CPU. Baseline and test must each start at least 99% of
scheduled operations. Actual generator cgroup CPU and host CPU are retained.
The generator shares the four-vCPU runner with the stack; this is recorded, not
assumed to be an independent machine.

For `scheduled = rate * duration`, mutually exclusive categories are:

```text
failed     = finished - successful
dropped    = scheduled - started
unfinished = started - finished
error rate = (failed + dropped + unfinished) / scheduled
           = 1 - successful / scheduled
```

Timeouts are already failures; they are not counted again. Success requires both
HTTP requests to succeed and checkout to return an order identifier. Dedicated
started/finished counters exclude k6's terminal no-op iteration. The raw k6
dropped counter is also retained for comparison with scheduled-minus-started.

The SLO p95 uses all completed **checkout HTTP request** durations, including
failed responses and timeouts, with type-7 interpolation. Completions during the
30-second graceful stop belong to their originating measurement phase. This is
not p95 of the whole two-request operation; full-operation p95/max are recorded
separately. Unfinished attempts contribute to errors; absent checkout durations
give no p95 and an unsafe label. Timeout-saturated p95 does not identify the
uncensored tail. SLO-safe means `p95 <= 500 ms AND error_rate < 0.01` exclusively.

Baseline failure, pre-intervention system failure, quota mismatch or generator
failure marks a point technically invalid. The report shows this subset and
**all recoverable test outcomes** separately, including gate failures. No invalid
trial is replaced. Missing blocks are listed, never treated as successes.
Post-intervention restart/OOM remains diagnostic and neither excludes a point
nor changes its SLO label.

## Failure diagnostics and runtime integrity

The pinned memory/restart settings are not changed: checkout has a 20 MiB
container ceiling, `GOMEMLIMIT=16MiB`, and `restart=unless-stopped`. This is not
a factorial CPU-versus-memory experiment and cannot establish a CPU-only cause.

Each point records Docker events with exit-code attributes, time relative to the
intervention, inspection snapshots, compose logs, and two-second host/cgroup
samples (registry refreshed every six seconds). Samples include CPU usage,
throttling, memory usage and `memory.events`. No counter delta is computed across
a changed PID/cgroup inode or a reset. Event timestamps distinguish actual
post-intervention failures from ordinary teardown after measurement. Missing
diagnostics are disclosed and never delete primary outcomes.

Rendered Compose, image inspections, effective `cpu.max`, `NanoCpus`, runner image
versions and Docker/Compose versions are archived. The closed state is the sum
of **configured CPU ceilings**, not reserved CPU or actual utilization. Other
services remain part of the external runtime context.

## Running and reading the evidence

The corrected series is complete. Its [archived interpretation](results/README.md),
[all 104 points](results/point-level.csv), [block inputs](results/block-level.json)
and [aggregate](results/summary.json) are available without an Actions download.
The A/B contrast recurred in 10/16 pairs; equal-balance service permutations
also produced discordant outcomes. These results are reported separately.

Run [fixed-experimental-followup](../.github/workflows/followup.yml) with the exact
commit in `expected_sha`. With `execute=false` it runs only verification and an
end-to-end smoke outside the sample. With `execute=true`, a successful smoke
releases the fixed 28-job matrix (maximum 20 simultaneous jobs), then aggregates
every available block. No controller dispatches additional waves.

The workflow writes:

- `followup-preflight`: checks and smoke evidence, excluded from analysis;
- `followup-block-<id>`: every point's losslessly compressed raw k6 metrics,
  compact primary observations, counters, events, resource samples and provenance;
- `followup-result`: descriptive `summary.json`, `block-level.json`, `point-level.csv`
  and a readable `RESULTS.md`, including exact intervals and both contrast directions.

Raw job artifacts are retained for 14 days; the aggregate for 90 days. These are
download deadlines, not the archival lifetime: before expiry, preserve the
reported aggregate and raw evidence in a versioned archive. Evidence checksums
must accompany any reported result. Identifying source-hosting URLs are not
included in review-facing documentation.

Local checks do not start Docker:

```bash
python -B -m unittest discover -s probe3/tests -v
python -B probe3/scripts/study.py verify
```
