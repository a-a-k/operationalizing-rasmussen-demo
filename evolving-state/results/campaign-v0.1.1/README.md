# Eight-history evolving-state campaign

## Outcome

The updating measurement contract worked in all eight new runtime histories.
It reconstructed the observed attempt state, applied the current policy, and
reported unavailable intervals when required lineage information was delayed.
It did not confuse a policy edit with movement of the measured composition.

The equally updated **direct-ratio observer worked just as accurately**.
This campaign establishes an executable, supported form of evolving-state
observation, not a uniquely superior CoDA detector.

The separate [directional readout](directional-v0.1.0/README.md) now checks what
the retained trajectory adds: orientation relative to each current policy and
conditional distance to the first boundary along a fixed relative direction.
It reuses these histories without changing their runtime results or claiming
prediction of the actual future.

## What actually ran

The [fixed design](../../design-v0.1.1.json) was exercised on eight fresh hosted
runners after two engineering executions excluded from this dataset. No history was
replaced or rerun. Each history had 19 ten-second observation windows under an
open-loop stream of catalog and currency reads.

The evolved components were an instrumented retry/forwarding layer in front of
the pinned OpenTelemetry Demo. One catalog forwarding worker became two routed
workers; those workers were replaced and then recombined. These were actual
containers and routing changes, **not decomposition of the Demo's business
services or inference of arbitrary architectural lineage**. Supported membership
was extracted from deployment annotations and explicit predecessor records.

Faults were controlled delivery failures after successful upstream reads.
The client increased its maximum attempts from two to three. The experiment
also edited the allowed retry fraction, separately and alongside other changes.
The observers were passive; they never chose retries or rolled back updates.

The measured policy was `R/(F+R) <= rho`, at one client-call layer and over the
latest completed window. This is an administrative attempt-count policy, not a
validated CPU-capacity boundary or a claim that the application was overloaded.
Successful logical reads mean external-client HTTP 200 responses.

The state oracle reconstructed individual client events using logical call
identities, rather than the observer's component mapping. Separate worker
journals corroborated physical calls; external k6 records corroborated client
responses. The client event journal and counters share the client-layer timing
origin, so they are not wholly independent measurement instruments.

## Results and interpretation

The call-rescue enumeration and same-window witness counts below are
descriptive post-run readouts of the retained journals. They do not introduce
a refitted detector, a new success threshold or an independent confirmation claim.

### 1. A concrete local benefit came with more retry activity

There were **35,410 attempt starts and 35,410 matching worker receipts**, all
with successful upstream reads before the controlled delivery faults. The
external client recorded **27,206 completed calls, 25,810 successful**. No load
iterations were dropped and no external-client record lacked a gateway start.

At the same configured delivery-failure probability, the higher-allowance
cohort had greater client success and a greater retry share in all eight
histories. Across histories, the median success fraction was **79.4% with two
allowed attempts and 90.6% with three**; median retry share was **30.4% versus
39.2%**.

Those cohorts occur at different times and include subsequent policy/component
edits. Their rate comparison is descriptive, not a randomized causal estimate.
The stronger within-call observation is explicit in the journals:
**667 calls had two unsuccessful attempts followed by a successful third
attempt and a successful external-client response**. There were 1,276 third
attempts in this same-fault cohort. These are concrete rescue witnesses under
controlled faults, not 667 independent runtime replications or a production
benefit estimate.

For the preselected example `history-01`, the two-attempt cohort had 315/400
successful calls and 182 retries among 582 attempt starts. The three-attempt
cohort had 725/802 successful calls and 518 retries among 1,320 starts; 85 calls
were rescued on their third attempt. These are attempt counts, not CPU work.

### 2. An unchanged measured point can acquire a different policy status

There were **13 consecutive-report comparisons of the same completed window**
in which the applied policy changed but all four measured counts remained
identical. In **five**, at least one group's policy status changed. The ILR
state did not change in any of these comparisons.

This demonstrates why state movement and movement of the constraint must be
reported separately. It does not assert that every aspect of the executing
application stayed physically unchanged between the reports.

For every available updated diagnosis, the reconstructed counts, current margin,
and the decomposition `delta_m = delta_rho - delta_r` agreed with the event
oracle. The maximum recorded arithmetic errors were zero.

### 3. Updating the contract preserved diagnosis through representation changes

An assessment below means one logical group in one emitted report. Reports can
be emitted on window, policy or metadata changes; they are **not independent
statistical trials**. The independent replication unit is the runner history.

| Observer | Available assessments | Correct full state/policy/margin | Wrong policy decisions | Missing lineage | No attempts |
|---|---:|---:|---:|---:|---:|
| Fixed initial schema | 129 | 80 | 48 | 210 | 23 |
| Updated direct ratios | 304 | 304 | 0 | 32 | 26 |
| Updated CoDA | 304 | 304 | 0 | 32 | 26 |

The fixed schema's 48 erroneous policy decisions are repeated assessments,
six per history, not 48 independent incidents. One additional available fixed
assessment had an incorrect margin without changing the binary policy decision.
Its unresolved components were reported unavailable, not silently discarded;
there is no claim that this conservative ablation fabricated resource movement.

Both updated observers retained real count changes across the routing updates.
They agreed on **every** policy assessment. Native Prometheus 3.15.0 passed
**165 applicable input fixtures**, including the metadata join and policy
arithmetic. This is native arithmetic validation, not a comparison of full
production alerting-platform latency.

### 4. Availability and cost remain part of the result

The planned metadata delay produced 32 unavailable group assessments. Recovery
occurred **20.1–20.5 seconds after application**, or **11.5–13.1 seconds after the
first affected completed-window report**. With metadata available, the first
affected report was already correct. These numbers include the chosen
ten-second measurement windows and are not universal recovery bounds.

For the 32 policy applications, the first available correct policy report
arrived **2.7–492.6 ms** after application, with a median of **188.2 ms** under
the independent half-second polling loop.

The complete log-ratio state was available in **135 of 181 emitted report
batches**. It was unavailable in 16 because of missing lineage and in 30 because
of zero parts. Zero retries can still give a valid policy ratio; no attempts
cannot. No pseudocount or artificial trajectory interpolation was used.

Median per-history observer-call times, summarized by their median, were
**38.5 microseconds for updated direct ratios and 48.5 for CoDA**. These are
descriptive fixed-order Python timings; they exclude collection, network and
instrumentation overhead and do not establish a system-wide overhead bound.

The deployment script emitted two root group annotations and five successor
lineage records per history. No manual in-run repair occurred. The cost is an
explicit supported mapping contract, not automatic semantic discovery.

## What this supports, and what it does not

The result supports passive observation of a locally useful adaptation, the
associated change in attempt composition, and changing interpretations under
current constraints and component mappings. CoDA supplies the complete
relative state and a coherent scale and direction of proportional movement.
Its geometry is established mathematics; runtime reconstruction is the new
implementation check here.

Accuracy gains over the fixed schema belong to **updating the measurement
contract**. They cannot be attributed uniquely to CoDA, because updated direct
rules matched it. Stable logical-group labels could also be maintained at the
metric producer; this experiment does not establish that a separate lineage
observer is necessary or better than that deployment choice.

The [separate reduced log-odds replay](directional-v0.1.0/reduced-v0.1.0/README.md)
uses two histories `log(R/F)` with the same policies, smoothing and availability.
It reproduces all policy orientations and first constraints of the full-state
calculation on the common mask. These outputs do not require all three ILR
coordinates.

Scope is limited to supported annotated forwarding transitions, controlled
delivery faults, and the specified policy. No failure prediction, causal model
of accidents, general architecture extraction, operator study, or prevention
of service violations is established.

## Evidence and reproduction

[One complete history](full-history.png) ([vector figure](full-history.svg))
uses the smallest block ID, not an effect-selected example. Panel C shows two
orthonormal policy-normal coordinates and omits the third ILR coordinate;
complete vectors remain in the data. Missing and zero-part intervals are not
bridged. Panel D shows emitted reports, not continuously correct coverage.

- [All per-history summaries](analysis/summary.json).
- [Every diagnostic assessment](analysis/diagnostic-comparison.csv).
- [Actual execution windows](analysis/execution-windows.csv).
- [Complete relative vectors](analysis/geometry.json).
- [Call-level interpretation and policy-only witnesses](analysis/interpretation-stats.json).
- [Native engine identity](engine.json) and [all native verification outcomes](promql-validation.json).
- [Export provenance](provenance.json) and [compressed primary replay inputs](inputs/).

```sh
python -B evolving-state/scripts/analyze.py --inputs evolving-state/results/campaign-v0.1.1/inputs --output artifacts/evolving-replay
python -B -m unittest discover -s evolving-state/tests -v
```

`describe.py --bundle evolving-state/results/campaign-v0.1.1` regenerates the
descriptive call analysis. After installing `evolving-state/plot-requirements.txt`,
`render.py --bundle evolving-state/results/campaign-v0.1.1` regenerates the
figure. Native replay is available with the pinned engine:

```sh
python -B evolving-state/scripts/promql_check.py --inputs evolving-state/results/campaign-v0.1.1/inputs --output artifacts/evolving-native --promtool /path/to/promtool
```
