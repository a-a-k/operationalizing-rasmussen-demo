# Practical forecast-method comparison

Version 0.1.0. Saved-data replay only; no runtime expansion, controller change
or frozen-model revision. [Machine-readable definition](practical-baseline-v0.1.0.json).

## Why this method is a practical baseline

Prometheus implements [predict_linear](https://prometheus.io/docs/prometheus/latest/querying/functions/#predict_linear)
as simple linear regression on gauge samples with a forecast horizon in seconds.
It requires at least two float samples. Grafana documents
[forecast-threshold alerting](https://grafana.com/docs/grafana-cloud/observe-and-act/alert-and-measure-reliability/alerting/guides/alerting-on-forecasts/)
for advance warning about resource limits. A concrete deployed-rule example is
Google Cloud's documented
[NodeFilesystemSpaceFillingUp](https://docs.cloud.google.com/stackdriver/docs/managed-prometheus/exporters/node_exporter),
using native predict_linear and disk-space thresholds.

That establishes the provenance of the forecasting method, not a universal SLO
default. The four gauges below, short lookbacks, forecast horizon and absence
of a persistence delay are explicit adaptations to these recorded processes.
No assertion is made that a disk-capacity rule is unchanged or optimal here.
Grafana's steady-trend assumption matters: these short trajectories contain
noise and controller-induced changes. This is a check of a documented practical
method under those conditions, not every enterprise monitoring system or SOTA.

## Exact comparison

Both rules target a violation of any requirement in the next two cycles,
at currently valid, safe windows. The unchanged ILR rule uses its frozen
threshold 0.2 and previously emitted online labels. No new allocation model
is trained. Prometheus extrapolates these original raw gauge values:

| Gauge | Predicted failure |
| --- | --- |
| Checkout request p95 | >500 ms |
| Checkout unsuccessful-operation fraction | >=0.01 |
| Advertising timely fraction | <0.99 |
| Accounting timely fraction | <0.99 |

The forecast warning is the OR of those four comparisons, with no persistence
delay. Samples are timestamped when all primary measurements became available,
rounded upward to integer milliseconds, never at window start or midpoint.
Missing samples are neither interpolated nor repeated. Native PromQL cannot
access any sample after its query timestamp, even though the replay TSDB
contains the complete dataset. A native known-trend fixture tests this cutoff
by inserting an extreme future sample and comparing it with a prefix-only series.

The horizon in seconds is twice the pooled median spacing of consecutive valid
nonbaseline advertising windows in the old development campaign. Only old
timestamps set it; future confirmation timing and labels do not. This is a
fixed time approximation to two cycles, not knowledge of their future duration.
The primary lookback is five minutes. Two- and ten-minute sensitivity checks
are all retained, without choosing a best result. These are short-history
engineering settings, not claimed vendor defaults. Parameters are specified
before native baseline results, but after seeing the source confirmation data:
the comparison is retrospective, not a new independent confirmatory test.

At least two samples and a finite prediction for each gauge are required. Unavailable
forecasts are reported, not coded as silence. For each lookback, compare ILR
and Prometheus on the identical covered decisions, retaining the original full
ILR counts separately. First events count only warnings within two cycles and
before the first violating window begins. A baseline lead is estimated from
recorded availability time; it is not an actual live Prometheus notification.

Report first violations warned/missed, false decisions, precision and lead,
including unchanged controls. Dependent windows are not independent trials.
No pass/fail number, significance claim or outcome-selected threshold is added.
More detections at much higher alarm burden alone is not superiority. The ILR
rule additionally has an old labeled-history library: any difference is a
whole-rule comparison, not isolation of the geometry alone.

## Execution and audit trail

The [manual workflow](../.github/workflows/practical-forecast-replay.yml) runs
the checksum-pinned native Prometheus/promtool 3.15.0 binaries. It backfills
the unchanged records using OpenMetrics and evaluates native predict_linear
through the HTTP API, not a Python reimplementation of regression. Stored
queries/responses, predictions, coverage flags, event rows, version/binary
hashes and synthetic fixture responses make the replay inspectable.

Local unit tests check only adapters and accounting; they start no server.
Original runtime observations, frozen rules and primary outcome scoring
remain unchanged. This replay adds no independent replication to any campaign.
