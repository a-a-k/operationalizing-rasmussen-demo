# Accumulated allocation histories: interpretation and evidence

This is a versioned retrospective analysis of the completed
[guarded campaign](../main-v0.2.0/README.md), not a new runtime experiment.
It changes neither controller decisions nor external outcome labels. The
[definition](../../accumulated-analysis-v0.1.0.json) pins its source files.
Saved-data execution 38528873748 used commit
b17978672f5e528d11ad466e4b5d577cdfabe51a and started no services.

## What the measurement question is

The question is how to describe the joint, accumulated allocation change when
selected local relations hide part of that change. Prediction is a separate
question. We retain each initial CPU/RAM allocation, each subsequent relative
state, the decisions and reversals, and the measured margin to each requirement.

Eleven positive CPU allocations are normalized within their 3.4-CPU budget;
eleven RAM allocations within their 4544-MiB budget. These are two compositions,
not CPU and RAM numbers added together. A complete state has ten ILR coordinates
per resource. Each window's displacement is its twenty-coordinate state minus
its own measured baseline state. Initial allocations and absolute budgets are
retained: displacement alone is not the complete current allocation.

The cumulative vector is the sum of consecutive displacement vectors. We
also retain the entire sequence: returning to baseline gives zero net movement,
but does not erase the earlier transfers, unsafe trial or rollback. Discrete
path lengths distinguish observed allocation vertices from the commanded
rollback vertices. A command has no inferred business outcome if it was not
followed by another measurement window.

This observer supplies a consistent relative description of an adaptation
history. It does not identify a universal direction of danger, assign an SLO
from a distance, or determine the cause of a particular failure.

## 1. Guarded adaptation produced a real operational trade-off

The source received all 24 runner pairs, 48 attempted histories and 988 windows.
One unchanged control was already unsafe at baseline and stopped; its records
and adaptive counterpart remain present. Fixed-cycle paired contrasts therefore
have 23 complete, baseline-safe pairs. Nothing is pooled with other probes.

The adaptive controller chose CPU donors from preceding measured requirement
headroom and resource pressure, gave CPU to advertising, measured the result,
and reversed unsafe/near-boundary changes. CoDA was not an input to this policy,
and a crossing was not required by the controller.

At the fixed cycle 20, changes from each history's own baseline were compared
with the same changes in its unchanged control:

| Quantity | Median control-adjusted change | Direction across pairs |
| --- | ---: | --- |
| Advertising nonempty-response goodput | +2105.4 responses/s | Increased in 23/23 |
| Checkout latency margin, 500 ms minus request p95 | -45.8 ms | Decreased in 21/23 |
| Accounting observed-p99 delay margin | -55.4 ms | Decreased in 21/23 |

Seven matched adaptive histories had an unsafe window, compared with none of
their matched controls; four also violated accounting timeliness. Advertising
stayed timely in all 988 windows. Two adaptive histories ended at unsafe trials
with recorded rollback commands but no subsequent window. They are not reported
as recovered. Not every transfer increased advertising output, and not every
history violated a requirement.

These observations instantiate a guarded adaptation process in which useful
recipient gains coexist with reduced margins and occasional externally measured
violations elsewhere. They do not measure production prevalence or isolate the
causal effect of each individual transfer.

Each requirement keeps its own units and membership rule. Checkout also requires
an unsuccessful scheduled-operation fraction strictly below 1%; its p95 panel
alone is not the entire SLO. Advertising and accounting require at least 99%
timely attempts/orders. Accounting's observed p99 is conditional on committed
records and is diagnostic: late and missing orders still enter the timely
fraction. A recipient gain does not offset a violated requirement.

Evidence: [every cumulative window](history-windows.csv),
[all trajectories and command endpoints](trajectory-level.csv),
[all paired epochs](paired-epochs.csv),
[fixed-endpoint descriptive intervals](summary.json), and
[the original fixed example](history.svg). The example was selected before the
runtime campaign; the new analysis has not replaced it with a favorable history.
Intervals resample runner pairs, not dependent windows, and describe only these
designed conditions.

## 2. Even the entire selected local trace can hide a difference

The selected local coordinates are CPU checkout/payment, CPU frontend/ad and
RAM accounting/Kafka, each log-scaled by 1/sqrt(2). A descriptive search of all
received histories found three interactive/busy runs whose selected traces
coincide at every epoch from baseline through cycle 6. The full allocations do
not coincide. At that cycle:

| Runner suffix | Checkout CPU | Frontend CPU | Ad CPU | Accounting CPU | Database CPU | Kafka CPU | Checkout p95 | Outcome |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 01 | .55 | .55 | .49 | .11 | .38 | .22 | 609.3 ms | Unsafe |
| 02 | .55 | .55 | .49 | .11 | .34 | .26 | 120.5 ms | Safe |
| 03 | .55 | .55 | .49 | .11 | .42 | .18 | 294.0 ms | Safe |

RAM is unchanged and identical in these three initial contexts. Both advertising
and accounting remained timely at this displayed cycle. The checkout boundary
is 500 ms. Thus selected traces alone cannot distinguish these observed
allocation histories, even though their full paths and observed outcomes differ.
This is stronger than comparing only equal local endpoints.

These are **two overlapping comparisons sharing one unsafe run**, not two
independent replications or evidence that the database/Kafka split caused the
latency difference. Different runners, queue histories and noise remain possible
contributors. Full raw shares and full ILR both preserve the allocation
distinctions; no uniquely CoDA-based predictor is established by this witness.

Across adaptive histories, the median of per-history median cumulative
displacement energy outside these three orthonormal coordinates is 78.1%.
Zero-displacement windows have no defined energy fraction. This measures loss
of allocation information in a chosen projection, **not a missed-alert rate**.
It differs from the earlier 88.7% calculation on individual adjacent transfers.

Evidence: [all equal-prefix comparisons](prefix-witnesses.csv),
[every epoch of the three witnessed prefixes](prefix-witness-history.csv),
[their figure](prefix-witness.svg), and
[all five overlapping endpoint comparisons](endpoint-witnesses.csv).
The witnesses were found retrospectively; there is no statistical success threshold.

## 3. Why relative geometry differs from Euclidean changes in full shares

Full shares are compositional data too. Their information is not inherently
inferior to ILR: both retain a complete selected allocation. The distinction is
the geometry used to compare changes, not access to extra measurements.

The first transfer of repetition 1 at moderate load in each initial context
really moved the same 0.04 CPU from accounting to advertising. Advertising
started at .25 CPU and ended at .29 in all three cases:

| Initial context | Accounting before / after | Loss relative to its starting allocation | Euclidean full-share displacement | Full relative displacement |
| --- | --- | ---: | ---: | ---: |
| Ledger | .35 / .31 | 11.4% | .01664 | .19155 |
| Balanced | .25 / .21 | 16.0% | .01664 | .22884 |
| Interactive | .15 / .11 | 26.7% | .01664 | .34036 |

The complete additive share-change vector is identical: accounting loses
0.04/3.4 = 1.176 percentage points, advertising gains the same, and other shares
do not change. That vector measures the same absolute transfer. Full ILR changes
distinguish its different proportional meaning at different starts. Keeping
the starting raw shares also permits deriving those percentages: CoDA offers
an established, systematic relative geometry, not otherwise inaccessible data.
All three measured endpoints were safe, so this example does not establish
that a larger relative displacement implies greater SLO risk.

The examples were selected retrospectively for illustration, not as a
predeclared scientific endpoint. See [actual transfers](actual-transfer-examples.csv).

Separately, we applied the same positive multiplier vector from the balanced
transfer to each starting composition, then closed the budgets. These
**unexecuted mathematical checks have no SLO labels**. Full relative vectors
and their norm coincide (.22884); Euclidean share-change norms range from
.01356 to .02020. This checks a known invariance:

```text
x' = closure(x * u)
ILR(x') - ILR(x) = ILR(closure(u))
```

Multiplication is componentwise and closure is applied separately to each
resource. A common multiplier does not imply a common business consequence.
The calculation verifies known CoDA properties and this implementation, not
a new theorem or a detector advantage.

Evidence: [unexecuted relative-update checks](relative-update-checks.csv) and
[inverse/accumulation numerical verification](summary.json).

## 4. The additional analogy task did not show predictive superiority

The original comparison is retained unchanged: use a single adjacent
displacement to retrieve nearest displacements outside the entire query runner
pair, match workload and both window durations, then predict changes in three
normalized controller headrooms. It does not use the entire starting allocation,
the cumulative history or internal runtime state.

| Method | Macro pair mean absolute error | Median nearest neighboring pairs |
| --- | ---: | ---: |
| New retrospective no-headroom-change diagnostic | .2691 | Not applicable |
| Original three selected log-ratio changes | .4312 | 10 |
| Original Euclidean full-share changes | .3860 | 11 |
| Original full ILR changes | .4120 | 2 |

Lower error is better for this task. All three analogy procedures had higher
aggregate error than simply predicting no headroom change. This diagnostic
was added after execution and is not a newly tested online alert. Large
accounting headroom changes dominate the aggregate, and per-process errors
remain available. Different geometries also produce different tie counts:
raw-share retrieval averages many more neighbors, coupling distance choice
with smoothing. This comparison does not cleanly isolate their effects.

Consequently the analogy exercise does not demonstrate ILR predictive
superiority and is not the verdict on accumulated relative-drift measurement.
The information-loss witnesses and relative geometry have their own, different
evidence above. Neither is presented as superior alert sensitivity or false
positive rate.

Evidence: [all diagnostic errors and their origin](secondary-diagnostics.csv),
[original matching candidates](../main-v0.2.0/neighbors.csv),
[original queries](../main-v0.2.0/sections.csv), and
[unchanged original aggregate](../main-v0.2.0/summary.json).

## Reproduction and limits

Only CPU moved within these histories. RAM is an initial context, not an
experimentally varying drift direction. Twenty coordinates describe the
selected state space, not twenty exercised directions. Allocations are configured
ceilings, not reserved or consumed resource quantities. Absolute budgets,
workload, host conditions and runtime history remain relevant to outcomes.

Run only the saved-data analysis, not a workload:

```bash
python -B probe7/scripts/analyze_accumulated.py --output-dir artifacts/accumulated-history-replay
```

Zero execution identifiers mark a local replay. The separate
[manual analysis workflow](../../../.github/workflows/guarded-history-analysis.yml)
records hosted provenance but also starts no runtime services. The original
[primary inputs](../main-v0.2.0/primary/README.md) still independently rescore
all external labels. Source hashes, all windows and all witnesses are retained;
failed baselines, reversals and the unsuccessful analogy comparison are not removed.

This establishes a working measurement layer for joint accumulated relative
allocation changes, illustrates what chosen local summaries lose, and ties
the recorded history to separately measured requirement margins. It does not
establish universal predictor superiority or a geometry-defined safe region.
