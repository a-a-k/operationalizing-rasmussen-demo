# Static CPU boundary calibration

Received 18/18 fresh-runner trials.

Each label summarizes all three measured windows of one runner. Warmup and invalid-load observations remain in windows.csv.

| Checkout CPU | Usable runners | All safe | All unsafe | Mixed | Final-window p95 range (ms) |
|---|---:|---:|---:|---:|---:|
| 0.45 | 3/3 | 3 | 0 | 0 | 95.1–123.1 |
| 0.30 | 3/3 | 3 | 0 | 0 | 108.9–231.7 |
| 0.22 | 3/3 | 3 | 0 | 0 | 158.9–165.4 |
| 0.16 | 3/3 | 3 | 0 | 0 | 282.0–409.8 |
| 0.12 | 3/3 | 2 | 1 | 0 | 278.8–668.5 |
| 0.08 | 3/3 | 0 | 3 | 0 | 597.7–5001.9 |

No deterministic boundary is inferred from a safe/unsafe pair of finite-window measurements.
The final-window range is descriptive; all earlier windows and error outcomes must also be inspected.
Client outstanding operations do not measure internal server queue lengths.
Failed load delivery is not silently discarded: see trials.csv and windows.csv.

Missing trials: none
