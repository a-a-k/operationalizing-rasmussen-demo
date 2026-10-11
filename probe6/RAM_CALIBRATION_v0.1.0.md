# RAM range: a separate engineering check

The first four-history engineering execution observed no memory-cap events.
Checkout peaks were approximately 25--35 MiB, while its smallest tested ceiling
was 64 MiB. The twenty-block joint-resource campaign therefore did not start.
That executed design, runtime and runner remain unchanged.

This bounded follow-up consists of nine independent GitHub runners: one unchanged
256-MiB control and checkout ceilings of **64, 48, 40, 36, 32, 28, 24 and 20 MiB**.
Every job begins with the same fresh 256-MiB checkout / 512-MiB advertising
allocation, a 30-second warmup and a 60-second initially safe baseline. It then
applies one target, followed by 10 seconds of stabilization and a 60-second test.
The two configured memory ceilings always target a sum of 768 MiB; reduced
checkout memory is transferred to advertising. Swapping is disabled. Updates
are donor-first and not atomic across containers, with a complete command journal.

CPU remains checkout/payment/shipping 0.30 each and advertising 0.10. Checkout
load remains 40 scheduled operations/s with 800 fixed VUs, alongside 8 advertising
VUs. Application code, GOMEMLIMIT=192MiB for checkout, restart policy and every
other runtime setting are inherited and unchanged. No memory-consuming feature,
new synthetic workload or outcome-targeted grid search is added.

All nine conditions execute regardless of observations. One trial per ceiling is
enough for this engineering screen, not to establish a reproducible safe limit.
Kernel memory-cap events, Docker OOM diagnostics and the externally measured SLO
are separate fields. OOM/restart never overrides the SLO label or automatically
excludes a point. Resource mismatches and primary-data loss are technical-invalid;
every readable outcome remains available. Failed client update commands are
archived, both sides are attempted, and actual persisted/live limits determine
whether the target manipulation succeeded.

The new inputs are `ram-calibration-design-v0.1.0.json` and
`ram-calibration-runtime-v0.1.0.json`; the parent runner and runtime are hash-pinned.
Run `ram-range-calibration` with its exact commit in `expected_sha`.
This workflow has no automatic follow-on campaign or parameter selection.
It saves full evidence for 14 days and compact `summary.json`,
`condition-level.csv` and `RESULTS.md` for 90 days; archive before expiry.

Locally run only lightweight checks:

```bash
python -B -m unittest discover -s probe6/tests -v
python -B probe6/scripts/ram_calibration.py verify
```
