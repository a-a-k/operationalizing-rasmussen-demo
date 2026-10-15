# Frozen prediction of remaining checkout CPU transfer

This small exploratory campaign tests a concrete question: **after calibration,
how much checkout CPU does a fixed model permit transferring to advertising,
and does a new descending run violate checkout SLO before that allowance is
exhausted?** Revision 0.1.1 repeats all six runner blocks after an actuator-grid
correction; its results are not yet available.

It follows the [static calibration](../README.md) and
[paired transition comparison](../history/README.md), without changing either.
It does not test recovery from overload. No learned classifier, alert comparison,
RAM intervention or new global-system safety criterion is introduced.

## One independent unit: a runner block

The [fixed design](design-v0.1.1.json) gives each of six runners this sequence:

1. Five fixed-quota calibrations: checkout CPU 0.30, 0.22, 0.16, 0.12 and 0.08.
   Each starts a fresh stack and fresh volumes. A hash-fixed order differs by
   block. Each has 180 seconds of warmup and two 60-second measurement windows.
2. Fit the single declared model using only those ten measurement windows.
   Freeze its parameters, prediction, recommendation, complete validation plan
   and calibration-input hashes. Upload `frozen-forecast.json` before the next
   workflow step. A model abstention is retained, not silently replaced.
3. On the same runner, start another fresh stack at 0.30 checkout CPU. Keep
   load continuous and descend through the predeclared quota grid. Add the
   recommended endpoint to this grid so that it is actually measured.
4. Independently rescore retained per-operation events and compare observations
   with the previously frozen predictions. Validation never refits the model.

For every allocation, checkout plus advertising CPU is 0.70. The complete
eleven-service sum is 3.4 CPU ceilings. Every other CPU and RAM limit is fixed.
These are administrative ceilings, not guaranteed processing capacity.
Both streams remain fixed: 40 checkout operations/s and 100 ad requests/s;
each preallocates exactly 512 VUs. The CPU quota period remains 100,000 us.
Runtime images, Actions and upstream code use the existing pinned versions.

Calibration and validation sharing a runner reduces, but does not remove,
environmental variability. It does not attribute variation to CPU hardware
alone. Windows within one runner are not independent replications. There is
no simultaneous unchanged control in this campaign; the prediction is conditional
on the declared allocation path and workload, not a causal attribution of every
latency change to CPU quota.

## Model, fit and recommendation

For checkout quota `q`, offered checkout rate `lambda = 40/s`, nonnegative
offset `b` in milliseconds and critical quota `c > 0`:

```text
L(q) = b + 1000 * ln(20) * c / [lambda * (q - c)]    if q > c
L(q) = infinity                                      otherwise
effective service demand d = c / lambda
```

In an ideal M/M/1 queue with service rate `mu = q/d`, the system-time p95 is
`ln(20)/(mu-lambda)`. This
[queueing result](https://www.stat.uchicago.edu/~yibi/teaching/stat317/2021/Lectures/Lecture19.pdf)
motivates the formula; **it does not establish its adequacy for this deployment**.
Constant-rate arrivals, multiple services, variable processing demand, failures
and [periodic CPU throttling](https://www.kernel.org/doc/html/latest/scheduler/sched-bwc.html)
violate the ideal assumptions. `b` represents a fixed residual delay and `d` is
an effective fit, not an independently measured physical service demand. This
experiment tests this two-parameter approximation, not all queueing models.

The deterministic search tries positive `c` multiples of 0.0005 below the
smallest quota with an exact calibration p95, and `b` multiples of 1 ms from
zero through the smallest exact p95. At least three distinct exact-quantile
quota levels are required. Minimize summed squared log residuals; for a
censored p95 use only the squared deficit below its lower bound. Ties use
smaller `c`, then smaller `b`. Parameter-grid edges and fit loss are reported.
There is no model selection or threshold tuning on validation data.

The latency boundary solves `L(q) = 500 ms`. An explicit additional empirical
guard forbids quotas at or below the largest calibration quota with an
unsuccessful fraction of at least 1%. This guard is not a model of failure
probability. Both conditions must permit a quota. The continuous combined boundary
is retained unrounded. The executable recommendation is rounded upward to a
0.01-CPU endpoint, strictly above the error guard and within
the tested range 0.08--0.30. A boundary below the tested range is marked as such,
not empirically validated by extrapolation. If no positive in-range transfer is
permitted, the model abstains. No confidence guarantee or safety margin derived
from uncertainty is claimed by this first check.

For example, a computed minimum of 0.125946 CPU becomes a command of 0.13 CPU
for checkout and **0.57 CPU** for advertising, preserving their 0.70 sum.
The advertising quota is the remainder, not a separately upward-rounded value.
This reduces the recommended transfer by about 0.004054 CPU relative to the
continuous model limit. This is rounding conservatism relative to the model,
not a safety guarantee. With a binding strict error guard, an endpoint exactly
on that guard advances by one full grid step.

The model's parameter grid and analytic root precision are unchanged. Near
the previously observed transition zone, the sampled crossing bracket is now
0.01 CPU wide, unless there is no crossing; earlier fixed-grid gaps are wider.
Agreement inside a bracket does not establish finer accuracy, monotonic runtime
behavior or safety between measurements. Small overpredictions can remain
unresolved. Reports retain the continuous prediction, executable recommendation,
rounding amount and sampled bracket width separately.

## Validation path and primary outcome

Checkout starts at 0.30 CPU. The baseline cohort covers load age 180--240 s;
it must meet **checkout** SLO to enter the primary comparison. It is not a claim
that advertising or every system requirement is satisfied, nor proof of
stationarity. The first update is at 270 s; subsequent updates are 90 s apart:

```text
0.30 -> 0.26 -> 0.22 -> 0.20 -> 0.19 -> 0.18 -> 0.17 -> 0.16
     -> 0.15 -> 0.14 -> 0.13 -> 0.12 -> 0.11 -> 0.10 -> 0.09 -> 0.08
```

The frozen recommended quota is inserted in descending order if absent.
Each update first reduces checkout and then increases advertising; temporary
under-allocation and actual update times are recorded. All effective limits
are read back. Each primary cohort starts 10 seconds after its scheduled update
and lasts 60 seconds. The first 10 seconds and remaining inter-step gaps are
also scored and retained separately. This timing is a specified observation
window, **not** a universal claim about stabilization or safety during excluded
seconds. The entire fixed path is executed, but primary crossing analysis ends
at its first observed unsafe primary cohort; later points are diagnostics.

Checkout safe means p95 at most 500 ms and unsuccessful operations below 1%.
The principal result is the number of runner blocks whose **first unsafe
primary point was permitted by the frozen model and guard**, divided by blocks
with valid calibration, technically valid validation, a checkout-safe baseline
and an in-range recommendation. No majority or other binary success criterion
is applied. Always report all six block statuses, abstentions, invalid baselines,
technical failures and missing blocks with that fraction.

For each usable block also report:

- Predicted transfer limit and the rounded recommended transfer, in CPU units.
- Last-safe/first-unsafe sampled transfer bracket and how far the predicted
  limit lies outside it. This bracket describes the sampled sequence, not an
  exact deterministic continuous boundary. No crossing is a censored result.
- Actual outcome at the recommended point, including whether it was reached
  only after the first violation; those later outcomes are not new independent
  tests from a safe state.
- Prediction error for non-censored p95, failure fractions, and separately the
  permitted transitions that violated checkout SLO.
- Advertising outcomes, actual offered/completed rates, client outstanding
  operations, restart/OOM events and cgroup diagnostics.

## Timeouts and technical validity

All failed, unfinished and dropped operations remain unsuccessful for SLO.
The p95 label retains the earlier response-duration definition. For model
fitting, HTTP timeout code 1050 is explicitly recorded, following the
[k6 error-code reference](https://grafana.com/docs/k6/latest/javascript-api/error-codes/).
A recorded timeout duration bounds a latent response from below; it is not an
exact successful completion time. Missing durations have bounds `[0, infinity)`.
Quantile bounds are calculated by the same type-7 interpolation on per-operation
lower and upper bounds. If they differ, only the lower p95 bound enters the fit.
Low-latency failed responses remain visible in the failure fraction; their
recorded response durations are not interpreted as successful service times.
Client outstanding counts do not measure internal server queue lengths.

Missing primary data, generator failure or failed setup is infrastructure-invalid.
Before calibration on every runner, two disposable idle containers test all
23 executable checkout/advertising quota pairs from 0.30/0.40 to 0.08/0.62.
The check uses the pinned load-generator image, both combined CPU/memory and
CPU-only updates, and reads back actual cgroup limits and the quota period.
It archives `quota-preflight.json` and Docker/cgroup-driver diagnostics, then
removes those containers before starting the first fresh experimental stack.
A mismatch aborts before load and must be investigated, not retried to seek
a passing host. All experimental-stack readbacks remain in place as well.
Quota/readback, update-timing or delivered-load mismatches are explicit comparison
quality failures; measured outcomes remain available. Restart/OOM never changes
the checkout SLO label and is never itself an automatic exclusion or retry.
The predeclared capacity is sufficient for the client timeout envelope; drops
are nevertheless retained as failures and flag a load-delivery mismatch.
Retries are limited to infrastructure failures and repeat the **whole** block.
The latest whole attempt is selected regardless of outcomes; attempts are never
spliced and earlier attempt statuses remain in the aggregate.

## Relative movement and the coordinate check

Let `a(q)` be the complete eleven-part CPU vector, with checkout `q`, advertising
`0.70-q`, and fixed remaining components. Write `x(q) = a(q)/3.4`, and let
`z(q) = H log(x(q))` for the declared orthonormal Helmert contrast matrix `H`.
The inverse restores the same allocation; the absolute budget remains explicit.

The implementation solves the latency boundary once analytically in quotas and
again numerically through `q -> z(q) -> inverse ILR -> checkout quota -> L`.
These roots must agree within 1e-9 CPU. Both calculations use the **same physical
path and model**: agreement verifies coordinates, not model accuracy or empirical
superiority of CoDA.

Along this path record two distinct relative quantities:

```text
endpoint distance D(q0,q1) = ||z(q1)-z(q0)||_2
path length       S(q0,q1) = integral ||dz(q)/dq||_2 dq, between q0 and q1
```

Equal additive checkout-to-ad transfers need not be equal relative changes.
The additive path is generally curved in ILR coordinates, so endpoint distance
is not interchangeable with its accumulated length. Length uses fixed
256-interval Simpson integration. Remaining CPU to the predicted boundary is
signed; the two relative magnitudes are unsigned and interpreted with that sign.
All ten ILR coordinates are retained by the transformation: no selected group
balance is substituted for the full composition.

## Actuator correction and preceding campaign

The unchanged [0.1.0 design](design-v0.1.0.json) requested a model-dependent
extra point at thousandth-CPU precision. In its six-block execution, five such
points were rounded upward by the runtime: both checkout and advertising gained
CPU, increasing their combined effective limit from 0.70 to 0.71. The quota
checks correctly marked those five blocks comparison-invalid. The sixth block
was fully comparison-valid and recorded an unsafe transfer permitted by the
model. Correcting the actuator does not erase that model failure.

Revision 0.1.1 adapts executable limits to the hundredth-CPU grid and adds the
preflight. The mathematical model, fit, five calibration quotas, base validation
grid, workload, timing and outcome definitions are unchanged. The additional
recommended point can move or coincide with an existing grid point, so its
insertion and subsequent timestamps can differ. This is a new campaign, not a
retroactive relabeling of old observations. Calibration and validation are both
repeated; results are not pooled. The prior implementation remains in version
history for replay of the original artifacts.

## Running and reading artifacts

Dispatch `boundary-frozen-prediction` with the exact implementation commit in
`expected_sha`. All runtime work is in GitHub Actions. The six jobs run in
parallel; expect approximately 60--75 minutes plus queue time, with a 120-minute
per-job cap. Local checks do not start Docker:

```sh
python -B -m unittest discover -s boundary/prediction/tests -v
python -B boundary/prediction/scripts/prediction_run.py matrix
```

The workflow publishes one pre-validation frozen-forecast artifact and one
complete artifact per block. The aggregate contains `RESULTS.md`, `blocks.csv`,
`points.csv`, `windows.csv`, `summary.json` and `diagnostics.json`.
An additional small diagnostics artifact contains the forecast, block status,
host details, preflight and quota readbacks, so checking limit application does
not require downloading raw load-generator records.
Raw block artifacts contain all primary events, k6 metrics/counters, frozen
forecasts, image inspections, rendered Compose, limit readbacks and runtime
diagnostics. Recompute from downloaded block artifacts with:

```sh
python -B boundary/prediction/scripts/prediction_analyze.py --inputs downloaded-blocks --output-dir artifacts/prediction-recomputed
```

Artifacts have 90-day retention; archive the primary records and frozen forecasts
before expiration. A failed boundary prediction is an experimental result, not
grounds to silently change this design and report a replacement as confirmation.
