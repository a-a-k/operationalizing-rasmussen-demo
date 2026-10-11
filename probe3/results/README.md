# Completed fixed-endpoint follow-up

All 28 planned runner blocks and 104 point attempts were received. There are
16 complete valid A/B pairs; the six-condition context arm has 8 fully valid
blocks of 12 and 68 valid points of 72. Pairwise context denominators retain
partial blocks when the two compared points are valid.

## Results and meaning

- A was safe in 16/16; radially nearer B was unsafe in 10/16
  (descriptive exact 95% interval 0.3543--0.8480). Reverse contrasts: 0/16.
  Both radial distances lose direction. Nine B points had post-intervention
  failures, retained in the results; timeout-saturated latency is censored.
- Equal-balance service permutations produced different outcomes:
  checkout-low unsafe in 4/11 valid points; payment-low and shipping-low safe
  in 12/12 and 11/11. Matched checkout/payment discordances: 4/11;
  checkout/shipping: 3/10, with zero reverse discordances.
- With checkout quota, group sum and reduced count fixed, anchor/payment-low
  had five safe/unsafe contrasts in ten valid pairs. A balance distinguishes
  this pair, but that does not demonstrate predictive superiority.
- Balanced versus concentrated reductions include reverse outcomes. Every
  direction, technical-invalid point and recoverable outcome remains visible.

These are representational witnesses, not a temporal adaptation history,
held-out detector evaluation or isolated CPU-only failure experiment.
The scalar group balance also loses service identity; the full allocation
vector retains it. This series is never pooled with historical Probes 1--2.

## Data

- [summary.json](summary.json): exact intervals, valid/recoverable populations,
  every point and both contrast directions.
- [point-level.csv](point-level.csv): all 104 attempts, outcomes, validity,
  counters, summaries and diagnostics.
- [block-level.json](block-level.json): unchanged downloaded block inputs for
  replaying the original aggregation; not a substitute for native raw streams.
- [RESULTS.md](RESULTS.md): unchanged execution-generated tables.
- [Design](../design-v0.1.1.json) and [runtime](../runtime-v0.1.1.json).
- [Setup-attempt provenance](../execution-provenance.json), kept separate.

Recorded execution: run identifier 38058045576; commit
56b1404dbe21776ee410c55eab1d6a6e12cfcd8f. These are provenance identifiers,
not identifying source-hosting links. Downloaded observations are preserved;
Git stores CSV/text with canonical LF line endings. Checksums are in the root
[manifest](../../SHA256SUMS).
