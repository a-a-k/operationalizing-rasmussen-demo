# Practical forecast baseline: what the comparison shows

This is a retrospective replay of the existing twenty-pair confirmation
dataset, not another runtime campaign. Execution 38563585497 used commit
e12535e117665cb85808c11d1332cd21f0ce3012. Original runtime execution 38547221917
and its frozen warning model are unchanged. The
[definition and practical-method sources](../../practical-baseline-v0.1.0.md)
explain why native Prometheus predict_linear is a documented practical forecast
method and what was adapted for this short experiment.

## In plain language

Prometheus looks at the recent measured service results and extends their
linear trend: will checkout become too slow, or will errors/late processing
exceed their existing limits? It does not see which resource allocations led
to those measurements. The frozen ILR rule also sees the resource-allocation
history and consults analogous histories from the old development campaign.
Both are evaluated against the same question: a requirement violation in
either of the next two cycles, while the current measurements remain safe.

The practical forecast method was executed by real Prometheus 3.15.0, not
reimplemented as a custom Python predictor. The time horizon was 86.962 s,
twice the old median cycle interval. Five minutes is the primary history
window; all two- and ten-minute sensitivity results are retained.

| Rule | First violations warned / observed | True signal decisions | False signal decisions |
| --- | --- | ---: | ---: |
| Native Prometheus, primary 5 min | 0/6 | 0 | 7 |
| Native Prometheus, 2 min | 1/6 | 1 | 7 |
| Native Prometheus, 10 min | 0/6 | 0 | 11 |
| Frozen live ILR, threshold 0.2 | 5/6 | 5 | 45 |

Thus the frozen allocation-history rule warned about substantially more of
these events, but with substantially more false signals. That primary
operating point alone does not dominate the baseline. A false signal means
neither of the next two cycles violated a requirement, not that the system
would remain safe forever. Both methods produced zero control-history signals.

## Comparison at lower alarm burden

The earlier development had already enumerated every achievable ILR score
threshold, and the original confirmation already preserved their
[descriptive operating curve](../confirmation-v0.1.0/evaluation/operating-curves.csv).
Those fixed scores can also be inspected at stricter thresholds without
retraining a model or altering the live threshold. All of them, including
disabled and always-alert rules, are shown here rather than selecting just
the favorable point:

| Existing ILR threshold | First violations warned / observed | False signal decisions | Signal precision |
| --- | --- | ---: | ---: |
| Disabled | 0/6 | 0 | NA |
| 0.6 | 2/6 | 2 | 50% |
| 0.4 | 2/6 | 6 | 25% |
| 0.2, frozen live rule | 5/6 | 45 | 10% |
| 0.0, always alert while eligible | 6/6 | 706 | 1.40% |

These [common-mask counts](ilr-fixed-operating-points.csv) reproduce the old
threshold list on exactly the same 716 covered decisions used above. At 0.4
and 0.6 the rule warns about two events versus at most one for these three
Prometheus settings, with fewer false decisions. The two warnings occur about
52 s before the violating windows start. This is an observed favorable
detection/alarm-burden trade-off for the allocation-history predictor on this
dataset, compared with this practical method's specified adaptations.

It is a secondary descriptive comparison, not independent validation of a
newly chosen threshold. The original live threshold remains 0.2. No threshold
is promoted to a new confirmed rule on the strength of this result.

## Boundaries of the interpretation

This is now a comparison with a documented practical forecasting family,
not merely with another variant of our own nearest-neighbor model. It shows
that recent service trends alone did not anticipate most of these constructed
violations, whereas an allocation-history predictor could anticipate some
at lower observed alarm burden. Linear forecasting is intended for relatively
steady trends; abrupt controller-induced changes are an applicability limit.
The adapted SLO gauges and minute-scale settings are not universal vendor defaults.

The comparison does not isolate the ILR geometry. The ILR predictor additionally
uses old labeled histories and resource allocations; Prometheus uses only
service trajectories and no labeled training library. The older full-share
and ILR comparison remains the geometry control. These results therefore do
not establish that only CoDA can give the warnings, that all enterprise
detectors are inferior, or that the stricter threshold will transfer reliably.
There are just six first violations and dependent decision windows. No alert
intervention or production false-alarm cost was measured.

## Coverage, timing and audit trail

There are 756 original eligible decisions. Each history's initial baseline
has only one gauge sample, so Prometheus cannot forecast there: 40 unavailable
points are explicitly excluded for both methods, leaving 716 common points
(10 future-positive and 706 future-negative). All six events retain eligible
forecast opportunities. None of the five original ILR detections or 45 false
signals is removed by this common mask. Unknown futures are never negatives.

Samples use primary-data availability rounded upward to milliseconds. The
[native fixtures](native-checks.json) show a known linear forecast of 0.6 for
both prefix-only and full series despite an extreme future sample, and no
prediction from a one-sample prefix. Baseline lead is an availability-time
replay estimate, not a recorded live Prometheus notification; ILR timestamps
are the original online timestamps.

- [Every native query and response](native-responses.jsonl.gz), with query time,
  labels, lookback and horizon; no Python regression replaces native results.
- [All forecasts, signal labels and future outcomes](decisions.csv).
- [Each first event and warning opportunity](first-events.csv).
- [Machine-readable summary, versions and binary hashes](summary.json).
- [Exact backfilled gauges](inputs.openmetrics), [backfill log](backfill.log)
  and [native server log](prometheus.log).
- [Original runtime evidence](../confirmation-v0.1.0/README.md), including
  independently rescored primary outcomes and unchanged online warnings.

The native binary tarball was checksum-pinned, and archive checks preserve
all raw API responses needed to reproduce the arithmetic without launching
services. New runtime replications were not added or inferred.
