# CPU MEWMA: recorded evidence and replay

## Compared observers

The measured state has eleven positive CPU-consumption parts. Both observers
retain all parts through ten orthonormal contrasts, `V*x` or `V*log(x)`, and
use full covariance and `lambda=0.2`. Each history retains its reference.
Fitting uses eight separate backgrounds and calibration twelve more; neither
uses the test outcomes. The original frozen model is retained byte-for-byte.

## Results

All 250 selected reallocation histories were detected by both original observers.
ILR was earlier in 207 pairs, tied in 40 and later in three.

| ILR threshold | Mean advance, cycles | Mean advance, seconds | Control signals, ILR / raw |
|---|---:|---:|---:|
| Original `h` | 1.252 | 50.08 | 9 / 6 |
| Retrospective `1.10h` | 0.972 | 38.88 | 6 / 6 |

Cycles comprise a ten-second guard and thirty-second measurement. Delay is
counted after the first four pre-intervention cycles and restricted to twelve;
an undetected history is assigned twelve. The `1.10h` row was chosen using
evaluation controls retrospectively. Its equal observed control counts do not
establish equal population false-alarm rates. Both rows retain both methods
and all controls. Signals without a planned quota transfer are not automatically
classified as false alarms.

Representation, covariance estimation and calibration were not causally
separated. The result concerns representation-dependent resource-state detection,
not service-violation lead time or operational benefits of intervention.

## Selection, availability and preparation cost

The original 250 attempted pairs yielded 230 qualified pairs. Two later batches
of twenty and three repeated the original unqualified block identities. The
reported selection takes each originally planned block's **first qualified**
attempt; it never replaces an already qualified pair or selects by signal outcome.

All **273 attempts**, including 23 unqualified attempts, are retained with
their configurations, reasons, settling checks, references, load diagnostics,
per-window coverage, quota/timing checks, integrated CPU and original online scores.
The dataset contains 8,736 recorded test measurement windows. Every attempt
record contains both history entries; failed qualification remains visible.

Twenty original background histories are also retained: eight fitting and twelve
calibration histories, including their qualification/settling evidence. Per
history the scheduled load includes 600 seconds of warmup, 90 seconds of
reference measurement and sixteen 40-second monitoring cycles. Stack startup,
image preparation and graceful termination are additional costs. Early failure
or missing observations must not be treated as free successful runs.

Qualification requires positive CPU values, at least 95% counter coverage for
each part, actual quota readback, timely changes and the declared settling gate.
The gate is an engineering check, not proof of stationarity. External SLO
failures do not exclude a history. This retry-policy extension is not a newly
unselected independent 250-pair replication.

## Evidence

- [Frozen model](inputs/frozen-model.json).
- [All background records](inputs/backgrounds.jsonl.gz).
- [All attempted pair records](inputs/attempts.jsonl.gz).
- [Attempt ledger](inputs/attempt-ledger.csv) and [selected first-qualified pairs](inputs/selected-cases.csv).
- [Reproduced result rows and checks](analysis/summary.json).
- [Source-record hashes and export boundaries](provenance.json).

The original per-second streams and complete container logs are not duplicated
here. Integrated measurements and all inputs needed for the reported replay
are retained. Repeated frozen-model copies were omitted from each pair record;
the exact original model is stored once. Host workspace prefixes in textual
error messages were redacted; measurement values and identities were preserved.

## Reproduce

```sh
python -m pip install -r requirements.txt
python -B drift-monitor/scripts/replay_evidence.py --output artifacts/cpu-replay
```

The replay recomputes background means, covariance and calibrated thresholds,
checks the frozen source model, reconstructs selection from original qualification
flags and checks it against the ledger, replays original online scores, and
recalculates both result rows. It starts no workloads and changes no thresholds
in the archived model. Numerical tolerances permit small platform differences.
