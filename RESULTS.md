# Results and interpretation

## Evolving state and current constraints

The separate [eight-history runtime campaign](evolving-state/results/campaign-v0.1.1/README.md)
observes a retry adaptation, actual forwarding-component updates and policy
edits. All 304 available updated group assessments matched the event oracle.
Five policy-status changes occurred at unchanged measured counts. The recorded
benefit/work trade-off includes 667 calls rescued by a third attempt after two
failures under controlled delivery faults. Updated direct ratios and CoDA
matched; the advantage over a stale schema concerns the updating measurement
contract, not uniquely better policy detection by CoDA.

The [retrospective directional extension](evolving-state/results/campaign-v0.1.1/directional-v0.1.0/README.md)
adds conditional boundary diagnosis. Of 85 reports with available direction
and both policies satisfied, 51 latest-increment rays and 52 smoothed rays
intersect a current policy boundary. Independent continuation in the original
parts agrees in all 119 available calculations per direction. Thirty matched
local-state pairs have opposite latest directions; 26 pairs satisfy both
policies in both observations. These are overlapping descriptive observations,
not independent trials, forecasts of actual crossings, or an accuracy advantage
over an updated direct method using the same history and path.

The closed-resource evidence below is a separate set of experiments.

The evidence supports a measurement model for closed resource adaptation:
complete selected allocation state, consistent relative-drift geometry, and
histories joining pressure, actions, recipient output and external outcomes.
Runtime observations, representational witnesses, mathematical checks and
exploratory detector comparisons have distinct roles.

## Position and movement: separate saved-data readout

[Trajectory observability v0.1.0](drift-monitor/trajectory-observability/README.md)
replays all 988 guarded-adaptation windows and the same 250 selected continuous
runner pairs. At four quota holds, consumption still moved. At five quota
restorations, consumption moved closer to its reference without exactly
returning; the next measured windows satisfied the original requirements.
The guarded generators were intermittent, so these episodes do not establish
recovery under continuous load.

In the separate continuous archive, relative path coherence over windows 5–16
was higher during reallocation in 224/250 pairs (medians 0.160 versus 0.079;
paired mean difference 0.0786, descriptive paired-bootstrap 95% interval
[0.0709, 0.0864]). This describes directional accumulation, not safety or an alarm.

Controlled rename/split/merge replay preserves both detailed semantic-service
and canonical-group trajectories with supplied lineage. A separate within-group
transfer leaves the canonical channel unchanged but changes the detailed state.
These are explicitly synthetic transformations of measured source paths, not
new architecture events or measured counterfactual SLO outcomes.
See the [complete example](drift-monitor/trajectory-observability/results/v0.1.0/full-history-v0.1.0.png),
[event table](drift-monitor/trajectory-observability/results/v0.1.0/adaptation-events.csv)
and [machine summary](drift-monitor/trajectory-observability/results/v0.1.0/summary.json).

## Independent online warnings: real lead, substantial false-alarm burden

[The separate confirmation](probe8/results/confirmation-v0.1.0/README.md)
applied four rules frozen from earlier saved-data development to twenty new
runner pairs. All forty histories had safe baselines and completed twenty
cycles; all 840 windows were valid. Six adaptive histories violated checkout
requirements, two also accounting; controls stayed safe. All live predictions
replayed, and every external outcome was independently rescored from primary
inputs. No confirmation data entered fitting or threshold selection.

| Frozen rule | First violations warned | False decisions | True signals / all signals |
| --- | ---: | ---: | ---: |
| Full ILR history | 5/6 | 45 | 5/50 (10.0%) |
| Euclidean share history | 4/6 | 38 | 4/42 (9.52%) |
| Selected local history | 2/6 | 6 | 2/8 (25.0%) |
| Service indicators | 2/6 | 3 | 2/5 (40.0%) |

All credited signals preceded the violating window by about 52 seconds, while
current requirements still held. Thus a fixed compositional-history observer
can emit a genuinely prospective warning in these constructed conditions.
The observer never changes donor selection or rollback. This is a different
task from the older one-step headroom-change analogy exercise below.

Nine of ten ILR signals were false for the chosen two-cycle target. Relative
to Euclidean share history, one extra event was warned at the cost of seven extra false
decisions: not established practical superiority. Moreover, the secondary
pre-enumerated score curves show that a lower local threshold would also catch
five events with 43 false decisions. The primary 5/6 versus 2/6 therefore does
not prove the necessity of full-state prediction. No threshold is refitted.

Evidence: [all decisions](probe8/results/confirmation-v0.1.0/evaluation/warning-decisions.csv),
[first-event lead times](probe8/results/confirmation-v0.1.0/evaluation/first-violation-events.csv),
[fixed-score curves](probe8/results/confirmation-v0.1.0/evaluation/operating-curves.csv),
[full history records](probe8/results/confirmation-v0.1.0/evaluation/block-level.json)
and [primary-input audit](probe8/results/confirmation-v0.1.0/primary/README.md).
Decision windows are dependent; the six events and twenty runner pairs remain
the visible independent-execution scale, not hundreds of independent trials.
Operational usefulness and benefits of acting on a signal remain open.

## Native practical forecast replay: comparison beyond custom model variants

The [separate replay](probe8/results/prometheus-baseline-v0.1.0/README.md)
compares the unchanged warning scores with native Prometheus predict_linear,
a forecasting method documented for advance resource-limit alerts. Its
adaptation forecasts the four original requirement gauges over 86.962 s.
No new runtime histories or training inputs are added. The primary five-minute
lookback and both specified sensitivity lookbacks remain visible.

At 716 shared decisions, Prometheus warned 0/6, 1/6 and 0/6 events for five-,
two- and ten-minute lookbacks, with 7, 7 and 11 false decisions. Frozen live
ILR warned 5/6 with 45 false decisions, so its primary operating point
trades higher event coverage for substantially higher alarm burden.

The already enumerated ILR thresholds additionally yield 2/6 warned events
with 2 false decisions at 0.6 or 6 false decisions at 0.4. These descriptive
points have a favorable observed trade-off against the specified practical
forecasts. Every threshold is retained; no favorable point is promoted to
a newly confirmed live rule. Native results, unavailable predictions and
common-mask accounting are replayable from the committed API responses.

The result is a retrospective whole-rule comparison, not a geometry-only
comparison or a claim about all enterprise detectors. The ILR rule also has
a labeled allocation-history library. Short irregular trajectories and
controller actions limit simple linear forecasting. Baseline leads are replay
estimates; original ILR signals retain their actual online timestamps.

## Guarded full-stack adaptation: three externally measured requirements

The separate [guarded follow-up](probe7/results/main-v0.2.0/README.md) received
24 runner pairs and 988 technically valid evaluation windows. A controller
selected CPU donors from observed requirement headroom and resource pressure,
then measured and rolled back unsafe/near-boundary changes. It used no CoDA
coordinate and prescribed no crossing. RAM differed across initial contexts
but stayed fixed within each history because commissioning did not establish
useful recipient RAM benefit.

Twenty-three pairs had safe baselines and complete twenty-cycle histories.
The remaining control stopped after baseline checkout p95=559.2 ms; its outcome
and completed adaptive counterpart remain in the archive. At the fixed final
cycle, advertising baseline-adjusted gain over control was positive in 23/23
pairs, median +2105.4 responses/s. Checkout p95 and accounting observed p99 lag
each increased in 21/23 contrasts (medians +45.8 ms and +55.4 ms).

Seven adaptive histories violated checkout requirements, four also accounting
timeliness; their 23 matched controls stayed safe. Advertising stayed within
its timeliness policy in all 988 evaluation windows. Eight transfers were
rolled back, and two final adaptive windows remained unsafe. These are
constructed, guarded adaptation histories, not a production failure rate.

Five overlapping post-hoc comparisons had identical selected local ratios,
different complete allocations and safe/unsafe outcomes under the same initial
context and workload. Full shares and full ILR both preserve those allocation
distinctions. They do not establish the causal source of the outcome difference.

The separate [accumulated-history analysis](probe7/results/accumulated-v0.1.0/README.md)
strengthens the descriptive witness: three interactive/busy histories had
identical selected traces at every epoch from baseline through cycle 6, not
merely identical endpoints. Checkout p95 at that cycle was 609.3 ms versus
120.5 and 294.0 ms, with different database/Kafka CPU allocations. These are two
overlapping comparisons sharing one unsafe run, not independent causal effects.
Full raw shares and full ILR both retain the differing paths. Median per-history
median cumulative displacement energy outside the selected projection was
78.1%; that is not a missed-alert rate.

Actual first accounting-to-ad transfers also illustrate the geometry: each
moved 0.04 CPU, producing identical additive share changes but donor losses of
11.4%, 16.0% and 26.7% across initial states. Full relative movement distinguishes
those proportional changes. All three endpoints were safe; a larger distance is
not assigned a larger risk. Separate unexecuted multiplier checks verify known
relative invariance and never receive business-outcome labels.

Held-pair-out analog retrieval did not favor ILR over complete raw shares:
macro pair mean absolute headroom-change errors were 0.4312 for three selected
ratios, 0.3860 for full shares and 0.4120 for full ILR. Per-process errors and
conditional descriptive uncertainty are reported, not detector superiority.
The new saved-data diagnostic of predicting no headroom change had lower
aggregate error, 0.2691, than all three analogy methods. Their different tie
counts also couple metric choice with neighbor averaging. This is an additional
consequence-prediction exercise, not a test of cumulative-history completeness.

Evidence: [complete interpretation](probe7/results/main-v0.2.0/README.md),
[all windows](probe7/results/main-v0.2.0/windows.csv),
[paired epochs](probe7/results/main-v0.2.0/paired-epochs.csv),
[all analogs](probe7/results/main-v0.2.0/neighbors.csv),
[projection comparisons](probe7/results/main-v0.2.0/projection-witnesses.csv),
[aggregate](probe7/results/main-v0.2.0/summary.json) and
[prespecified history](probe7/results/main-v0.2.0/example.svg).
The new analysis preserves [all accumulated windows](probe7/results/accumulated-v0.1.0/history-windows.csv),
[complete prefix witnesses](probe7/results/accumulated-v0.1.0/prefix-witness-history.csv),
[actual transfer examples](probe7/results/accumulated-v0.1.0/actual-transfer-examples.csv),
[separate diagnostics](probe7/results/accumulated-v0.1.0/secondary-diagnostics.csv), and
[the full interpretation](probe7/results/accumulated-v0.1.0/README.md).

## Sequential CPU migration: competing outcomes before and at crossing

[Probe 5](probe5/) planned 20 fresh runners, each with two fresh-stack histories
in balanced order. Runtime state persisted within each history. Starting at
(checkout, payment, shipping, ad) = (.30,.30,.30,.10), each adaptive decision
moved .04 CPU to advertising from a cyclic donor. The gate used preceding safe
checkout performance and positive advertising CPU throttling.

Checkout received 40 scheduled operations/s; advertising used eight closed-loop
VUs. Advertising goodput is successful nonempty responses/s, not revenue.
The competing workloads have different semantics.

| Observation | Result |
| --- | --- |
| Planned / received runner pairs | 20 / 19; one outcome unknown |
| Adaptive SLO crossings | 19/19 received, at steps 8--13 |
| Unsafe unchanged controls | 0/19; controls observed through step 18 |
| Moves increasing / decreasing recipient goodput | 198 / 16 of 214 |
| Recorded restart/OOM measurement windows | 0 |
| Median baseline-adjusted goodput gain over control at first crossing | +1718.1 responses/s |

### Retrospective comparison at step 6

Step 6 completes two donor cycles and was selected retrospectively. For each
metric and pair the contrast is:
(adaptive_step6 - adaptive_baseline) - (control_step6 - control_baseline).

All 19 pairs were technically valid and both histories remained SLO-safe.
Adaptive allocations were (.22,.22,.22,.34).

| Control-adjusted change | Median | Range | Positive pairs |
| --- | ---: | ---: | ---: |
| Advertising goodput (responses/s) | +863.9 | +723.9 to +1964.9 | 19/19 |
| Checkout p95 (ms) | +47.1 | +6.8 to +155.3 | 19/19 |

Useful recipient gains accompanied checkout deterioration while the external
SLO still held. Every received adaptive history later crossed the boundary;
unchanged controls stayed safe. This is a constructed runtime analogue of
locally useful adaptation accumulating toward an acceptability boundary.

Step-6 selection is retrospective; first-crossing contrasts are outcome-selected.
Neither is an isolated transfer's causal effect or a validated predictor.
The prescribed path also allows a local quota or step index to encode progress.

Evidence: [every window](probe5/results/trajectory-level.csv),
[paired epochs](probe5/results/paired-epochs.csv),
[aggregate](probe5/results/summary.json),
[step-6 inputs and contrasts](probe5/results/history-v0.1.0/step6-pairs.csv),
[full ILR history](probe5/results/history-v0.1.0/ilr-history.csv), and
[execution provenance / missing runner](probe5/results/README.md).

## CPU/RAM histories: joint resource context

The separate [Probe 6 follow-up](probe6/JOINT_RESOURCES_v0.2.0.md) received all
20 four-history blocks: control, CPU-only, RAM-only and joint. Each step moved
.03 CPU and/or 4 MiB from checkout to advertising within separately closed
budgets. Engineering checks informed the RAM range but are not campaign data.

Five blocks had a matched joint-unsafe step with safe control, CPU-only and
RAM-only histories: 5/20, descriptive exact 95% interval 8.7--49.1%.
Crossings: joint 20/20, CPU-only 14/20, RAM-only 17/20, control 0/20.
CPU-only crossed earlier than joint in one block.

Block 020, step 5:

| History | Checkout CPU | RAM MiB | p95 ms | Unsuccessful operations | SLO |
| --- | ---: | ---: | ---: | ---: | --- |
| Control | .30 | 48 | 106.5 | 0/2400 | Safe |
| CPU-only | .15 | 48 | 206.6 | 0/2400 | Safe |
| RAM-only | .30 | 28 | 109.7 | 0/2400 | Safe |
| Joint | .15 | 28 | 192.0 | 48/2400 | Unsafe |

The same local CPU value and the same local RAM value each occurred with safe
and unsafe outcomes. Their joint context matters. Different preceding
allocations and queue states prevent interpreting this as an isolated factorial
causal interaction or a general safety-region topology.

At joint first crossings, baseline-adjusted advertising gains over control
were positive in all 20 blocks (median +671.1 responses/s). RAM-only step-6
contrasts were weaker: median +2.8, range -124.3 to +113.0, 13 positive and
seven negative. CPU pressure is weak motivation for RAM-only transfers when
extra RAM yields little recipient benefit.

Evidence: [interpretation / engineering provenance](probe6/results/README.md),
[all windows](probe6/results/joint-v0.2.0/trajectory-level.csv),
[complete and incomplete steps](probe6/results/joint-v0.2.0/four-way-epochs.csv),
and [aggregate](probe6/results/joint-v0.2.0/summary.json).

## Geometry: complete state and comparable relative drift

Full ILR recovers the selected positive composition. CPU's four parts require
three coordinates; RAM's two parts require one. A balance is one projection.
CPU and RAM remain separate compositions; budgets and workload remain context.

Applying equal positive multiplicative factors and closing the budget gives
the same full ILR displacement at different starts. Six synthetic checks
reproduced this known property. Aitchison distance was constant (CPU 0.790041;
RAM 0.776836), while Euclidean share distance varied (CPU 0.130375--0.156347;
RAM 0.029149--0.057645). Euclidean share distance still measures additive change.
Equal relative movement does not imply equal SLO consequences.

All 594 CPU and 551 CPU/RAM source windows are retained separately with original
labels and validity. These dependent windows are not 1,145 independent
replications. Synthetic endpoints have no SLO labels. Product-metric weights
are declared conventions, not calibrated risk weights.

Evidence: [definitions](geometry/README.md),
[properties](geometry/results/v0.1.0/metric-properties.csv),
[full coordinates](geometry/results/v0.1.0/trajectory-coordinates.csv),
[verification](geometry/results/v0.1.0/summary.json), and
[figure / interpretation](geometry/results/v0.1.0/RESULTS.md).

## Fixed endpoints: limits of scalar reductions

The corrected [Probe 3](probe3/results/README.md) enforced the generator gate.
All 28 blocks and 104 point attempts were received. The 16 valid A/B pairs
showed farther A safe in 16/16 and nearer B unsafe in 10/16; both radial
distances lost direction. Nine B points had post-intervention failures,
retained as diagnostics. Timeout-saturated latency is censored.

Permuting (.15,.24,.24) over the functional services with ad at .37 preserves
the group balance, sum, minimum and both radial distances. Checkout-low was
unsafe in 4/11 valid points; payment-low and shipping-low were safe in 12/12
and 11/11. Matched discordances were 4/11 and 3/10 with no reverse contrasts.
This demonstrates loss of service identity in scalar summaries, including
the chosen balance. Full coordinates retain those distinctions; their
predictive usefulness was not evaluated here.

Evidence: [point outcomes / invalid reasons](probe3/results/point-level.csv),
[block inputs](probe3/results/block-level.json),
[intervals and both contrast directions](probe3/results/summary.json), and
[generated tables](probe3/results/RESULTS.md).

## Threshold comparison: retain the unfavorable result

[Probe 4](probe4/results/README.md) had 109 valid points of 120 attempts.
Eleven baseline/pre-intervention failures remain in the table. Thresholds were
selected and evaluated in-sample, separately at each load. Local OR exhausts
independent service cutoffs and is more flexible than one balance threshold.

| Load | Unsafe / valid | Balance detections at zero observed false alarms | Local OR detections |
| --- | ---: | ---: | ---: |
| 40/s | 33/60 | 10/33 | 30/33 |
| 64/s | 39/49 | 22/39 | 30/39 |

The scalar balance did not outperform local OR on these scenarios. This is not
a comparison of full ILR with equally capable raw-share predictors. In-sample
envelopes are descriptive, not held-out alert performance. There is no binary
scientific success criterion.

Evidence: [all 120 records](probe4/results/point-level.csv),
[every threshold](probe4/results/thresholds.csv),
[rules and envelopes](probe4/results/comparison.json), and
[complete tables](probe4/results/RESULTS.md).

## Historical evidence and the overall conclusion

Original Probes 1--2 are separate in
[historical-endpoints.md](docs/historical-endpoints.md), including the omitted
generator gate, conditional sensitivity, restarts, timeouts and pilot selection.
Their counts are not combined with follow-ups.

The evidence supports full allocation histories and relative-drift geometry
with consequences measured externally. It does not establish universal alert
superiority, causality from geometry, production prevalence or an allocation-only
prediction of acceptability. Budget-aware observability integration, snapshot
correctness, overhead and diagnostic usefulness are concrete next evaluations.
