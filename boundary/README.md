# Static CPU boundary calibration

This separate exploratory experiment asks whether a checkout SLO transition is
reproducible under fixed quotas and controlled offered load. It does not fit a
performance model, test adaptation, or compare coordinate systems.

Separate follow-ups are the [paired transition comparison](history/README.md)
and the [frozen boundary-prediction check](prediction/README.md). The latter
calibrates per runner before independently testing a fresh descending path;
it does not retrofit a model to this static campaign's validation outcomes.

The first completed campaign and its retained primary evidence are available
in [the results interpretation](results/static-v0.1.0/README.md).

The separate [paired history follow-up](history/README.md) tests whether identical
endpoints behave differently after a quota decrease, recovery, or unchanged control.
It does not change the completed static campaign.

## Fixed experiment

The [design](design-v0.1.0.json) specifies six checkout CPU ceilings
(0.45, 0.30, 0.22, 0.16, 0.12, 0.08 cores), each on three fresh runners.
The checkout/ad sum remains 0.70 cores: CPU removed from checkout is assigned
to ad before the load begins. Other quotas and all memory ceilings stay fixed.
The sum of the eleven CPU ceilings remains 3.4 cores; these are not reservations.
The actual cgroup CPU period must be 100,000 microseconds.

Each runner has continuous, independent arrival-rate scenarios: 40 order
operations/s and 100 ad requests/s. There is a fixed 180-second warmup followed
by three 60-second observation windows, without stopping generators between
windows. Fixed warmup is not a guarantee of equilibration: trends across all
three later windows are part of the result. Every quota receives a fresh stack;
no safe baseline is required and no low-quota failure is replaced.

Ads now use an open arrival process, unlike earlier closed-loop scenarios.
This deliberately controlled background load is a new condition. Maximum VUs
equal preallocated VUs; the design records timeout-based capacity bounds.

## Evidence and interpretation

Primary start/finish records identify each operation, scenario origin and
latency. Windows use operation-start cohorts; late completions remain in their
original cohort. Checkout p95 includes completed failed HTTP requests and
timeouts. Unsuccessful operations include failed, unfinished and dropped
attempts. SLO-safe means p95 at most 500 ms and unsuccessful fraction below 1%.
Actual starts, completions and drops are reported separately. Load-delivery
failures retain their outcomes but cannot establish a controlled-load boundary.

Client outstanding counts are reconstructed from starts and finishes, including
operations begun in earlier windows. They are not internal server queue lengths:
server work may continue after a client timeout. Cgroup samples, CPU throttling,
host and generator load, memory, container events, rendered Compose and image
inspection are retained. Restart/OOM remains a system diagnostic, not an
automatic exclusion or replacement for measured SLO labels.

One fresh-runner trial is the independent unit. Its three measured windows are
repeated observations. Report every window and classify each runner as all-safe,
all-unsafe or mixed; do not count nine windows as nine independent replications.
An observed transition band is not an exact deterministic boundary. A successful
static calibration would still need a separate test after resource changes.

## Execution

Dispatch the `static-boundary-calibration` workflow with the exact commit in
`expected_sha`. The workflow runs eighteen jobs and independently rescores their
retained records before aggregation. All runtime execution is in Actions.

Small local checks:

```sh
python -B -m unittest discover -s boundary/tests -v
python -B boundary/scripts/run.py matrix
```

Recompute the saved results without starting Docker:

```sh
python -B boundary/scripts/analyze.py --inputs boundary/results/static-v0.1.0/evidence --output-dir artifacts/static-boundary-recomputed
```

Artifacts are retained for 90 days. Archive the compact results and primary
records before expiration. Infrastructure retries keep the same inputs and
record run attempt; unsafe completed trials must not be retried for outcome
selection. Aggregation uses the latest attempt per trial ID, irrespective of
SLO outcome, and retains every attempt status. Earlier artifacts remain available.
