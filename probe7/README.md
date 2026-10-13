# Guarded multi-resource adaptation

Separate PoC execution on the digest-pinned full OpenTelemetry Demo, with
accounting and Kafka enabled. Nothing is pooled with earlier series.
Eleven selected components have separately closed CPU and memory ceilings;
their full composition state has twenty ILR coordinates. Observed trajectory
dimension is assessed separately.

## External requirements

- Checkout request p95 <=500 ms and unsuccessful scheduled operations <1%.
- At least 99% of advertising attempts obtain a nonempty response within 200 ms.
- At least 99% of confirmed orders appear as committed accounting records within 5 s.

The last two are experimental policies, not requirements supplied by Demo.
Orders are joined by ID. PostgreSQL commit timestamps are enabled before the
fresh stack processes orders; client confirmation is the starting timestamp.
Late and missing records remain violations. No geometry assigns an SLO label.

## Engineering stage and main series

The active [technical pilot](pilot-design-v0.1.1.json) uses two fresh runners with
counterbalanced CPU/RAM trial order. It establishes measurement feasibility
and actual recipient benefit. The [main definition](design-v0.1.1.json) remains
not-ready until that check is assessed. It proposes three initial allocations,
two loads and four repetitions: 24 paired fresh-stack histories, with twenty
bounded cycles each. CPU and RAM eligibility may be revised before execution
if advertising does not benefit from a resource; dimensionality is never
manufactured by pointless transfers.

The PARTIES-inspired controller selects a donor using observed requirement
headroom and resource reserve, evaluates the changed state and rolls back
unsafe/near-boundary changes. Controller reserves are engineering guards, not
statistical success criteria. Restoration has priority over further advertising
improvement. The compositional analysis is an observer, not an input to policy.
Failed attempts, reversals, safe histories and missing data remain visible.

The comparison uses fixed selected log-ratios, full share changes and full ILR
changes on the same histories. Analog searches exclude the entire runner pair
and match workload profile. No superiority or boundary crossing is promised.

## Execution

Use [guarded-adaptation.yml](../.github/workflows/guarded-adaptation.yml) with
the exact expected_sha and mode=pilot first. All runtime work is in Actions.
Local checks start no services:

```bash
python -B -m unittest discover -s probe7/tests -v
```

Native checkout streams and order confirmation/commit observations are retained.
Advertising retains native counters and quantiles rather than every RPC trace.
Resource samples, quota readbacks, rendered Compose and image inspection are
separate integrity evidence. Memory totals and CPU totals are administrative,
not reserved host capacity; unselected services and generators are context.

## Technical revision

The first v0.1.0 attempt had one disappearing-PID diagnostic parsing error after
an advertising restart; its primary observations remain archived separately.
The other runner completed all engineering windows. v0.1.1 ignores unavailable
diagnostic frames without overriding primary SLO labels, records Docker events,
raises advertising's startup reserve to 512 MiB, and warms up for 120 seconds.
The images and three external requirements are unchanged. A fixed 10-ms retry
backoff bounds failed advertising reconnection attempts. No main observations
have yet been collected; the earlier draft is not an alternative active design.
