# Does the same endpoint behave differently after different histories?

This small follow-up to the [static calibration](../results/static-v0.1.0/README.md)
tests history dependence, not a fitted boundary or a warning classifier.
The previous 0.08–0.16 CPU transition band is descriptive and specific to the
checkout/ad exchange and controlled load. It is not a confidence interval or
a guaranteed safe CPU threshold.

## Fixed comparison

The [versioned design](design-v0.1.0.json) defines twelve runner blocks: two
checkout endpoints (0.12 and 0.16 CPU) with six repetitions each. Every runner
executes three paths sequentially, with a **fresh stack and fresh volumes before
each path**. The six permutations of path order occur once per endpoint; their
assignment to repetitions is fixed before execution. Paths share the host but
not application state. Blocking and order balancing reduce, not eliminate,
host and sequence effects.

| Path | Initial checkout CPU | Checkout CPU after 180 s |
|---|---:|---:|
| Decrease | 0.30 | endpoint |
| Recover | 0.08 | endpoint |
| Control | endpoint | unchanged endpoint |

Checkout and ad always have an endpoint sum of 0.70 CPU. All other CPU and RAM
limits match across paths; the eleven CPU ceilings total 3.4 cores. Endpoint
identity is checked for **all** resource limits, not checkout alone. Initial,
endpoint and final cgroup readbacks verify the 100,000 us CPU period. During the
two sequential updates the donor is reduced first, briefly underspending the
budget; both actual timestamps are retained. The control receives two no-op
updates at the same time. These are configured ceilings, not CPU reservations.

The recovery path intentionally begins in the previously overloaded regime.
It tests persistence or recovery, not a safe resource-management policy.
There is no safe-baseline filter, outcome-driven stop or rollback.

## Common timeline and load

Reuse the pinned stack and unchanged static workload: constant 40 checkout
operations/s and 100 advertising requests/s, independent open-loop scenarios,
512 preallocated/maximum VUs per stream, and unchanged request timeouts. All
runtime execution takes place in Actions; local tests do not start containers.

Time is measured from the **actual checkout scenario start**, not Docker launch:

- 0–180 s: three visible diagnostic windows at the initial allocation.
- At 180 s: apply the shared endpoint without stopping generators or the stack.
  Both updates must finish by 182 s for the controlled comparison.
- 180–190 s: retain a separate transition interval, including all failures.
- 190–490 s: five aligned 60-second cohorts, beginning 10, 70, 130, 190 and
  250 seconds after the planned transition. The first is the earliest resolved
  post-transition window, not a measurement of the first ten seconds.
- 30 s graceful stop; late finishes remain in their original start cohort.

The control has exactly the same load age and observation times. The stack is
never reset at the endpoint; otherwise history would be erased. The fixed
prehistory duration is not a guarantee of stationarity.

## Outcomes and interpretation

Checkout safe means p95 at most 500 ms and unsuccessful fraction below 1%, as
in the static calibration. Failed, unfinished and dropped attempts remain in
the failure fraction. Completed timeout durations remain in descriptive p95;
status-zero and near-deadline counts are also reported. They are not exact
successful server response times and cannot simply be omitted from a later
performance-model fit. No such model is fitted here.

For each runner and post-transition window, report signed p95 differences for
decrease-minus-control, recover-minus-control, and decrease-minus-recover,
together with error fractions, SLO labels, delivered rates and outstanding
client operations. All windows are retained. Client outstanding work is not
an internal queue measurement and may omit server work left after a timeout.

**50 ms**, one tenth of the existing latency limit, is declared in advance as
the practical resolution for a latency difference in this PoC. Differences
above it are operationally noticeable at that resolution. This is not a
universal threshold, statistical equivalence test, power justification, or
binary campaign success criterion. Exact differences and their runner-level
range/median remain visible. Matching SLO labels does not imply matching p95;
matching p95 does not imply matching error rates.

Differences persisting at the same endpoint support including history or
execution state when applying a static boundary. Differences becoming small
after a dwell would support approximate endpoint agreement **over the observed
windows and conditions**, not prove stationarity or a universal settling time.
Agreement throughout would mean no material history difference was observed
at this temporal and latency resolution. Failure events and actual load must
be considered before interpreting any contrast. None of these outcomes alone
validates a queueing model, computes a directional margin, or compares CoDA
with another representation.

Restart/OOM is a system diagnostic, never an automatic exclusion or substitute
SLO label. Missing primary data or generator failure is infrastructure-invalid.
Completed quota, timing or load-delivery mismatches retain measurements but are
not used as controlled paired contrasts. An infrastructure retry repeats the
**whole block** on a new runner; aggregation selects the latest block attempt
regardless of outcomes and never mixes its paths with an earlier attempt.

## Execution and evidence

Dispatch `boundary-history-comparison` with the exact commit in `expected_sha`.
Twelve parallel jobs each execute three fresh-stack paths. The aggregate job
independently rescores the primary records before producing paired contrasts.

Small local checks:

```sh
python -B -m unittest discover -s boundary/history/tests -v
python -B boundary/history/scripts/history_run.py matrix
```

Recompute downloaded artifacts:

```sh
python -B boundary/history/scripts/history_analyze.py --inputs artifacts/history-inputs --output-dir artifacts/history-recomputed
```

Artifacts retain raw starts/finishes, k6 metrics and counters, actual update
times, resource/host samples, container failure events, rendered Compose,
digest-pinned image inspection and cgroup checks. Runtime artifacts expire
after 90 days; preserve compact primary evidence before expiration.
