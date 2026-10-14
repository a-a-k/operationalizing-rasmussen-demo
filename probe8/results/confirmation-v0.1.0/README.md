# Independent warning confirmation: interpretation

Execution 38547221917 used commit
2f8cf9e8bde4413eef7bd9cc3cdc43e28f87ca85 and the unchanged
[frozen model](../../frozen-model-v0.1.0.json), developed in execution
38544485211. No confirmation observations entered the library, scale fitting
or threshold selection. This campaign is separate from its development source.

## Completeness and measurement integrity

All twenty planned fresh runner pairs arrived: forty baseline-safe, complete
histories and 840 technically valid windows. Six adaptive histories violated
checkout requirements; two of those also violated accounting timeliness.
Advertising stayed within its requirement, and all twenty unchanged controls
stayed safe. There were no missing pairs, truncated histories, unknown eligible
future labels or failed live predictions.

The [primary audit](primary/summary.json) independently reproduced every
external outcome from 887,039 checkout durations, 887,010 confirmed-order
records and 48,814,447 advertising attempts. Replay of the frozen observer
reproduced every live score, threshold, alert and selected neighbor list.
Native primary inputs are preserved in the [compressed packs](primary/README.md).
The [twenty host contexts](hosts/) preserve CPU, Docker, kernel and runner-image
metadata from the actual new executions.

There were 756 eligible safe decisions per method: 376 adaptive and 380 control.
Ten decisions preceded a violation within the next two cycles; these ten
overlapping opportunities are **not ten independent events**. The six first
violations occurred at cycles 13, 14 or 20. Four currently unsafe windows within
cycles 0--18 are ineligible; cycles 19--20 are measured but not forecast because
their planned two-cycle future is unavailable.

## Results at the frozen operating points

| Method | First violations warned / observed | True / all warning decisions | False warning decisions | False warnings / safe-future decisions |
| --- | ---: | ---: | ---: | ---: |
| Full ILR history, threshold .2 | 5/6 | 5/50 (10.0%) | 45 | 45/746 (6.03%) |
| Euclidean share history, threshold .2 | 4/6 | 4/42 (9.52%) | 38 | 38/746 (5.09%) |
| Selected local history, threshold .4 | 2/6 | 2/8 (25.0%) | 6 | 6/746 (0.80%) |
| Service indicators, threshold .4 | 2/6 | 2/5 (40.0%) | 3 | 3/746 (0.40%) |

All signals occurred in adaptive histories; controls received no signals.
Consequently, the false-warning fractions among **adaptive** safe-future
decisions are 45/366 (12.30%), 38/366 (10.38%), 6/366 (1.64%) and 3/366 (0.82%),
respectively. The pooled percentages are not the alarm burden of adaptation
alone. These are dependent decision counts, not independent trial rates.

Every credited first-violation signal preceded the violating window by
51.53--52.09 seconds. For ILR the median was 51.73 seconds. All signals were
two cycles before their event. This is time to the start of the first violating
measurement window, not an inferred internal failure instant or a demonstrated
reaction-time requirement. Computation of all four methods together took
3.08 ms on average across eligible decisions, maximum 11.39 ms; this excludes
file writing and is not a full physical-overhead experiment.

## A concrete successful warning, not just an already breached SLO

In balanced-busy-04, cycle 11 was safe: checkout p95 was 295.9 ms, errors were
zero and both timeliness fractions were 1. The ILR rule emitted score .2 at its
frozen threshold .2. Cycle 12 remained safe, p95 272.0 ms. Cycle 13 then violated
the checkout requirement, p95 614.0 ms. The signal was available 51.73 seconds
before that window began. The Euclidean-share rule had score zero and did not warn.

The selected-local rule also had score .2 at cycle 11, but its frozen threshold
was .4. Its missing signal in this example therefore must not be attributed
solely to absent allocation information. Different development operating
points are part of the measured comparison.

Evidence: [every first event](evaluation/first-violation-events.csv),
[all decisions](evaluation/warning-decisions.csv),
[full recorded histories](evaluation/block-level.json),
[aggregate](evaluation/summary.json).

## What the result adds, and what it does not

A fixed compositional-history rule really emitted forecasts before observed
violations on new executions, without changing the guarded controller or using
those executions' future outcomes. This is an implemented and prospectively
checked warning mechanism, beyond retrospective descriptions of hidden drift.

It is not yet a good operational alert: nine of ten ILR signals did not precede
a violation within the specified horizon. Compared with Euclidean share history, one
additional event was warned at the cost of seven additional false decisions.
Compared with the frozen service-only rule, three additional events were warned
at the cost of forty-two additional false decisions. More detections alone do
not establish practical superiority or a uniquely necessary full-state detector.

The [secondary operating curves](evaluation/operating-curves.csv) use only
thresholds enumerated in development; the live rules are not retuned. At .2 the
local score would also cover five events, with 43 false decisions versus ILR's
45. This is a descriptive score comparison, not a newly confirmed replacement
rule. It prevents interpreting the primary 5/6 versus 2/6 contrast as proof that
the complete representation is necessary for this prediction task. No uniform
ILR superiority is established.

False signals mean no measured violation in both next cycles **under the
unchanged guarded policy**. A prevented but unobserved failure without the
controller's rollback is not inferred. Performance is conditional on these
constructed CPU histories, RAM contexts, workloads and the small number of
events. Benefits of acting on a signal and deployment usefulness remain open.

For target definitions and simple examples see the
[plain-language explanation](../../interpretation-v0.1.0.md).

## Recheck without workloads

```bash
python -B -m unittest discover -s probe8/tests -v
```

This replays committed forecasts and independently rescores primary packs;
it starts no services, changes no thresholds and launches no new campaign.

