# RAM range: engineering observations

Received 9/9 conditions. Missing: [].

| Condition | Checkout MiB | Valid | SLO safe | p95 ms | Error rate | Kernel cap hit | Post-update OOM events |
| --- | ---: | --- | --- | ---: | ---: | --- | ---: |
| control | 256 | True | True | 91.68085249999989 | 0.0004166666666666667 | False | 0 |
| ram-064 | 64 | True | True | 91.8670097 | 0.0 | False | 0 |
| ram-048 | 48 | True | True | 76.68553424999988 | 0.0 | False | 0 |
| ram-040 | 40 | True | True | 114.57262524999993 | 0.0 | False | 0 |
| ram-036 | 36 | True | True | 117.98772609999996 | 0.0 | False | 0 |
| ram-032 | 32 | True | True | 110.04011019999996 | 0.0 | True | 0 |
| ram-028 | 28 | True | True | 115.62976399999998 | 0.0 | True | 0 |
| ram-024 | 24 | True | False | 114.36377984999996 | 0.017916666666666668 | True | 2 |
| ram-020 | 20 | True | False | 88.40815735 | 0.11875 | True | 7 |

Report all nine conditions, raw memory-cap events, Docker OOM diagnostics, external SLO outcomes and validity. One observation per limit does not establish a reproducible safe threshold, causality, alert accuracy or monotonicity. No fitted model, binary scientific criterion, outcome-based replacement or automatic follow-on campaign.

No joint-resource campaign was launched or selected automatically. OOM is diagnostic and never substitutes for the measured SLO label. Invalid readable measurements and absent conditions remain visible.
