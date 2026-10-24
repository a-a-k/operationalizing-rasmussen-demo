# Reproduction

## Verify the retained artifact

Use Python 3.13 and the pinned numerical dependency:

```sh
python -m pip install -r requirements.txt
python -B scripts/verify_archive.py --report artifacts/verification.json
```

Verification covers canonical-LF text and exact-byte compressed/PNG hashes,
local links, retained scope, both studies, reduced log-odds, frozen CPU fitting
and calibration, online scores, both threshold rows, and runtime relocation.
It starts no workloads and does not overwrite evidence. LICENSE is distributed
separately from the measurement checksum manifest.

## Recompute the eight-history study

```sh
python -B evolving-state/scripts/analyze.py --inputs evolving-state/results/campaign-v0.1.1/inputs --output artifacts/evolving-state
python -B evolving-state/scripts/directional.py --output artifacts/directional
python -B evolving-state/scripts/reduced.py --output artifacts/reduced-log-odds
```

These rebuild state/policy assessments from events, check conditional contact
for both directions, and independently maintain two log-odds histories to compare
orientations and first constraints on the same availability mask.

The call-level benefit and policy-only witnesses can be regenerated using
`python -B evolving-state/scripts/describe.py --bundle <copy-of-bundle>`.
Optional plotting uses `evolving-state/plot-requirements.txt` and
`evolving-state/scripts/render.py --bundle <copy-of-bundle>`.
Those descriptive/plot commands write inside their supplied bundle; use a copy.

Native arithmetic validation uses a local Linux `promtool`:

```sh
python -B evolving-state/scripts/promql_check.py --inputs evolving-state/results/campaign-v0.1.1/inputs --output artifacts/native-promql --promtool /path/to/promtool
```

Omitting `--promtool` downloads the checksum-pinned engine to the output directory.
The saved native results validate arithmetic rather than platform latency.

## Recompute the CPU comparison

```sh
python -B drift-monitor/scripts/replay_evidence.py --output artifacts/cpu-replay
```

This refits the model from the same 20 backgrounds, checks the original frozen
model, reconstructs first-qualified selection from all 273 attempts, replays
online scores and reproduces both threshold rows. Original model bytes remain
unchanged. Numerical tolerances accommodate platform differences; identities,
hashes, selected attempts and discrete counts must agree.

## New workloads on GitHub Actions

| Workflow | Scope |
|---|---|
| [evolving-state.yml](.github/workflows/evolving-state.yml) | Engineering check or eight new retry/forwarding histories |
| [compositional-mewma.yml](.github/workflows/compositional-mewma.yml) | Twenty fitting/calibration backgrounds |
| [compositional-mewma-extended.yml](.github/workflows/compositional-mewma-extended.yml) | New 250-pair batch with the archived frozen model; optional explicit block subset |
| [verify.yml](.github/workflows/verify.yml) | Read-only archive and upstream/runtime-configuration checks |

Supply `expected_sha` as the exact implementation commit for runtime dispatch.
New runs are separate datasets and do not replace archived counts. Shared pinned
images, overlays, sampling and quota readback are in [runtime/](runtime/README.md).
The CPU study's executed design files retain their original bytes.

## Retention and evidence boundaries

Committed CPU records retain integrated measurements, coverage, quota/timing
checks, qualifications, configurations and online scores. They do not duplicate
every per-second stream or container log. Source hashes identify original records.
All twenty backgrounds and every test attempt are retained, including failures.

Keep the reviewed snapshot and checksum manifest available independently of
finite Actions artifact retention. Preserve new raw outputs before expiration.
