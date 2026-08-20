# Closed-allocation runtime probes

This is the companion artifact for a double-anonymous research submission. It
contains the fixed designs, GitHub Actions workflows, analysis code, and compact
results for two constructive runtime probes. It does not contain the manuscript
or the authors' private protocol notes.

Both probes use a digest-pinned OpenTelemetry Demo deployment and a closed CPU
budget. An SLO outcome is measured externally with k6 and is safe only when
request p95 is at most 500 ms and the error rate is below 1%.

## What was tested

| Probe | Comparison | Question | Observed result |
| --- | --- | --- | --- |
| [Probe 1](probe1/) | Two reallocations from the same three-service reference composition. A is farther from the reference by both Euclidean and Aitchison radial distance; B moves much farther in the checkout-risk direction. | Does radial drift magnitude identify the operationally risky direction? | A was safe in 256/256 valid pairs; the radially nearer B was unsafe in 221/256. The paired reversal rate was 0.863 (exact 95% CI 0.815--0.903). [Aggregate](probe1/results/summary.json) · [replicates](probe1/results/replicate-level.csv) |
| [Probe 2](probe2/) | The same 0.19-CPU local quota is applied to checkout, payment, or shipping alone, and then to all three jointly, within randomized four-condition blocks. | Does one component's quota represent the joint allocation context? | Every valid singleton point was safe. The joint point was unsafe in 9/32 blocks; the complete within-block pattern occurred in 8/28 valid blocks (exact 95% CI 0.132--0.487). [Blocks and aggregate](probe2/results/summary.json) |

Probe 1 shows that distance from a reference composition is not a risk direction:
a larger radial change can remain safe while a smaller, risk-directed change
violates the SLO. Probe 2 supplies repeated witnesses that an unchanged local
quota does not encode what happened to the rest of a closed allocation. The
second result does not claim superiority over arbitrary multivariate, group-sum,
or application-specific detectors.

No binary success threshold or majority rule is used for either result. Counts,
proportions, and exact intervals are reported descriptively.

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
.github/workflows/
  verify.yml              static verification and optional runtime smoke test
  probe1.yml              complete 256-pair reproduction
  probe2.yml              complete 32-block reproduction
```

There is one current `design.json` and one current `runtime.json` per probe.
Version identifiers retained inside JSON results are immutable execution
provenance, not alternative active designs.

## Reproduction

The experiments are intentionally executed in GitHub Actions because runner
shape, Docker/cgroup behavior, action revisions, and upstream source are part of
the runtime contract. Local execution is limited to lightweight unit tests.

```bash
python -m unittest discover -s probe1/tests -v
python -m unittest discover -s probe2/tests -v
```

Use the Actions interface for the authoritative checks:

1. Run `verify` for the static gates and optional pinned-stack smoke test.
2. Run `probe-1-directional-pair` with `expected_sha` set to the exact commit,
   an empty `controller_run_id`, and `auto_continue=true`.
3. Run `probe-2-joint-context` with `expected_sha` set to the same exact commit.

Full reruns are deliberately manual and computationally expensive. The compact
reported evidence is committed under each probe's `results/` directory, so
review does not depend on the retention lifetime of GitHub Actions artifacts.

## Provenance boundary

The submission-facing repository was reorganized and its history compacted only
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
