# Resource-history observers with matched and practical controls

This fixed campaign recorded four frozen warning methods on the same new
runtime histories. It does not replace or pool previous executions.

- `ilr_history`: the frozen full ILR/Aitchison history observer.
- `share_history`: the same frozen rule using complete raw allocation shares.
- `service_indicators`: the same frozen nearest-history rule and labeled
  library, using only service headrooms and their last observed changes.
- `prometheus_predict_linear`: native forecasts of the four service-requirement
  gauges, using the previously specified practical baseline.

The matched comparison is each complete allocation-history observer versus
`service_indicators`. This holds the labeled library, service context, neighbor
rule, target and threshold-selection procedure constant while changing whether
the complete CPU/RAM allocation prefix is available. Prometheus remains a
separate practical reference; it is not a matched learned control. ILR versus
shares is a diagnostic comparison of representations.

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

## Fixed comparisons

All methods ask whether any external requirement will fail in the next two
cycles while the current window is valid and safe. All three frozen
nearest-history rules, including `service_indicators`, emitted online
predictions during execution. The matched-control table was aggregated after
the campaign from those recorded predictions without refitting a model or
selecting a threshold. Native Prometheus was run during aggregation over
availability-timestamped raw requirement gauges, with no access to later
samples at each query time.

The primary Prometheus lookback is five minutes; two and ten minutes are fixed
sensitivity checks. Its horizon is 86.962 seconds, fixed from the old median
cycle interval. The primary resource thresholds remain 0.2. All thresholds
previously enumerated during development are retained as secondary operating
points; none is selected from this campaign.

Report first violations warned, misses, false-signal decisions, histories with
false signals, precision and lead time on common forecast coverage. Decision
windows within a history are dependent. The independent runtime scale is the
received runner pairs and their first violations.

The matched control can show what complete allocation history adds to the same
learned warning mechanism. The practical comparison can show whole-rule
behavior against a documented service-trend forecast, but that difference
cannot be attributed solely to resource history or geometry.

## Completed result

All 250 fixed jobs and the aggregate completed without a technical failure or
replacement. Of 500 histories, 483 began safe and completed; 104 had a first
post-baseline violation.

At their pre-frozen thresholds, the matched service-only observer warned before
6/104 first violations. ILR history warned before 44/104 and complete raw-share
history before 41/104. Every event warned by the service-only observer was also
warned by both allocation-history observers; ILR added 38 and shares added 35
event-level warnings. This sensitivity came with a larger false-signal burden:
33 histories for the service-only observer, 106 for ILR and 98 for shares.
Consequently the result shows additional warning information in allocation
history under the frozen rules, not unconditional detector dominance at an
equal achieved false-signal rate. See the [matched-control
result](results/service-control-v0.1.0/RESULTS.md).

In the separate practical comparison, ILR warned before 44/104, complete raw
shares before 41/104, and the five-minute Prometheus forecast before 0/104.
At the pre-specified stricter resource threshold and two-minute Prometheus
sensitivity setting, the observed trade-off was much closer: 11/104 for each
resource observer versus 10/104 for Prometheus, with comparable false-signal
burden.

The adaptive/control contrast supports the drift interpretation: among 237
jointly eligible pairs, 89 violated a requirement only under adaptation, 4 only
under control, 3 under both, and 141 under neither. Neither allocation-history
observer signaled in unchanged controls.

The campaign supports retaining complete allocation history when the objective
is to warn about adaptation-induced drift. It does not show that ILR predicts
better than complete raw shares. See the [practical comparison and
plain-language interpretation](results/generalization-v0.1.0/RESULTS.md).

[Runtime definition](runtime-design-v0.1.0.json) and
[analysis definition](analysis-v0.1.0.json) are immutable inputs to the manual
workflow. The [matched-control definition](service-control-v0.1.0.json) pins the
retrospective aggregation inputs. Local tests start no services.
