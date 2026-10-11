# Allocation scenarios: threshold comparison

Exploratory, in-sample comparison; no held-out prediction, binary scientific success criterion, or pooling with earlier observations.

Recorded 120/120 points; valid 109. Missing blocks: [].

Fixed memory reserves: checkout 256 MiB (GOMEMLIMIT=192MiB), PostgreSQL 1 GiB. OOM/restart is diagnostic, never an SLO-label override or exclusion. No pooling with the cancelled runtime attempt.

## Fixed load: 40 iterations/s

| Allocation | CPU: checkout / payment / shipping / ad | Balance displacement | Unsafe / valid | Unsafe / recoverable | Failures / OOM | Median p95, valid (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| reference | 0.30 / 0.30 / 0.30 / 0.10 | 0.0000 | 0/5 | 0/5 | 0 / 0 | 111.8 |
| joint_024 | 0.24 / 0.24 / 0.24 / 0.28 | 1.0849 | 0/5 | 0/5 | 0 / 0 | 117.4 |
| joint_019 | 0.19 / 0.19 / 0.19 / 0.43 | 1.6588 | 0/5 | 0/5 | 0 / 0 | 212.5 |
| joint_014 | 0.14 / 0.14 / 0.14 / 0.58 | 2.1824 | 2/5 | 2/5 | 0 / 0 | 451.5 |
| joint_010 | 0.10 / 0.10 / 0.10 / 0.70 | 2.6366 | 5/5 | 5/5 | 0 / 0 | 4237.0 |
| joint_007 | 0.07 / 0.07 / 0.07 / 0.79 | 3.0503 | 5/5 | 5/5 | 1 / 1 | 5001.5 |
| checkout_only_007 | 0.07 / 0.30 / 0.30 / 0.33 | 1.4541 | 5/5 | 5/5 | 0 / 0 | 5001.7 |
| payment_only_007 | 0.30 / 0.07 / 0.30 / 0.33 | 1.4541 | 5/5 | 5/5 | 0 / 0 | 3488.1 |
| shipping_only_007 | 0.30 / 0.30 / 0.07 / 0.33 | 1.4541 | 0/5 | 0/5 | 0 / 0 | 272.6 |
| checkout_skew_007 | 0.07 / 0.17 / 0.18 / 0.58 | 2.2539 | 5/5 | 5/5 | 0 / 0 | 5001.7 |
| payment_skew_007 | 0.17 / 0.07 / 0.18 / 0.58 | 2.2539 | 5/5 | 5/5 | 0 / 0 | 5001.1 |
| shipping_skew_007 | 0.17 / 0.18 / 0.07 / 0.58 | 2.2539 | 1/5 | 1/5 | 0 / 0 | 409.2 |

### valid: 33 unsafe, 27 safe points

Each cell is detected unsafe points / actual false alarms. The budget is a maximum, not an exact number of alarms or a pass criterion.

| Maximum false alarms | R_group | checkout_quota | payment_quota | shipping_quota | minimum_group_quota | group_sum | reduced_count | E | d_A | local_or |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 10/0 | 20/0 | 20/0 | 0/0 | 0/0 | 10/0 | 0/0 | 10/0 | 10/0 | 30/0 |
| 1 | 10/0 | 20/0 | 20/0 | 0/0 | 0/0 | 10/0 | 0/0 | 10/0 | 10/0 | 30/0 |
| 2 | 10/0 | 20/0 | 20/0 | 0/0 | 0/0 | 10/0 | 0/0 | 10/0 | 10/0 | 30/0 |
| 3 | 10/0 | 22/3 | 27/3 | 0/0 | 0/0 | 10/0 | 0/0 | 10/0 | 10/0 | 32/3 |
| 4 | 21/4 | 22/3 | 27/3 | 0/0 | 0/0 | 10/0 | 0/0 | 21/4 | 21/4 | 32/3 |
| 5 | 21/4 | 22/3 | 27/3 | 0/0 | 0/0 | 10/0 | 0/0 | 21/4 | 21/4 | 32/3 |
| 6 | 21/4 | 22/3 | 27/3 | 0/0 | 0/0 | 10/0 | 0/0 | 21/4 | 21/4 | 32/3 |
| 7 | 23/7 | 28/7 | 28/7 | 0/0 | 0/0 | 23/7 | 0/0 | 23/7 | 23/7 | 33/7 |
| 8 | 23/7 | 28/7 | 28/7 | 0/0 | 0/0 | 23/7 | 0/0 | 23/7 | 23/7 | 33/7 |
| 9 | 23/7 | 28/7 | 28/7 | 11/9 | 31/9 | 23/7 | 0/0 | 23/7 | 23/7 | 33/7 |
| 10 | 23/7 | 28/7 | 28/7 | 11/9 | 31/9 | 23/7 | 0/0 | 23/7 | 23/7 | 33/7 |
| 11 | 23/7 | 28/7 | 28/7 | 11/9 | 31/9 | 23/7 | 0/0 | 23/7 | 23/7 | 33/7 |
| 12 | 23/7 | 28/7 | 28/7 | 23/12 | 33/12 | 23/7 | 0/0 | 23/7 | 33/12 | 33/7 |
| 13 | 23/7 | 28/7 | 28/7 | 23/12 | 33/12 | 23/7 | 0/0 | 23/7 | 33/12 | 33/7 |
| 14 | 23/7 | 28/7 | 28/7 | 23/12 | 33/12 | 23/7 | 0/0 | 23/7 | 33/12 | 33/7 |
| 15 | 23/7 | 28/7 | 28/7 | 23/12 | 33/12 | 23/7 | 0/0 | 23/7 | 33/12 | 33/7 |
| 16 | 23/7 | 28/7 | 28/7 | 23/12 | 33/12 | 23/7 | 0/0 | 23/7 | 33/12 | 33/7 |
| 17 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 23/17 | 33/17 | 33/12 | 33/7 |
| 18 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 23/17 | 33/17 | 33/12 | 33/7 |
| 19 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 23/17 | 33/17 | 33/12 | 33/7 |
| 20 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 23/17 | 33/17 | 33/12 | 33/7 |
| 21 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 23/17 | 33/17 | 33/12 | 33/7 |
| 22 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |
| 23 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |
| 24 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |
| 25 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |
| 26 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |
| 27 | 33/17 | 33/27 | 33/27 | 33/27 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |


### all_recoverable: 33 unsafe, 27 safe points

Each cell is detected unsafe points / actual false alarms. The budget is a maximum, not an exact number of alarms or a pass criterion.

| Maximum false alarms | R_group | checkout_quota | payment_quota | shipping_quota | minimum_group_quota | group_sum | reduced_count | E | d_A | local_or |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 10/0 | 20/0 | 20/0 | 0/0 | 0/0 | 10/0 | 0/0 | 10/0 | 10/0 | 30/0 |
| 1 | 10/0 | 20/0 | 20/0 | 0/0 | 0/0 | 10/0 | 0/0 | 10/0 | 10/0 | 30/0 |
| 2 | 10/0 | 20/0 | 20/0 | 0/0 | 0/0 | 10/0 | 0/0 | 10/0 | 10/0 | 30/0 |
| 3 | 10/0 | 22/3 | 27/3 | 0/0 | 0/0 | 10/0 | 0/0 | 10/0 | 10/0 | 32/3 |
| 4 | 21/4 | 22/3 | 27/3 | 0/0 | 0/0 | 10/0 | 0/0 | 21/4 | 21/4 | 32/3 |
| 5 | 21/4 | 22/3 | 27/3 | 0/0 | 0/0 | 10/0 | 0/0 | 21/4 | 21/4 | 32/3 |
| 6 | 21/4 | 22/3 | 27/3 | 0/0 | 0/0 | 10/0 | 0/0 | 21/4 | 21/4 | 32/3 |
| 7 | 23/7 | 28/7 | 28/7 | 0/0 | 0/0 | 23/7 | 0/0 | 23/7 | 23/7 | 33/7 |
| 8 | 23/7 | 28/7 | 28/7 | 0/0 | 0/0 | 23/7 | 0/0 | 23/7 | 23/7 | 33/7 |
| 9 | 23/7 | 28/7 | 28/7 | 11/9 | 31/9 | 23/7 | 0/0 | 23/7 | 23/7 | 33/7 |
| 10 | 23/7 | 28/7 | 28/7 | 11/9 | 31/9 | 23/7 | 0/0 | 23/7 | 23/7 | 33/7 |
| 11 | 23/7 | 28/7 | 28/7 | 11/9 | 31/9 | 23/7 | 0/0 | 23/7 | 23/7 | 33/7 |
| 12 | 23/7 | 28/7 | 28/7 | 23/12 | 33/12 | 23/7 | 0/0 | 23/7 | 33/12 | 33/7 |
| 13 | 23/7 | 28/7 | 28/7 | 23/12 | 33/12 | 23/7 | 0/0 | 23/7 | 33/12 | 33/7 |
| 14 | 23/7 | 28/7 | 28/7 | 23/12 | 33/12 | 23/7 | 0/0 | 23/7 | 33/12 | 33/7 |
| 15 | 23/7 | 28/7 | 28/7 | 23/12 | 33/12 | 23/7 | 0/0 | 23/7 | 33/12 | 33/7 |
| 16 | 23/7 | 28/7 | 28/7 | 23/12 | 33/12 | 23/7 | 0/0 | 23/7 | 33/12 | 33/7 |
| 17 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 23/17 | 33/17 | 33/12 | 33/7 |
| 18 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 23/17 | 33/17 | 33/12 | 33/7 |
| 19 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 23/17 | 33/17 | 33/12 | 33/7 |
| 20 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 23/17 | 33/17 | 33/12 | 33/7 |
| 21 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 23/17 | 33/17 | 33/12 | 33/7 |
| 22 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |
| 23 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |
| 24 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |
| 25 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |
| 26 | 33/17 | 28/7 | 28/7 | 23/12 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |
| 27 | 33/17 | 33/27 | 33/27 | 33/27 | 33/12 | 33/17 | 33/22 | 33/17 | 33/12 | 33/7 |

## Fixed load: 64 iterations/s

| Allocation | CPU: checkout / payment / shipping / ad | Balance displacement | Unsafe / valid | Unsafe / recoverable | Failures / OOM | Median p95, valid (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| reference | 0.30 / 0.30 / 0.30 / 0.10 | 0.0000 | 0/4 | 0/4 | 0 / 0 | 217.0 |
| joint_024 | 0.24 / 0.24 / 0.24 / 0.28 | 1.0849 | 2/5 | 2/5 | 0 / 0 | 360.7 |
| joint_019 | 0.19 / 0.19 / 0.19 / 0.43 | 1.6588 | 4/5 | 4/5 | 0 / 0 | 1412.7 |
| joint_014 | 0.14 / 0.14 / 0.14 / 0.58 | 2.1824 | 4/4 | 4/4 | 1 / 1 | 5002.0 |
| joint_010 | 0.10 / 0.10 / 0.10 / 0.70 | 2.6366 | 3/3 | 3/3 | 2 / 2 | 5002.8 |
| joint_007 | 0.07 / 0.07 / 0.07 / 0.79 | 3.0503 | 4/4 | 4/4 | 4 / 4 | 5002.0 |
| checkout_only_007 | 0.07 / 0.30 / 0.30 / 0.33 | 1.4541 | 4/4 | 4/4 | 0 / 0 | 5002.0 |
| payment_only_007 | 0.30 / 0.07 / 0.30 / 0.33 | 1.4541 | 4/4 | 4/4 | 1 / 1 | 5002.3 |
| shipping_only_007 | 0.30 / 0.30 / 0.07 / 0.33 | 1.4541 | 3/5 | 3/5 | 3 / 3 | 5000.9 |
| checkout_skew_007 | 0.07 / 0.17 / 0.18 / 0.58 | 2.2539 | 4/4 | 4/4 | 0 / 0 | 5002.1 |
| payment_skew_007 | 0.17 / 0.07 / 0.18 / 0.58 | 2.2539 | 3/3 | 3/3 | 2 / 2 | 5001.9 |
| shipping_skew_007 | 0.17 / 0.18 / 0.07 / 0.58 | 2.2539 | 4/4 | 4/4 | 2 / 2 | 2814.5 |

### valid: 39 unsafe, 10 safe points

Each cell is detected unsafe points / actual false alarms. The budget is a maximum, not an exact number of alarms or a pass criterion.

| Maximum false alarms | R_group | checkout_quota | payment_quota | shipping_quota | minimum_group_quota | group_sum | reduced_count | E | d_A | local_or |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 22/0 | 26/0 | 26/0 | 0/0 | 0/0 | 22/0 | 0/0 | 22/0 | 22/0 | 30/0 |
| 1 | 26/1 | 30/1 | 30/1 | 0/0 | 0/0 | 26/1 | 0/0 | 26/1 | 22/0 | 34/1 |
| 2 | 26/1 | 30/1 | 30/1 | 25/2 | 33/2 | 26/1 | 0/0 | 26/1 | 33/2 | 34/1 |
| 3 | 37/3 | 30/1 | 30/1 | 29/3 | 37/3 | 37/3 | 0/0 | 37/3 | 37/3 | 37/3 |
| 4 | 37/3 | 32/4 | 32/4 | 29/3 | 37/3 | 37/3 | 28/4 | 37/3 | 37/3 | 37/3 |
| 5 | 37/3 | 32/4 | 32/4 | 29/3 | 37/3 | 37/3 | 28/4 | 37/3 | 37/3 | 37/3 |
| 6 | 39/6 | 32/4 | 32/4 | 31/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 |
| 7 | 39/6 | 32/4 | 32/4 | 31/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 |
| 8 | 39/6 | 32/4 | 32/4 | 31/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 |
| 9 | 39/6 | 32/4 | 32/4 | 31/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 |
| 10 | 39/6 | 39/10 | 39/10 | 39/10 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 |


### all_recoverable: 39 unsafe, 10 safe points

Each cell is detected unsafe points / actual false alarms. The budget is a maximum, not an exact number of alarms or a pass criterion.

| Maximum false alarms | R_group | checkout_quota | payment_quota | shipping_quota | minimum_group_quota | group_sum | reduced_count | E | d_A | local_or |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 22/0 | 26/0 | 26/0 | 0/0 | 0/0 | 22/0 | 0/0 | 22/0 | 22/0 | 30/0 |
| 1 | 26/1 | 30/1 | 30/1 | 0/0 | 0/0 | 26/1 | 0/0 | 26/1 | 22/0 | 34/1 |
| 2 | 26/1 | 30/1 | 30/1 | 25/2 | 33/2 | 26/1 | 0/0 | 26/1 | 33/2 | 34/1 |
| 3 | 37/3 | 30/1 | 30/1 | 29/3 | 37/3 | 37/3 | 0/0 | 37/3 | 37/3 | 37/3 |
| 4 | 37/3 | 32/4 | 32/4 | 29/3 | 37/3 | 37/3 | 28/4 | 37/3 | 37/3 | 37/3 |
| 5 | 37/3 | 32/4 | 32/4 | 29/3 | 37/3 | 37/3 | 28/4 | 37/3 | 37/3 | 37/3 |
| 6 | 39/6 | 32/4 | 32/4 | 31/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 |
| 7 | 39/6 | 32/4 | 32/4 | 31/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 |
| 8 | 39/6 | 32/4 | 32/4 | 31/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 |
| 9 | 39/6 | 32/4 | 32/4 | 31/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 |
| 10 | 39/6 | 39/10 | 39/10 | 39/10 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 | 39/6 |

## Reading the result

A balance advantage at a budget means fewer missed unsafe points among these observations while staying within the same maximum false-alarm count. Crossing curves mean a trade-off, not a universally better method. The budgets are correlated display coordinates, not statistical votes.

All achievable thresholds are retained, including disabling alarms. Local OR exhausts separate per-service thresholds, so it is a flexible in-sample oracle comparator. No favorable threshold is presented as independently validated performance. Quota thresholds are not alerts on measured CPU utilization or throttling.

Multiple redistribution directions expand the tested state context; the joint panel alone would merely compare monotone reparameterizations. Identical balance values with different SLO outcomes remain evidence against scalar sufficiency and are not discarded.

The reference allocation is a sham intervention, not an expected-safe label. Baseline failures can prevent a test; missing and invalid points remain in the point table. Recoverable technical-invalid outcomes are also compared separately. Results at the two loads are never pooled.

These are independently measured allocations, not a temporally observed adaptive process. They show representation and discrimination on fixed scenarios, not adaptation incentives, advertisement performance, early warning, or general operational reliability.

Full rules, confusion counts and false-alarm-budget envelopes: comparison.json and thresholds.csv. All 120 planned point records, including missing/invalid observations: point-level.csv.
