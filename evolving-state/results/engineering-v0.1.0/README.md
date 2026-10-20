# Initial engineering execution

This is the initial execution of [design 0.1.0](../../design-v0.1.0.json),
not part of the subsequent descriptive campaign.

- All 18 windows were recorded. There were 4,465 client attempt starts and
  4,442 forwarding-worker receipts, all with successful upstream reads.
- No load iterations were dropped. The gateway completed 3,401 logical calls,
  3,231 successfully. External-client response journaling was added later;
  these success counts are gateway observations.
- Both updated observers reconstructed all available states and policies
  correctly. Native PromQL verified the updated direct arithmetic.
- The run exposed 23 attempts without a worker receipt during handover and
  one late first attempt in the nominal idle window. These records remain here.

Revision 0.1.1 adds worker readiness checks, independent observer polling and a
second idle window. It also reverses the order of the two policy-only threshold
changes to exercise a change of policy status without a simultaneous execution
intervention. None of these engineering data are pooled with that campaign.

[Summary](analysis/summary.json), [per-diagnosis comparison](analysis/diagnostic-comparison.csv),
[execution windows](analysis/execution-windows.csv), [native engine](engine.json),
[native verification](promql-validation.json), [export provenance](provenance.json).
The current reanalysis distinguishes held-report staleness from computational
error and does not censor lineage latency at unrelated policy edits. Original
event and observer records are preserved in [the replay inputs](inputs/).

Reproduce from the repository root:

```sh
python -B evolving-state/scripts/analyze.py --inputs evolving-state/results/engineering-v0.1.0/inputs --output artifacts/evolving-engineering-0
```
