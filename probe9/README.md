# Resource-history observers against a practical forecast

This fixed campaign evaluates three warning methods on the same new runtime
histories. It does not replace or pool previous executions.

- `ilr_history`: the frozen full ILR/Aitchison history observer.
- `share_history`: the same frozen rule using complete raw allocation shares.
- `prometheus_predict_linear`: native forecasts of the four service-requirement
  gauges, using the previously specified practical baseline.

The two primary comparisons are ILR versus Prometheus and raw shares versus
Prometheus. ILR versus shares is a diagnostic comparison of representations,
because those observers otherwise share the same labeled library, business
features, neighbor rule and prospective target.

## Fixed 250-job matrix

The matrix is 25 initial CPU compositions, two fixed workloads and five
repetitions. Every job runs one adaptive and one unchanged-control history;
their order is deterministically balanced 125:125 across the matrix. There are
no replacements or outcome-triggered jobs.

Two closed axes create the 25 compositions. Axis `a` moves CPU jointly between
frontend/checkout and accounting/Kafka at five levels from -0.10 to +0.10.
Axis `b` moves CPU between advertising and product catalog at five levels from
-0.08 to +0.08. RAM and total CPU stay fixed. All allocations remain positive.
The controller continues to transfer exactly 0.04 CPU per accepted step, so
the same absolute action has different relative magnitude across starts.

The allocation policy, external requirements, workload durations, image
digests and frozen resource-history rules remain unchanged. Baseline failures,
invalid jobs and missing jobs remain in the denominator and are not replaced.

## Fixed comparison

All methods ask whether any external requirement will fail in the next two
cycles while the current window is valid and safe. The resource-history rules
emit online predictions during execution. Native Prometheus is run during
aggregation over availability-timestamped raw requirement gauges, with no
access to later samples at each query time.

The primary Prometheus lookback is five minutes; two and ten minutes are fixed
sensitivity checks. Its horizon is 86.962 seconds, fixed from the old median
cycle interval. The primary resource thresholds remain 0.2. All thresholds
previously enumerated during development are retained as secondary operating
points; none is selected from this campaign.

Report first violations warned, misses, false-signal decisions, histories with
false signals, precision and lead time on common forecast coverage. Decision
windows within a history are dependent. The independent runtime scale is the
received runner pairs and their first violations.

This design can show whether either full resource-history observer generalizes
beyond service-trend forecasting, and whether ILR and raw-share histories
differ under varied starts. A whole-rule difference from Prometheus cannot be
attributed solely to geometry because the resource observers also use a frozen
labeled history library.

[Runtime definition](runtime-design-v0.1.0.json) and
[analysis definition](analysis-v0.1.0.json) are immutable inputs to the manual
workflow. Local tests start no services.
