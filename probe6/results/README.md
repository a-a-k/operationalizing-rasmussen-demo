# CPU/memory evidence: separate executions

The new campaign completed: **5 of 20 technically valid fresh-runner blocks**
contained an observed matched step where control, CPU-only and RAM-only were
safe, while the joint history was unsafe. No result fraction defined success;
all twenty blocks are present, including the fifteen without that witness.

## Provenance and data

| Execution | Run identifier | Execution commit | Role |
| --- | --- | --- | --- |
| Original engineering check | 38119850102 | 63c7450160a991f98d86b76da78a1f84a7999b18 | Its path ended at 64 MiB without observed memory-cap binding; no campaign started. |
| RAM range calibration | 38121505766 | 538a6570922ea66e5bdfe8d041b68e165493f368 | Nine independent engineering conditions, one observation each. Never pooled with campaign blocks. |
| Six-step CPU/memory follow-up | 38122731803 | 8100cf8671ace12f82b726f13b82e35bcf691b88 | Twenty new four-history blocks; 46 minutes 49 seconds including verification and aggregation. |

The active follow-up design and its engineering-informed selection are in
[JOINT_RESOURCES_v0.2.0.md](../JOINT_RESOURCES_v0.2.0.md). These committed files are
the downloaded compact outputs, not replacements for or altered versions of
executed inputs:

- [Campaign summary and complete block records](joint-v0.2.0/summary.json)
- [Every baseline and observed adaptation step](joint-v0.2.0/trajectory-level.csv)
- [Every observed matched or incomplete four-way step](joint-v0.2.0/four-way-epochs.csv)
- [Generated campaign interpretation](joint-v0.2.0/RESULTS.md)
- [Original engineering gate decision](engineering-v0.1.0/engineering-gate.json),
  with the separate original [control](engineering-v0.1.0/control/block-result.json),
  [CPU-only](engineering-v0.1.0/cpu/block-result.json),
  [RAM-only](engineering-v0.1.0/ram/block-result.json) and
  [joint](engineering-v0.1.0/joint/block-result.json) block records
- [Separate RAM calibration summary and complete point records](ram-calibration-v0.1.0/summary.json)
- [Every RAM calibration condition](ram-calibration-v0.1.0/condition-level.csv)

The campaign summary retains full block records for reanalysis. Run identifiers
are provenance, not external links required to understand these data. Raw-stream
artifacts have a shorter lifetime; these compact observations remain in the
repository. A lightweight local replay of the frozen analysis reproduced the
block counts, validity, witness identities and matched-step counts.

## What happened

All 80 baselines were initially safe and technically valid. All 471 observed
adaptation/sham measurements were technically valid; all 551 primary windows
started every scheduled iteration, with zero drops and zero unfinished
iterations. All 112 complete four-way steps were valid. The remaining eight
step comparisons are incomplete because an adaptive history had already stopped;
its later outcome is not inferred.

| History | Blocks with an observed unsafe step | First unsafe step |
| --- | ---: | --- |
| Unchanged control | 0/20 | None; all 120 sham measurements safe |
| CPU-only | 14/20 | One at step 3, one at step 5, twelve at step 6 |
| RAM-only | 17/20 | All seventeen at step 6 |
| CPU+RAM | 20/20 | Five at step 5, fifteen at step 6 |

The six safe CPU-only histories and three safe RAM-only histories reached the
move limit. They are not assumed safe beyond it. Five matched joint-only unsafe
witnesses occurred: blocks 005, 008, 010 and 020 at step 5 (0.15 CPU / 28 MiB),
and block 007 at step 6 (0.12 CPU / 24 MiB). The within-block witness fraction
is 5/20 = 0.25, with descriptive exact 95% interval 0.0866--0.4910. It is not a
detector reliability estimate or a scientific pass/fail threshold.

Four witnesses violated the error-rate requirement; one violated latency.
Memory-cap events were observed in all twenty RAM-only and all twenty joint
histories, and in none of the control/CPU-only histories. OOM/restart diagnostics
remain separate from SLO labels; safe measurements with diagnostics are retained.

## A concrete four-way witness

Block `resources-020`, step 5; other controlled quotas remain as specified by
the closed-budget paths:

| History | Checkout CPU | Checkout RAM MiB | p95 ms | Unsuccessful orders | SLO |
| --- | ---: | ---: | ---: | ---: | --- |
| Control | 0.30 | 48 | 106.5 | 0/2400 | Safe |
| CPU-only | 0.15 | 48 | 206.6 | 0/2400 | Safe |
| RAM-only | 0.30 | 28 | 109.7 | 0/2400 | Safe |
| Joint | 0.15 | 28 | 192.0 | 48/2400 (2%) | Unsafe |

This is an observed contrast between allocation histories: the same CPU ceiling
occurred with both a safe and an unsafe outcome, and so did the same RAM ceiling.
Neither resource value alone represents the joint context in this block. Most
requests were still fast, but the unsuccessful-order fraction exceeded the SLO.
Do not read lower joint p95 than CPU-only p95 as better overall service.

## Relation to adaptation and its limits

The transfers were successive, not static endpoint interventions. Each was
authorized by the preceding safe checkout outcome and positive advertising CPU
throttling. At the first joint unsafe step, the baseline-adjusted advertising
goodput increase relative to the matched control was positive in all 20 blocks:
minimum 493.73 responses/s, median 671.08 responses/s. This is measured output,
not revenue. All reward changes remain in the records; 31 of the 120 RAM-only
step-to-step changes were negative. Extra RAM is not established as beneficial
to the CPU-limited recipient.

The observations support a bounded example of output-pressure-motivated closed
resource redistribution crossing an external performance boundary, with five
replicated within-block witnesses of joint resource context. Separate CPU and
RAM compositions describe this joint state without adding unlike resource units.

They do **not** demonstrate a unique or superior CoDA detector. A multivariate
rule using CPU and RAM together could also distinguish the four states in the
example. There was no fitted detector, threshold calibration or predictive
comparison. Equal step indices do not guarantee equal queue state, and the
histories were run sequentially with balanced order, not simultaneously. A
witness is therefore not an isolated fixed-time causal interaction estimate.
No simplicial-complex structure, downward closure, general safety boundary,
production prevalence or universally safe resource threshold is established.
