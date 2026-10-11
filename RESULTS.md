# Results and interpretation

The evidence supports a measurement model for closed resource adaptation:
complete selected allocation state, consistent relative-drift geometry, and
histories joining pressure, actions, recipient output and external outcomes.
Runtime observations, representational witnesses, mathematical checks and
exploratory detector comparisons have distinct roles.

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
