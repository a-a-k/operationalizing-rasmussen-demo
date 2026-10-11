# Closed-allocation drift measurement

Executable runtime probes and saved-data analyses for observing resource
adaptation under closed administrative budgets. The measurement layer retains
the complete selected allocation, expresses relative movement in full isometric
log-ratio (ILR) coordinates, and connects the history to observed pressure,
actions, recipient output and external service outcomes.

The runtime uses a digest-pinned OpenTelemetry Demo deployment. CPU ceilings
are configured limits, not reserved or necessarily consumed CPU. CPU and RAM
have separate budgets. Checkout is SLO-safe only when request p95 is at most
500 ms and unsuccessful scheduled operations are below 1%; restart/OOM remains
a diagnostic and never overrides that label.

## Start here

- [Results and their interpretation](RESULTS.md): comparisons, conclusions and limits.
- [Reproduction guide](REPRODUCING.md): offline checks and manual runtime workflows.
- [Sequential CPU evidence](probe5/results/README.md), including the separate
  [retrospective pre-crossing analysis](probe5/results/history-v0.1.0/README.md).
- [Joint CPU/RAM evidence](probe6/results/README.md).
- [Full-coordinate and metric checks](geometry/results/v0.1.0/RESULTS.md).

## Evidence map

Each row is a separate series. Counts are never pooled across campaigns, and
synthetic transformations are not additional runtime observations.

| Evidence | Comparison | Recorded result | Data |
| --- | --- | --- | --- |
| Sequential CPU migration (Probe 5) | Pressure-motivated transfers versus unchanged controls | 19/20 planned pairs received. All 19 adaptive histories crossed at steps 8--13; controls stayed safe. At retrospective step 6 all pairs were still safe, with positive control-adjusted changes in both goodput and checkout p95. | [Trajectories](probe5/results/trajectory-level.csv), [paired epochs](probe5/results/paired-epochs.csv), [step-6 pairs](probe5/results/history-v0.1.0/step6-pairs.csv) |
| Joint CPU/RAM follow-up (Probe 6) | Control, CPU-only, RAM-only and joint histories | 20 valid blocks; five matched joint-only unsafe witnesses. Crossings: joint 20/20, CPU-only 14/20, RAM-only 17/20, control 0/20. | [Trajectories](probe6/results/joint-v0.2.0/trajectory-level.csv), [matched steps](probe6/results/joint-v0.2.0/four-way-epochs.csv) |
| Geometry verification | Full ILR and equal multiplicative updates across starting states | Six unlabeled synthetic checks; 1,145 saved windows retained in separate series. Equal relative updates have equal ILR displacement; Euclidean share distance describes additive change. | [Checks](geometry/results/v0.1.0/metric-properties.csv), [coordinates](geometry/results/v0.1.0/trajectory-coordinates.csv), [figure](geometry/results/v0.1.0/geometry.svg) |
| Fixed endpoints (Probe 3) | Corrected A/B and matched-summary service permutations | A safe in 16/16, nearer B unsafe in 10/16. Equal-balance permutations: checkout-low unsafe in 4/11; payment-low and shipping-low safe in 12/12 and 11/11. | [Interpretation](probe3/results/README.md), [all 104 points](probe3/results/point-level.csv), [aggregate](probe3/results/summary.json) |
| Threshold scenarios (Probe 4) | Twelve configurations, two loads, five repetitions | 109/120 points valid. At zero observed false alarms, balance detected 10/33 and 22/39 unsafe points; local OR detected 30/33 and 30/39. In-sample only. | [Interpretation](probe4/results/README.md), [points](probe4/results/point-level.csv), [all rules](probe4/results/thresholds.csv) |

Historical [Probe 1](probe1/) and [Probe 2](probe2/) are preserved separately:
221/256 paired reversals and 8/28 complete context witnesses, respectively.
Probe 1 omitted its intended generator-start gate; its conditional sensitivity
analysis is not a corrected execution. See the
[historical interpretation](docs/historical-endpoints.md) for deviations,
timeouts, failure diagnostics and selection provenance.

## What this establishes

Runtime histories instantiate a constructed adaptation mechanism: measured
recipient pressure motivates closed transfers, useful recipient output grows,
and another service approaches and crosses an externally measured boundary.
Fixed endpoints demonstrate information lost by radial magnitude and a single
group projection. Full ILR coordinates preserve the selected allocation; known
compositional geometry gives relative changes a consistent scale.

These results establish a measurement basis, not a universally better detector,
production failure probability, human-behavior model or calibrated safe region.
Platform integration, diagnostic usefulness and held-out prediction remain
separate evaluations. Budgets, workload and runtime history still condition outcomes.

## Verification without running a workload

Python 3.13 and its standard library suffice; no Docker, network or data-science
packages are needed:

```bash
python -B scripts/verify_archive.py
```

This checks checksums, local documentation links, anonymity, all unit-test suites
and saved-data analysis, including the step-6 contrasts. Full experiments run
only in the manual workflows in [REPRODUCING.md](REPRODUCING.md).
Pushing changes runs static verification only, not a workload campaign.

## Provenance and retention

Executed designs, image digests, action revisions and primary observations are
preserved. Execution identifiers and commits in metadata refer to the original
runs, without identifying source-hosting links in documentation. Post-run
analyses are explicitly versioned and do not alter frozen experiments.

Committed observations, aggregates and rules are the reviewable archive;
reading them does not depend on short-lived Actions artifacts. Native streams
and diagnostics are distinct execution artifacts, not reconstructed by compact
tables. [SHA256SUMS](SHA256SUMS) covers archived files using canonical LF text bytes.

## License

Artifact code is released under the [MIT License](LICENSE). Upstream
OpenTelemetry Demo retains its own license.
