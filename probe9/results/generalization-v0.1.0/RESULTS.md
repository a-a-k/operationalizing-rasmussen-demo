# Prospective drift-generalization result

## Plain-language result

The campaign asked a concrete early-warning question: while the system is
currently valid and satisfies all three requirements, will any requirement
fail within the next two adaptation cycles?

Two observers used the complete history of allocated resources. One encoded
that history in full ILR coordinates; the other used all raw allocation shares.
A native Prometheus baseline instead extrapolated the four directly observed
service-requirement gauges with `predict_linear`. The two primary comparisons
are therefore **ILR versus Prometheus** and **raw shares versus Prometheus**.
ILR versus raw shares is a secondary representation diagnostic.

All 250 planned runner pairs completed. They produced 500 fresh-stack
histories. Seventeen histories were already unsafe at baseline and were
retained as such; the remaining 483 completed all planned cycles. There were
104 first post-baseline violations and no prediction-integrity failures.

At the frozen primary settings, the allocation-history observers warned before
many first violations that the five-minute Prometheus forecast did not warn
before. They also produced more false signals. The result is evidence that the
history of joint resource redistribution contains useful prospective
information that is absent from the chosen local service-trend forecast; it is
not evidence that either resource rule dominates at every alert burden.

## Primary prospective comparison

An event is counted as warned when at least one eligible signal preceded the
first unsafe window by no more than two cycles. A false decision is a signal
not followed by an unsafe window within that horizon. A history with false
signals is counted once regardless of how many false decisions it contains.

| Frozen method | First violations warned | Histories with false signals | False decisions | Decision precision | Median lead |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full ILR history, threshold 0.2 | 44/104 (42.3%) | 106/483 (21.9%) | 346 | 13.1% | 51.6 s |
| Full raw-share history, threshold 0.2 | 41/104 (39.4%) | 98/483 (20.3%) | 277 | 15.0% | 51.6 s |
| Prometheus `predict_linear`, 5 min | 0/104 (0%) | 52/483 (10.8%) | 105 | 1.9% | NA |

The comparison is paired on the same 104 events. ILR alone warned before 44
events and Prometheus alone before none. Raw shares alone warned before 41 and
Prometheus alone before none. Prometheus did emit two decisions that were
followed by an unsafe window, but neither occurred before a history's *first*
violation; this is why its event count is 0/104.

The primary result is a trade-off, not free superiority: the two resource
observers caught substantially more first violations, while also disturbing
more otherwise negative histories. Exact paired counts are in
[summary.json](summary.json), and every decision is in
[decisions.csv](decisions.csv).

## Fixed sensitivity points at a similar signal burden

The campaign retained all operating points enumerated before execution; no
threshold was selected from these outcomes. The most informative sensitivity
comparison uses the stricter resource threshold 0.6 and the two-minute
Prometheus lookback:

| Fixed setting | First violations warned | Histories with false signals | False decisions | Decision precision | Median lead |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full ILR history, threshold 0.6 | 11/104 | 78/483 | 78 | 12.4% | 51.7 s |
| Full raw-share history, threshold 0.6 | 11/104 | 70/483 | 70 | 14.6% | 51.7 s |
| Prometheus `predict_linear`, 2 min | 10/104 | 77/483 | 92 | 11.5% | 29.8 s |

At this roughly comparable burden, the observed difference is modest rather
than dramatic. Raw shares warned before one additional event with seven fewer
affected histories and 22 fewer false decisions than Prometheus. ILR warned
before one additional event with one more affected history but 14 fewer false
decisions. Both gave about 22 seconds more median lead. These are descriptive
fixed-point results, not an optimized detector comparison.

The complete fixed curves are in
[resource-operating-points.csv](resource-operating-points.csv). Prometheus
results for the pre-specified 2-, 5-, and 10-minute lookbacks are in
[summary.json](summary.json).

## What this says about adaptation and drift

The unchanged controls make it possible to distinguish redistribution history
from ordinary runtime variation.

- Of 237 pairs in which both histories had a safe baseline and completed, 89
  had a violation only under adaptation, 4 only under control, 3 under both,
  and 141 under neither.
- Across all eligible histories, 97 adaptive histories and 7 control histories
  had a first post-baseline violation.
- ILR and raw-share observers emitted no signals in control histories. Their
  398 and 326 primary-setting signals, respectively, occurred only in adaptive
  histories. Prometheus emitted four false decisions in two controls.
- First failures involved checkout alone in 54 histories, advertising alone in
  12, accounting and checkout together in 37, and accounting alone in 1.
- Ninety-two first violations occurred under the busy profile and 12 under the
  moderate profile.

This is the Rasmussen-relevant result: repeated locally guarded reallocations
changed the joint allocation state, and post-baseline requirement failures were
concentrated in those adaptive histories. A full allocation-history observer
could warn from that accumulated movement when a forecast using only recent
service-requirement values often could not.

The paired policy counts above are reconstructed directly from
[history-status.csv](history-status.csv),
[first-events.csv](first-events.csv), and the archived
[blocks](blocks/). They are not additional executions.

## What this says about ILR versus complete shares

The campaign does **not** establish predictive superiority of ILR over all raw
shares. At the primary point ILR warned before three more events, but produced
69 more false decisions and affected eight more negative histories. At the
strict 0.6 point both warned before 11 events, while raw shares produced fewer
false signals.

That result does not make ILR redundant. Both vectors preserve the complete
selected allocation state, so both can outperform a local service-only rule
when the important information is simply missing from the latter. ILR adds an
orthonormal coordinate system for relative change and the Aitchison metric;
raw-share differences retain an additive scale whose meaning varies with the
starting composition. This campaign shows that both full-state histories are
usable warning inputs. It does not isolate geometry as the cause of their
advantage over Prometheus, because the frozen resource observers also share a
labeled history library and neighbor rule.

## Coverage and audit checks

| Check | Result |
| --- | ---: |
| Planned/received runner pairs | 250/250 |
| Fresh-stack histories | 500 |
| Baseline-safe, complete histories | 483 |
| Baseline-unsafe histories retained | 17 (6 adaptive, 11 control) |
| First post-baseline violation histories | 104 |
| Prediction-integrity failures | 0 |
| Missing matrix jobs | 0 |
| Technical job failures or replacements | 0 |

The resource observers ran online and could not read future windows. Native
Prometheus 3.15.0 was replayed over availability-timestamped raw gauges; each
query saw only samples available at its evaluation time. Binary versions,
hashes and native checks are preserved in [summary.json](summary.json) and
[native-checks.json](native-checks.json). Raw native responses are in
[native-responses.jsonl.gz](native-responses.jsonl.gz), and the empty integrity
failure table is [prediction-integrity.csv](prediction-integrity.csv).

Execution metadata in [summary.json](summary.json) identifies the exact frozen
commit and execution. The compact per-pair records in [blocks](blocks/) retain
the allocation histories, external outcomes and online resource-observer
decisions without depending on expiring workflow artifacts.

## Limits of the result

This is a constructed proof-of-concept campaign on one application and one
adaptation policy. It does not estimate production incident probability or
establish a universally optimal alert. Decision windows within a history are
dependent; the 250 runner pairs and their first violations are the meaningful
replication scale. The primary resource settings trade substantially more
false signals for detection, and even the stricter fixed points have low
precision. An intervention study would still be needed to show that acting on
these warnings improves operations.

The defensible conclusions are narrower:

1. complete allocation histories generalized beyond the earlier development
   executions and exposed prospective information missed by the fixed
   five-minute service-trend forecast;
2. the result concerns joint accumulated redistribution, as supported by the
   adaptive/control contrast;
3. a fixed, stricter resource-history setting remained competitive with a
   more responsive two-minute Prometheus forecast at a similar signal burden;
4. this campaign did not demonstrate that ILR predicts better than complete
   raw shares, so CoDA's distinct contribution remains the principled geometry
   and coordinate system for relative drift.

## Data index

- [summary.json](summary.json): aggregate methods, paired comparisons, versions
  and frozen provenance.
- [decisions.csv](decisions.csv): every eligible decision for all three
  Prometheus lookbacks.
- [first-events.csv](first-events.csv): per-method credit and lead time for each
  first violation.
- [resource-operating-points.csv](resource-operating-points.csv): all frozen
  ILR and raw-share thresholds.
- [strata.csv](strata.csv): primary outcomes by starting composition and load.
- [history-status.csv](history-status.csv): baseline and completion status for
  all 500 histories.
- [prediction-integrity.csv](prediction-integrity.csv): observer audit failures
  (header only because none occurred).
- [native-responses.jsonl.gz](native-responses.jsonl.gz): exact native query
  responses.
- [blocks/](blocks/): compact source records for all 250 runner pairs.
