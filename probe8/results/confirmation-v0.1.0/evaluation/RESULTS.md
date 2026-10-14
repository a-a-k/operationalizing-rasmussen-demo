# Independent passive warning confirmation

Frozen rules; no fitting on these observations.

Received 20/20 fresh runner pairs. Missing: [].

| Method | First violations warned / observed | False warning decisions | Decision precision | Achieved false-warning rate | Median lead to violating window start (s) |
| --- | --- | ---: | --- | --- | --- |
| ilr_history | 5/6 | 45 | 0.1 | 0.06032171581769437 | 51.7321142578125 |
| share_history | 4/6 | 38 | 0.09523809523809523 | 0.05093833780160858 | 51.81549829101563 |
| local_history | 2/6 | 6 | 0.25 | 0.00804289544235925 | 52.08072668457031 |
| service_indicators | 2/6 | 3 | 0.4 | 0.004021447721179625 | 52.08072668457031 |

Decision windows are dependent. Warning precision and event recall are different quantities.
Lead to the start of the first violating window is conservative relative to the measured outcome's availability, not the unknowable instant of a latent failure.
Actual false-warning rates can differ despite a common development budget; greater recall at greater false-alarm burden is not automatically superiority.
[Fixed-threshold operating curves](operating-curves.csv) use only thresholds enumerated during development; no threshold is refitted on confirmation outcomes.
Truncated unknown futures are not negatives. Baseline failures, early stops, failed predictions and missing runners remain visible.
The observer emits every frozen method simultaneously and never changes the guarded allocation policy.
[Summary](summary.json), [every decision](warning-decisions.csv), [every history](history-level.csv), [first-violation events](first-violation-events.csv), [integrity failures](prediction-integrity.csv), [full records](block-level.json).
