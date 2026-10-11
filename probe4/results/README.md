# Completed exploratory threshold comparison

All 120 planned points were recorded; 109 were technically valid. Eleven
baseline/pre-intervention failures remain visible. There are 60 valid points
at 40/s (33 unsafe, 27 safe), and 49 at 64/s (39 unsafe, 10 safe).
The loads are analyzed separately.

| Load | Group-balance detections at zero observed false alarms | Local OR | Checkout-only |
| --- | ---: | ---: | ---: |
| 40/s | 10/33 | 30/33 | 20/33 |
| 64/s | 22/39 | 30/39 | 26/39 |

All thresholds were selected and evaluated on the same observations.
Local OR exhausts independent per-service cutoffs, including disabled channels;
it is a more flexible in-sample oracle, not an independently validated detector.
The chosen balance did not outperform it. No full-vector predictor was fitted.

At 40/s, restricting checkout or payment to .07 CPU was unsafe in 5/5 points
each, while restricting shipping to the same quota was safe in 5/5. Their
group balance is identical. This limits the scalar summary's sufficiency,
not the invertibility of a complete ILR representation.

These fixed endpoints are not an observed adaptive process and do not measure
warning lead time. A false-alarm budget is the display axis of an in-sample
trade-off, not a scientific success threshold. Negative comparisons, invalid
points and readable post-intervention failures are not dropped.

## Data

- [point-level.csv](point-level.csv): all 120 planned attempts and invalid reasons.
- [thresholds.csv](thresholds.csv): every threshold and TP/FP/FN/TN count,
  separately for valid and recoverable populations.
- [comparison.json](comparison.json): all rules, outcome counts and envelopes.
- [RESULTS.md](RESULTS.md): unchanged execution-generated scenario and envelope tables.
- [Design](../design-v0.1.1.json), [runtime](../runtime-v0.1.1.json) and
  [memory overlay](../memory-v0.1.1.yaml).
- [Earlier setup provenance](../execution-provenance.json): cancelled execution,
  never pooled with the corrected runtime.

Recorded execution: run identifier 38072105465; commit
811d1cc046970abf866cdb75a5d6011895de13d7. Downloaded observations are preserved;
Git stores CSV/text with canonical LF line endings. Checksums are in the root
[manifest](../../SHA256SUMS).
