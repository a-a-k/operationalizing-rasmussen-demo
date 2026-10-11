# Retrospective CPU-history analysis v0.1.0

This is a separate post-run analysis of the 594 saved Probe 5 windows.
It does not change the runtime design, add observations or pool campaigns.
The [analysis definition](../../history-analysis-v0.1.0.json) fixes step 6
retrospectively: two complete cycles of the three donors.

For each metric, the paired contrast is the adaptive change from its own
baseline minus the corresponding control change from its own baseline.
All 19 received pairs were valid and SLO-safe at that step. Both contrasts
were positive in every pair:

| Metric | Median | Minimum | Maximum |
| --- | ---: | ---: | ---: |
| Advertising goodput (responses/s) | +863.9333 | +723.9222 | +1964.9444 |
| Checkout p95 (ms) | +47.0987 | +6.7626 | +155.2840 |

Adaptive allocation at step 6 was (.22,.22,.22,.34). Recipient gains therefore
accompanied checkout deterioration before SLO crossing. This is a descriptive
comparison, not preregistered confirmation, causal attribution of a transfer,
validated warning lead time or proof of diagnostic superiority.

## Files

- [step6-pairs.csv](step6-pairs.csv): all 19 per-pair inputs, differences,
  preceding pressure, donor, quotas and validity flags.
- [summary.json](summary.json): exact descriptive statistics and missing runner.
- [ilr-history.csv](ilr-history.csv): every saved window with all three CPU
  coordinates, successive change, reference displacement and registered path length.
- [measurement-metadata.json](measurement-metadata.json): component order, basis,
  resource budget, reference, source hash and timestamp availability.
- [Replay code](../../scripts/analyze_history.py).
- [Original observations](../trajectory-level.csv).

Path length is the sum of successive full-coordinate displacement lengths at
the recorded epoch frequency. No actual timestamps or rates are inferred.
One planned pair, migration-006, has no observations and remains unknown.
All readable invalid windows would be retained, not selected away; the saved
source contains valid windows only. The source and execution design are
checksum-validated before analysis.

From the repository root:

```bash
python -B probe5/scripts/analyze_history.py --output-dir artifacts/cpu-history-v0.1.0
```
