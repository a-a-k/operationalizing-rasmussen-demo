# Evolving-state observation

Status: [eight new histories completed](results/campaign-v0.1.1/README.md), with
the two engineering executions retained separately. All available updated
diagnoses matched the event oracle. Updated direct ratios matched CoDA; the
comparison does not establish uniquely superior compositional policy detection.
This separate experiment does not replace or revise previous campaigns.

## Question and scope

Can a passive observer keep its account of execution, current constraints and
relative movement meaningful while components and policies change?
The study separates a change in execution, a change in its representation, and
a change in the allowed limit. These can occur together.

The application is the pinned OpenTelemetry Demo. An instrumented client layer
issues real catalog and currency reads through replaceable forwarding workers.
Controlled delivery faults are injected **after real upstream operations**.
Increasing the permitted attempts is a scripted local adaptation: successful
logical requests and extra attempt load are measured, not assumed to improve.
This is not natural production drift, arbitrary lineage discovery, or an
automatic adaptation controller.

The [current definition](design-v0.1.1.json) specifies the schedule and runtime inputs.
The [initial engineering definition](design-v0.1.0.json) is retained separately.
Runtime workloads execute only in the [dedicated hosted workflow](../.github/workflows/evolving-state.yml).
Local work is limited to unit checks and saved-data analysis.

## Measurement contract

For group `g` and a completed, nonoverlapping ten-second window:

- `F_g`: starts of first attempts at this one client layer.
- `R_g`: starts of subsequent attempts for those logical calls.
- `r_g = R_g / (F_g + R_g)`: retry fraction among physical attempt starts.
- `rho_g(t)`: the policy actually effective at the atomic snapshot time.
- `m_g(t) = rho_g(t) - r_g(t)`: current policy margin.

An attempt belongs to its start window, even if its response arrives later.
A retry may therefore be in a different window from its first attempt.
Logical request completions are separate diagnostics, never the denominator of
the attempt policy. Only this client layer is measured; internal application
retries are not combined with it.

The windowed fraction is our precise experimental policy. Retry budgeting has
a [practical motivation](https://sre.google/sre-book/handling-overload/), but
this fraction is not claimed to reproduce every product's budget semantics.
Exceeding it establishes a policy violation, not proof of application overload.
It is an observational requirement, not an enforced rate limiter: none of the
three observers changes retry decisions.

For comparable group scopes, `delta_m = delta_rho - delta_r`. This is a
decomposition of a changed diagnosis, not proof of a causal application mechanism.
Policy publication, actual application and observer receipt are recorded
separately. A threshold change can create a violation without preceding drift.
Pointwise reconstruction is checked as of the snapshot's `generated_ms`.
Time-weighted coverage additionally counts the delay before the next poll:
a held report can become stale when a policy changes or a new window completes.
This delay is not silently counted as correct observation. External k6 response
records separately check successful logical completions at the requesting client.

The complete composition has four parts, in order:
`catalog:first, catalog:retry, currency:first, currency:retry`.
We retain counts and per-component detail alongside three orthonormal ILR
coordinates, accumulated displacement, increments and their EWMA (`alpha=0.2`).
The reference is the first complete positive window, not an assumed equilibrium.
Direction is movement of attempt composition, not automatically direction to
failure. No time-to-failure prediction is evaluated here.

Zeros are not repaired with pseudocounts. Zero retries with positive first
attempts give a valid zero ratio but unavailable complete log geometry. No
attempts give no ratio observation. Missing lineage, missing policy and missing
telemetry are different from either zero case. Movement is not interpolated
across unavailable windows.
When a policy or metadata event re-emits the same completed window, its
per-window increment is retained, not added to the EWMA a second time.

## Fair comparisons

All observers receive the same available telemetry and versioned metadata.

1. **Fixed initial schema:** a staleness ablation, not a production benchmark.
2. **Updated direct ratios:** current grouping and policy, ordinary arithmetic.
3. **Updated composition:** the same extraction, with full relative geometry.

The direct comparison is deliberately not restricted to obsolete container
names. Native PromQL replay checks aggregation and ratio arithmetic using
component-to-group metadata joins. This validates the practical arithmetic;
it does not measure a full deployed Prometheus alerting pipeline's latency.

For positive counts, the policy is also
`log(R/F) <= log(rho/(1-rho))`. Direct and compositional decisions should agree.
Their agreement is a correctness result, not superiority of one geometry.
The updating pipeline and relative geometry have separate evidential roles.

## Updates and independent evaluation

Forwarding workers really start, split, are replaced and merge. The supported
mapping comes from explicit deployment annotations and lineage records.
This instrumentation is part of the cost of the method. A known logical
group survives these transitions; arbitrary scope changes are not silently
treated as comparable. A controlled metadata delay measures unavailable time,
not merely a test that a missing label can be detected.

The observer never reads scenario names, the intervention schedule, request IDs
or the evaluator journal. The evaluator reconstructs attempt counts from
individual client events and logical route identities, not from the observer's
aggregate output or its component mapping. Independent forwarding logs provide
an additional check of actual upstream calls. Application timestamps determine
the true policy; publication timestamps do not substitute for them.

A real split may change execution. We check that canonical reconstruction
matches the actual event population, not that every split produces zero motion.
Pure re-expression of the same recorded events is checked separately.

## Reporting

Each fresh hosted runner is one history. Compare observers within history.
Report reconstruction and policy errors, margin decomposition error, update
latency, trustworthy/unavailable/stale coverage, computation cost and explicit
annotations. Report useful logical completions and physical attempt load
separately. Do not count correlated windows as independent replications.

The initial engineering run validates execution and recording. Eight fresh
histories followed this gate, with all attempts retained. This is a
small descriptive PoC, not a reliability claim or a success-by-majority test.
No automatic rollback, operator benefit or prevention of service violations
is established by this passive study.

The initial engineering execution had 18 windows, no dropped load iterations and
4,442 successful upstream reads. All available updated diagnoses matched the
individual event journal and native PromQL. It also exposed 23 client attempts
without a forwarding-worker receipt during component startup, and one late
request in the nominal idle window. Revision 0.1.1 adds readiness checks and a
second idle window, and decouples observer polling from intervention execution.
The policy-only sequence is relaxed then tightened to exercise a policy-only
boundary contrast. These refinements precede the descriptive campaign; the
initial execution is not pooled with it.

Evidence:

- [Initial engineering execution](results/engineering-v0.1.0/README.md).
- [Refined engineering execution](results/engineering-v0.1.1/README.md).
- [Main eight-history results, interpretation and reproduction](results/campaign-v0.1.1/README.md).
- [Conditional direction and policy-boundary distance](results/campaign-v0.1.1/directional-v0.1.0/README.md):
  a versioned retrospective extension, independently checked on the same paths
  in the original parts. It separates current policy status, latest motion,
  smoothed motion and changed constraints; it is not a future-violation forecast.
