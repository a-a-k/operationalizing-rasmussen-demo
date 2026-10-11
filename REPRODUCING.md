# Reproduction and archive verification

## Lightweight offline verification

Use Python 3.13 from the repository root:

```bash
python -B scripts/verify_archive.py
```

This checks canonical-LF SHA-256 hashes, local Markdown links, all eight
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

## Full runtime reruns: manual GitHub Actions only

Set expected_sha to the exact checked-out commit. Engineering gates are outside
the reported replication set. Every rerun is a new series, not a replacement
for or an automatic addition to the committed counts.

| Series | Workflow | Fixed scope |
| --- | --- | --- |
| Sequential CPU migration | [migration.yml](.github/workflows/migration.yml) | execute=true; simultaneous-workload gate, then 20 paired histories. No replacements. |
| Joint CPU/RAM follow-up | [joint-resources-v0.2.yml](.github/workflows/joint-resources-v0.2.yml) | Active v0.2.0; 20 four-history blocks. |
| Fixed endpoints | [followup.yml](.github/workflows/followup.yml) | execute=true; smoke, then 16 A/B pairs and 12 six-condition blocks, 104 points. |
| Threshold scenarios | [scenarios.yml](.github/workflows/scenarios.yml) | execute=true; maximum-load gate, then 120 points in 20 jobs. |
| Geometry replay | [geometry.yml](.github/workflows/geometry.yml) | Saved-data analysis only. |
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
