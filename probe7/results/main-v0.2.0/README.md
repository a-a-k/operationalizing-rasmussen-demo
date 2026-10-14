# Guarded adaptation: interpretation and evidence

Main execution: 38464142171, implementation
6bc428f7005b5ef3ece75262822f4f3a8f560dc0. The finalized
[definition](../../design-v0.2.0.json) and [runtime](../../runtime-v0.2.0.json)
are separate from the [technical feasibility observations](../engineering/README.md).
The runtime campaign ran from 20:36 to 21:55 UTC on 2026-10-13,
including aggregation (78 minutes 48 seconds). Twenty pairs ran concurrently,
followed by four more.

## What was compared

Each runner hosted two fresh full Demo stacks in randomized, cell-balanced
order. Both started from the same assigned allocation and received the same
checkout profile plus eight closed-loop advertising VUs. The adaptive history
transferred CPU to advertising after measuring receiver pressure and donor
requirement headroom. Its control kept the initial allocation. Each history
was bounded at twenty cycles; runtime state persisted between its windows.

Eleven selected components share a 3.4-CPU administrative ceiling budget and a
4544-MiB memory-ceiling budget. Memory differs across three initial contexts but
does not move within a history: commissioning did not establish recipient RAM
benefit. This is not a claim of dynamic joint CPU/RAM adaptation. Unselected
services and load generators remain contextual load outside these budgets.
Stack configuration and generator resource samples are recorded; the controller
does not continuously observe every unselected service's resource use.

The controller used no CoDA coordinate and contained no prescribed boundary
crossing. It chose among donors using preceding measurements and rolled back
unsafe or near-boundary changes. Its dependency table is an engineering model,
not an inferred dependency graph or a reproduction of the complete PARTIES
controller.

## Completeness and external outcomes

All 24 planned runner pairs were received: 48 attempted histories and 988
evaluation windows, excluding warmup. All 988 windows were technically valid.
One control, ledger-busy-01, had baseline checkout p95=559.2 ms with no errors;
it therefore stopped at the baseline safety gate. Its measurements remain in
[the block records](block-level.json). Its adaptive counterpart completed;
it is not silently discarded from the representation analysis. Paired
fixed-endpoint contrasts have 23 complete pairs, whereas analog retrieval has
24 query pairs.

| Observation | Result |
| --- | --- |
| CPU transfer attempts / RAM transfer attempts | 470 / 0 |
| Transfers rolled back | 8 |
| Initially safe paired adaptive histories with an unsafe window | 7/23 |
| Their matched controls with an unsafe window | 0/23 |
| Adaptive checkout-unsafe windows | 7 |
| Adaptive accounting-unsafe windows | 4, also checkout-unsafe |
| Advertising-unsafe evaluation windows | 0/988 |
| Unsafe adaptive fixed endpoints | 2/23 |

The extra eighth checkout-unsafe window is the stopped control's baseline.
All seven adaptive violations occurred under the busy profile. No evaluation
quota-readback snapshot recorded restart or OOM; this is not a proof that every
possible transient was absent. No restart flag changes an external outcome.

Rollback is reactive: the controller can discover that its earlier reserve
estimate was insufficient. It does not prevent a trial from violating a
requirement. The finite observation budget also ends two histories immediately
after unsafe trials; their rollback commands are recorded, but no subsequent
post-rollback window was measured. Those cases are not reported as recovered.

Evidence: [all windows](windows.csv), [every paired epoch](paired-epochs.csv),
[aggregate](summary.json), and [full records](block-level.json).

## Useful recipient gains accompanied costs elsewhere

At the prespecified final cycle, subtract each history's own baseline and then
the same contrast in its unchanged control. This accounts descriptively for
shared progression such as warmup; it does not isolate each individual transfer.

| Control-adjusted final change | Median | Positive pairs |
| --- | ---: | ---: |
| Advertising goodput | +2105.4 nonempty responses/s | 23/23 |
| Checkout request p95 | +45.8 ms | 21/23 |
| Accounting observed p99 commit lag | +55.4 ms | 21/23 |

Accounting p99 is conditional on observed commits. Timely fractions, including
missing orders, are the external membership criterion. The median final timely
fraction change is zero; this must not obscure the four earlier accounting
failures or the two failed endpoints. All raw contrasts and ranges are in
[the generated tables](RESULTS.md) and [paired epochs](paired-epochs.csv).

This supports a constructed runtime history in which locally useful adaptation
changes the operational trade-off and can exhaust another process's margin,
despite reactive protections. It is not a production-drift frequency, a human
adaptation model or a guarantee that every guarded history crosses a boundary.

## What selected local relations missed

The three selected coordinates were CPU checkout/payment, CPU frontend/ad,
and RAM accounting/Kafka, each log-scaled by 1/sqrt(2). They form three
orthonormal contrasts in the full twenty-coordinate product space. For the 476
nonzero observed reallocations, median energy outside their projection was
88.7%. This is geometric loss, not a percentage of missed failures.

A post-run descriptive search found five overlapping safe/unsafe comparisons
with identical selected coordinates, the same initial context and workload,
but different full allocations. They are not five independent replications or
causal contrasts. Every match is retained in
[projection-witnesses.csv](projection-witnesses.csv).

For example, interactive-busy-01 and interactive-busy-02 at cycle 6 had identical
selected ratios and the same checkout, frontend and advertising CPU ceilings
(0.55, 0.55, 0.49). Their database/Kafka ceilings were (0.38, 0.22) versus
(0.34, 0.26). Checkout p95 was 609.3 versus 120.5 ms. Full coordinates retain
that allocation distinction; they do not establish which component caused the
outcome. Different runners and preceding histories remain relevant.

Observed ILR displacement vectors span eight linear directions of the
twenty-coordinate state representation. Linear span is not an intrinsic
controller dimension or evidence of full state-space exploration. The two
representations with complete information—raw shares and full ILR—both preserve
all these distinctions. Only their geometry differs.

## No demonstrated ILR advantage in the analog task

For each nonzero adjacent reallocation, retrieve nearest displacement analogs
outside the entire query runner pair. Workload and both endpoint-window
durations match. All representations receive exactly the same targets and
candidates. Equidistant sections are averaged within neighboring pairs and then
equally across pairs. There is no outcome-selected tie break or fitted detector.

The target is the change in the three normalized controller headrooms. Its
error is reported separately by business process and averaged first within a
query pair, then equally across pairs. These headrooms are engineering signals,
not a learned safety-region metric or an alerting-performance score.

| Representation | Macro pair mean absolute error |
| --- | ---: |
| Three selected log-ratios | 0.4312 |
| Full shares, Euclidean displacement | 0.3860 |
| Full ILR displacement | 0.4120 |

Lower is better. Full ILR was not better than full shares in this task: it had
lower pair-mean error in 9 pairs and higher error in 15. Raw-minus-ILR mean error
was -0.0260; descriptive pair-resampling interval [-0.2325, 0.1104]. The large
accounting headroom changes dominate the aggregate error; per-process results
must also be read. Resampling dependent cross-validation results conditional on
their common neighbor pool is not a calibrated generalization guarantee.

This is not a negative result about invertibility or compositional invariance.
Those are established mathematical properties. It is a non-superiority result
for this particular simple consequence-similarity task. The controller uses
fixed additive 0.04-CPU transfers; the observation does not show that a relative
distance is necessarily the best distance for SLO consequences.

Evidence: [every analog](neighbors.csv), [pair-level errors](pair-retrieval-errors.csv),
[sections](sections.csv) and [per-process results](RESULTS.md).

## Analysis provenance and reproduction

The [execution-time aggregate](execution-aggregate.json) used the earlier
matching implementation. Saved-data analysis 0.1.1 additionally matches the
preceding-window duration: the first 60-to-30-second transition is not matched
to later 30-to-30-second transitions. This correction was specified before
inspecting main outcomes, changes no runtime data, and changes neither the
substantive interpretation nor the direction of the metric comparison. Raw and
ILR errors were initially 0.3863 and 0.4120. Raw-outcome contrasts and projection
witnesses are descriptive saved-data analyses, not additional experiments.

The displayed [example](example.svg) is balanced-busy-01, selected before main
execution, not replaced by the most favorable history.

```bash
python -B probe7/scripts/analyze.py --block-records probe7/results/main-v0.2.0/block-level.json --output-dir artifacts/guarded-replay
```

This reads committed records and starts no services. It regenerates tables,
matching results, all projection witnesses and the same prespecified figure.

[Preserved primary inputs](primary/README.md) independently rescore all 988
external outcomes from durations/counters, acknowledgment logs and database
commit timestamps. Their [audit](primary/summary.json) passed for every received
window. [Runner host contexts](hosts/) preserve CPU, kernel and Docker metadata.
