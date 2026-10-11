# Fixed follow-up: descriptive results

These are new observations only; no pooling with historical probes.

No fitted alert threshold, majority criterion, optional extension or binary scientific pass/fail.

## ab

| Point | Valid | Unsafe (valid) | Unsafe (all recoverable) | Post-intervention failures | p95 median, valid (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 16 | 0 | 0/16 | 0 | 88.16797410000001 |
| B | 16 | 10 | 10/16 | 9 | 10000.760116675 |

| Comparison | Left safe / right unsafe | Reverse | Discordant |
| --- | ---: | ---: | ---: |
| radial_reversal | 10/16 | 0/16 | 10 |

## context

| Point | Valid | Unsafe (valid) | Unsafe (all recoverable) | Post-intervention failures | p95 median, valid (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| balanced_021 | 12 | 1 | 1/12 | 0 | 137.51753324999987 |
| checkout_015 | 11 | 4 | 4/11 | 4 | 288.8866683499998 |
| payment_015 | 12 | 0 | 0/12 | 1 | 127.45945142499997 |
| shipping_015 | 11 | 0 | 0/11 | 0 | 109.13800184999994 |
| anchor_019 | 10 | 1 | 1/10 | 0 | 165.0387905749999 |
| payment_011 | 12 | 8 | 8/12 | 9 | 5000.968545725 |

| Comparison | Left safe / right unsafe | Reverse | Discordant |
| --- | ---: | ---: | ---: |
| sum_vs_checkout | 4/11 | 1/11 | 5 |
| sum_vs_payment | 0/12 | 1/12 | 1 |
| sum_vs_shipping | 0/11 | 1/11 | 1 |
| fixed_checkout_context | 5/10 | 0/10 | 5 |
| same_balance_checkout_payment | 0/11 | 4/11 | 4 |
| same_balance_checkout_shipping | 0/10 | 3/10 | 3 |

Matched sums/counts show representational ambiguity only when observed outcomes differ.
A differing balance is not by itself evidence that it predicts SLO or beats minimum-quota rules.
Discordance at the same balance limits the sufficiency of that scalar coordinate.
Timeout-saturated p95 is a censored severity measure. Technical-invalid points are retained in the all-recoverable analysis.
The no-snapshot-failure comparison is a conditional diagnostic subset, not an independently randomized CPU-only experiment.

Full counts, exact intervals, validity reasons and both contrast directions: summary.json, block-level.json and point-level.csv.
