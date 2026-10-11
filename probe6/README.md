# Joint CPU/memory boundary migration

This separate exploratory series tests whether the observed safety of one
resource adaptation depends on another resource allocation. It neither replaces
nor pools earlier results. No observation from this series has yet been reported.

## Four sequential histories

Every campaign block is one fresh GitHub runner. It runs four fresh-stack
histories in a fixed, position-balanced order:

| Policy | CPU transfer per step | Memory transfer per step |
| --- | --- | --- |
| control | None; sham update | None; sham update |
| cpu | 0.02 CPU, checkout to advertising | None |
| ram | None | 16 MiB, checkout to advertising |
| joint | Same CPU transfer | Same memory transfer |

The four CPU ceilings initially are checkout/payment/shipping 0.30 each and
advertising 0.10. Their sum stays 1 CPU. The two controlled memory ceilings
initially are checkout 256 MiB and advertising 512 MiB; their sum stays 768 MiB.
After twelve transfers checkout reaches 0.06 CPU and/or 64 MiB. These are separate
administrative ceilings, not reservations of physical host capacity. CPU and RAM
are never added or closed together into a single composition.

Checkout workload stays 40 scheduled operations/s with two 5-second HTTP
timeouts and 800 fixed VUs. Advertising uses the pinned native RPC, 8 fixed VUs
and a 2-second timeout. Its successful responses/s are the measured reward,
not money or a proxy derived from the allocation. Code, Go memory settings,
restart policies and all other services stay identical across the four policies.
Checkout GOMEMLIMIT stays 192 MiB even below that cgroup cap; it is not an
additional adaptation. Memory effects may include reclaim, queuing or OOM.

An adaptive history transfers only when the preceding checkout SLO is safe and
advertising was CPU-throttled. It stops at the first valid unsafe measurement,
absent/unobserved recipient CPU pressure, a technical measurement failure or
twelve moves. This is a fixed resource-transfer heuristic motivated by output
pressure, not an optimizer. In particular, recipient memory pressure or a benefit
from extra RAM is not presumed. Negative and zero goodput changes remain in the
data. The unchanged control performs all twelve sham epochs unless its
measurement infrastructure fails, even if it becomes unsafe.

## First, a separate engineering gate

Four independent engineering jobs exercise the same fixed paths with shorter
windows: 30-second warmup, 60-second baseline, 10-second stabilization and
30-second measurements. Each must have a valid initially safe baseline, measured
advertising output/CPU pressure, and technically valid observed epochs.
At least one RAM-only or joint history must show a positive post-adaptation
`memory.events` max/oom/oom_kill increment within one cgroup identity. This tests
that the memory ceiling actually binds, not that a joint-only SLO violation exists.
There is no parameter search or required SLO outcome. A failed gate stops the
campaign. These observations are engineering evidence, never scientific
replications in the twenty-block aggregate.

Campaign timings are 60-second warmup, 90-second baseline, 15-second
stabilization and 60-second measurement. Twenty jobs can execute concurrently;
each contains all four histories. There are no replacements or additional waves.

## What counts as a joint-context witness

At the same measured step within a block, with four valid initially safe baselines
and four valid measurements:

> Control, CPU-only and RAM-only remain safe, while CPU+RAM is unsafe.

Safe means externally measured checkout request p95 at most 500 ms **and**
unsuccessful scheduled iterations below 1%. Restart/OOM never changes that label
or automatically excludes the measurement. Generator capacity, real resource
configuration and primary-data integrity are separate validity checks.

Report every matched epoch and all alternative patterns. Later epochs after a
policy stops remain missing, not assumed safe/unsafe. Report blocks with an
observed witness, fully valid blocks, complete four-way epochs and missing or
invalid evidence. The block-level fraction and exact interval describe the
bounded observed paths, not a detector's reliability. There is no arbitrary
majority threshold or scientific pass/fail proportion.

Factorial latency/error/reward contrasts are descriptive and computed only at
valid matched epochs. Matching the transfer index does not equalize queue state
or undo the histories' prior outcomes. Crossing-selected contrasts are not a
preselected fixed-time causal effect.

An observed witness supports context-dependent safety of these adaptations.
It does not establish superiority over multivariate rules, a simplicial complex,
or downward closure of safe adaptation sets. Extra allocation alone establishes
no efficiency improvement: inspect the actual advertising reward in every arm.

## Runtime checks and reproduction

The design and runtime are versioned in `design-v0.1.0.json` and
`runtime-v0.1.0.json`. Existing digest-pinned images, complete action SHAs,
upstream RPC/source revision and primary measurement functions are reused.
The new runner, analysis, memory overlay and workflow are separate.

Docker updates are donor-first and not atomic across containers. Keep their
timestamps, stdout/stderr and exit codes. Before and after each measured epoch,
check both configured budgets and live `cpu.max`, `memory.max` and
`memory.swap.max`; swapping is disabled for checkout and advertising. A stopped
or restarting SUT with correct persisted configuration is diagnostic, not an
automatic exclusion. Cgroup counters are never differenced across identities.

Only lightweight checks run locally:

```bash
python -B -m unittest discover -s probe6/tests -v
python -B probe6/scripts/joint_resources.py verify
```

Run `joint-cpu-memory-migration` in Actions with the exact commit in
`expected_sha`. With `execute=false`, only verification and the four engineering
histories run. With `execute=true`, the twenty new blocks start automatically
only after the engineering gate passes. A technical gate failure is not a
scientific rejection of the joint-context hypothesis.

Every run preserves rendered Compose, image inspections, update journals,
effective resource snapshots, checkout raw streams, advertising summaries,
container events and resource samples. Raw artifacts last 14 days; compact
gate/campaign artifacts last 90 days. Archive them before expiration. The compact
analysis contains `summary.json`, `trajectory-level.csv`, `four-way-epochs.csv`
and `RESULTS.md`. No fitted alert threshold or automatic comparison claim is used.
