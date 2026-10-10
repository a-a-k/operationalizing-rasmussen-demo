# Closed-allocation runtime probes

This repository contains fixed designs, GitHub Actions workflows, analysis code,
and recorded results for constructive runtime probes of closed allocations.

The probes use a digest-pinned OpenTelemetry Demo deployment and a fixed sum of
configured CPU ceilings, not reserved or necessarily consumed CPU. An SLO outcome
is measured externally with k6 and is safe only when
request p95 is at most 500 ms and the error rate is below 1%.

## What was tested

| Probe | Comparison | Question | Observed result |
| --- | --- | --- | --- |
| [Probe 1](probe1/) | Two reallocations from the same three-service reference composition. A is farther from the reference by both Euclidean and Aitchison radial distance; B moves much farther in the checkout-risk direction. | Does radial drift magnitude identify the operationally risky direction? | A was safe in 256/256 retained pairs; the radially nearer B was unsafe in 221/256. The paired reversal rate was 0.863 (exact 95% CI 0.815--0.903). Historical generator-gate deviation: see below. [Aggregate](probe1/results/summary.json) · [replicates](probe1/results/replicate-level.csv) |
| [Probe 2](probe2/) | The same 0.19-CPU local quota is applied to checkout, payment, or shipping alone, and then to all three jointly, within balanced cyclic four-condition blocks. | Does one component's quota represent the joint allocation context? | Every valid singleton point was safe. The joint point was unsafe in 9/32 blocks; the complete within-block pattern occurred in 8/28 valid blocks (exact 95% CI 0.132--0.487). [Blocks and aggregate](probe2/results/summary.json) |
| [Fixed follow-up](probe3/) | Corrected A/B plus six fixed context conditions matched on simple summaries; 104 fresh-stack points. | Does the A/B contrast recur with adequate generator capacity, and what do balance, sum, count and minimum retain or lose? | New observations only; no pooling or fitted detector. Results are reported separately when execution completes. |
| [Threshold scenarios](probe4/) | Twelve fixed redistribution states at two loads, three repetitions; 72 new fresh-stack points with increased checkout memory reserve. | How do balance and local or combined quota thresholds trade off missed SLO violations and false alarms on these scenarios? | Exploratory in-sample comparison of all thresholds, reported separately; no calibration split, binary scientific criterion, or pooling. |

Probe 1 shows that distance from a reference composition is not a risk direction:
a larger radial change can remain safe while a smaller, risk-directed change
violates the SLO. Probe 2 supplies repeated witnesses that an unchanged local
quota does not encode what happened to the rest of a closed allocation. The
second result does not claim superiority over arbitrary multivariate, group-sum,
or application-specific detectors.

No binary success threshold or majority rule is used for either result. Counts,
proportions, and exact intervals are reported descriptively.

**Historical deviation:** Probe 1's executed confirmation omitted its intended
99%-started generator gate. Forty-nine B windows fell below it. Applying that
gate retrospectively gives 172 reversals among 207 retained pairs (exact 95% CI
0.773--0.879), a conditional sensitivity analysis, not a corrected execution.
The separate follow-up uses 800 fixed VUs and enforces the gate during every
baseline and test. The original designs, execution code and data remain intact.

For a claim-by-claim account of the runs, including the safe B cases, invalid
blocks, timeout censoring, pilot provenance, and comparison with ordinary CPU
thresholds, see the **[full results interpretation](RESULTS.md)**.

## Repository map

```text
probe1/
  design.json             fixed directional-pair design
  runtime.json            pinned runtime and measurement contract
  results/                aggregate and replicate-level results
  scripts/, tests/, k6/   execution, analysis, and checks
probe2/
  design.json             fixed joint-context follow-up design
  runtime.json            pinned follow-up runtime
  pilot-provenance.json   selection provenance; not part of the estimand
  results/summary.json    aggregate plus block-level results
  scripts/, tests/, k6/   execution, analysis, and checks
probe3/
  design-v0.1.1.json      fixed 16-pair / 12-six-condition follow-up
  runtime-v0.1.1.json     generator and diagnostic overlay
  scripts/, tests/, k6/   separate runner, measurements and descriptive analysis
.github/workflows/
  verify.yml              static verification and optional runtime smoke test
  probe1.yml              complete 256-pair reproduction
  probe2.yml              complete 32-block reproduction
  followup.yml            verification, smoke and the fixed 28-job follow-up
  scenarios.yml           verification, smoke and the fixed 12-job threshold comparison
```

There is one fixed design and runtime per series; the new follow-up is explicitly
versioned and does not replace historical definitions.
Version identifiers retained inside JSON results are immutable execution
provenance, not alternative active designs.

## Reproduction

The experiments are intentionally executed in GitHub Actions because runner
shape, Docker/cgroup behavior, action revisions, and upstream source are part of
the runtime contract. Local execution is limited to lightweight unit tests.

```bash
python -m unittest discover -s probe1/tests -v
python -m unittest discover -s probe2/tests -v
python -B -m unittest discover -s probe3/tests -v
python -B -m unittest discover -s probe4/tests -v
```

Use the Actions interface for the authoritative checks:

1. Run `verify` for the static gates and optional pinned-stack smoke test.
2. Run `probe-1-directional-pair` with `expected_sha` set to the exact commit,
   an empty `controller_run_id`, and `auto_continue=true`.
3. Run `probe-2-joint-context` with `expected_sha` set to the same exact commit.
4. Run `fixed-experimental-followup` with its exact commit and `execute=true`.
   Its own smoke gate precedes the fixed matrix; it does not search for points
   or dispatch additional waves. Use `execute=false` for verification only.
5. Run `allocation-threshold-scenarios` with its exact commit and `execute=true`
   for the separate 72-point exploratory comparison. It has its own smoke gate
   and a fixed matrix, with no automatic additional waves.

Full reruns are deliberately manual and computationally expensive. The compact
reported evidence is committed under each probe's `results/` directory, so
review does not depend on the retention lifetime of GitHub Actions artifacts.

## Provenance boundary

The repository was reorganized and its history compacted only
after the reported executions. The recorded run identifiers and execution
commits remain in result metadata. The committed counts and replicate/block-level
observations use the current descriptive analysis schema; repository checksums
are provided in `SHA256SUMS`.

Probe 2's pilot found no formally eligible candidate. For the separate follow-up
we fixed the pilot's sole observed interaction window (0.19 CPU at 40 requests/s);
the reported frequency uses only 32 new blocks. The pilot summary is retained
solely to make this choice auditable.

## Scope

This artifact establishes constructive counterexamples in one controlled
runtime instantiation. It does not estimate production prevalence, predictive
accuracy, or the general reliability of a detector.

## License

The artifact code is released under the MIT License. The upstream OpenTelemetry
Demo remains under its own license.
