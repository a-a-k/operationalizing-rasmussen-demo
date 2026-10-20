# Reproduction and archive verification

## Evolving-state campaign

The [dedicated results](evolving-state/results/campaign-v0.1.1/README.md)
include the eight complete histories, compressed event-level inputs, native
PromQL validation, interpretation and a full-history figure. Reconstruct the
main numerical comparison without starting a workload:

```sh
python -B evolving-state/scripts/analyze.py --inputs evolving-state/results/campaign-v0.1.1/inputs --output artifacts/evolving-state-replay
python -B -m unittest discover -s evolving-state/tests -v
```

Runtime is restricted to the separate manual
[evolving-state workflow](.github/workflows/evolving-state.yml). The two
engineering datasets are retained separately from the eight-history campaign.
Plotting is optional and uses `evolving-state/plot-requirements.txt`.

## Lightweight offline verification

Use Python 3.13 from the repository root:

```bash
python -B scripts/verify_archive.py
```

This checks canonical-LF text/exact-byte binary SHA-256 hashes, local Markdown links, all standard-library
unit-test suites and the saved-data CPU-history analysis. It does not start
Docker, contact GitHub, install packages or overwrite committed outputs.
Identity checks inspect local Git configuration solely to detect documentation
and comment leaks; they never change authorship or export identities.

To regenerate the versioned retrospective CPU-history tables into scratch space:

```bash
python -B probe5/scripts/analyze_history.py --output-dir artifacts/cpu-history-v0.1.0
```

The [analysis definition](probe5/history-analysis-v0.1.0.json) fixes step 6
retrospectively. Source quotas, outcomes and validity flags are retained;
missing outcomes and actual timestamps are not inferred. Compare outputs with
[the archived analysis](probe5/results/history-v0.1.0/).

Geometry can also be reproduced without workloads:

```bash
python -B geometry/scripts/analyze.py --commit 0000000000000000000000000000000000000000 --run-id 0 --output artifacts/geometry-v0.1.0
```

The zero identifiers explicitly mark a local replay without Actions provenance,
not a newly executed hosted run. Original execution identifiers remain in the
committed geometry summary.

For accumulated guarded histories, use the committed source data only:

```bash
python -B probe7/scripts/analyze_accumulated.py --output-dir artifacts/accumulated-history-replay
```

The [analysis definition](probe7/accumulated-analysis-v0.1.0.json) pins original
record hashes and marks retrospective selections. Outputs include all 988
windows, complete displacement vectors, requirement margins, command reversals,
entire selected-prefix witnesses and separately unlabeled geometry checks.
The [archived interpretation](probe7/results/accumulated-v0.1.0/README.md) explains
why this measurement task differs from the additional one-step analogy task.
Original designs and external SLO labels are not overwritten.

## Trajectory observability: optional numerical replay

The [separate readout](drift-monitor/trajectory-observability/README.md) bundles
all required measured inputs, including 48 native CPU streams and 250 compact
continuous paired records. Its numerical replay requires the pinned NumPy and
Matplotlib versions; the lightweight archive verifier above remains standard
library only.

```bash
python -m pip install -r drift-monitor/trajectory-observability/requirements.txt
python -B drift-monitor/trajectory-observability/scripts/analyze.py --output-dir artifacts/trajectory-observability-replay
python -B drift-monitor/trajectory-observability/scripts/check_replay.py --output-dir artifacts/trajectory-observability-replay
python -B -m unittest discover -s drift-monitor/trajectory-observability/tests -v
```

This starts no workloads. The output directory is scratch space, not the
committed archive. Use --no-figures to skip rendering. Compare CSV and JSON
outputs with [the versioned results](drift-monitor/trajectory-observability/results/v0.1.0/).
The procedure changes no frozen MEWMA rules and adds no runtime replications.

## Full runtime reruns: manual GitHub Actions only

The [250-job drift-generalization workflow](.github/workflows/drift-generalization.yml)
runs the fixed [three-method comparison](probe9/README.md). Its matrix is 25
initial CPU compositions by two loads by five repetitions. Each job contains
paired adaptive/control histories; aggregation compares ILR and raw shares
separately against native Prometheus. Set expected_sha to the exact campaign
commit. Missing or failed jobs are not replaced.
The completed 250-pair execution, compact source records, native responses and
plain-language interpretation are archived in
[probe9/results/generalization-v0.1.0](probe9/results/generalization-v0.1.0/RESULTS.md).

The [native practical forecast replay](.github/workflows/practical-forecast-replay.yml)
is also manual, but starts no workload: checksum-pinned Prometheus executes
queries over saved observations. Set expected_sha to its exact commit. Its
[definition](probe8/practical-baseline-v0.1.0.md) describes the practical-method
provenance, short-history adaptations and retrospective comparison boundary.

Set expected_sha to the exact checked-out commit. Engineering gates are outside
the reported replication set. Every rerun is a new series, not a replacement
for or an automatic addition to the committed counts.

| Series | Workflow | Fixed scope |
| --- | --- | --- |
| Guarded full-stack adaptation | [guarded-adaptation.yml](.github/workflows/guarded-adaptation.yml) | mode=campaign; finalized main v0.2.0, 24 runner pairs. Technical mode=pilot is separate, not needed to read saved results. |
| Passive warning confirmation | [warning-confirmation.yml](.github/workflows/warning-confirmation.yml) | Separate 20 new runner pairs; frozen source model and thresholds, no effect on allocation policy. |
| Sequential CPU migration | [migration.yml](.github/workflows/migration.yml) | execute=true; simultaneous-workload gate, then 20 paired histories. No replacements. |
| Joint CPU/RAM follow-up | [joint-resources-v0.2.yml](.github/workflows/joint-resources-v0.2.yml) | Active v0.2.0; 20 four-history blocks. |
| Fixed endpoints | [followup.yml](.github/workflows/followup.yml) | execute=true; smoke, then 16 A/B pairs and 12 six-condition blocks, 104 points. |
| Threshold scenarios | [scenarios.yml](.github/workflows/scenarios.yml) | execute=true; maximum-load gate, then 120 points in 20 jobs. |
| Geometry replay | [geometry.yml](.github/workflows/geometry.yml) | Saved-data analysis only. |
| Accumulated guarded-history replay | [guarded-history-analysis.yml](.github/workflows/guarded-history-analysis.yml) | Saved-data analysis only; no services or additional observations. |
| Warning-rule development | [warning-development.yml](.github/workflows/warning-development.yml) | Archived source data only; already frozen for the independent confirmation. |
| Static checks / optional smoke | [verify.yml](.github/workflows/verify.yml) | Push/PR runs static checks; manual runtime_smoke=true additionally starts a stack. |

Historical workflows are preserved separately:

- [probe1.yml](.github/workflows/probe1.yml): original 256-pair series, including
  the disclosed generator-gate deviation. For an independent rerun, start with
  an empty controller_run_id; the controller manages only that fixed series.
- [probe2.yml](.github/workflows/probe2.yml): original 32-block follow-up.
- [joint-resources.yml](.github/workflows/joint-resources.yml): original v0.1.0
  engineering-gated definition; its campaign did not start.
- [ram-calibration.yml](.github/workflows/ram-calibration.yml): nine engineering
  observations, never pooled with the active CPU/RAM campaign.

No outcome triggers an extra scientific campaign. Changes to runtime inputs
require a new version and separate provenance, not editing executed designs.

## Archive boundaries

[RESULTS.md](RESULTS.md) links every conclusion to committed observations.
Aggregate JSONs contain counts and provenance; CSVs contain individual outcomes.
[Probe 3 block records](probe3/results/block-level.json) preserve inputs for
aggregation replay. [Probe 4 thresholds](probe4/results/thresholds.csv) retain
every achievable rule, including disabled channels.

Native k6 streams, container events and resource samples are distinct artifacts.
Retention periods are defined by each workflow: raw streams commonly expire
after 14 days and aggregates after 90. Expired streams cannot be reconstructed
from a CSV. Preserve raw artifacts separately before expiry for new reruns.

Keep the committed compact evidence available through review and subsequent
archival use. Actions retention is not the repository's archival lifetime.
Preserve a durable snapshot of the exact reviewed commit and its checksum manifest.

The guarded follow-up can be replayed from committed block records:

```bash
python -B probe7/scripts/analyze.py --block-records probe7/results/main-v0.2.0/block-level.json --output-dir artifacts/guarded-replay
```

Its external labels can be independently rescored from preserved primary values:

```bash
python -B probe7/scripts/audit_primary.py --inputs probe7/results/main-v0.2.0/primary --output-dir artifacts/guarded-primary-replay
```

See [primary-input boundaries](probe7/results/main-v0.2.0/primary/README.md):
these committed packs preserve scoring inputs, not every original telemetry log.

The manifest uses canonical LF for text and exact bytes for compressed primary
inputs and PNG figures. It excludes only itself and LICENSE. A review mirror may redact the
copyright holder without changing the measurement evidence. This exception
does not permit changes to code, data, designs or interpretation documents.
