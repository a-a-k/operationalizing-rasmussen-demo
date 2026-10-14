# Native Prometheus forecast replay

Retrospective practical-method benchmark on already examined confirmation data, not independent confirmation of this newly specified baseline. The disk-capacity alert family motivates the method, not these SLO gauges, minute-scale lookbacks or zero persistence. No guaranteed coordinate superiority or production claim.

Forecast horizon: 86.962 s, two old median cycles. Primary lookback: 300 s.

| Lookback (s) | Method on common decisions | Covered decisions | First violations warned | False signals | Precision | Median lead (s) |
| ---: | --- | ---: | --- | ---: | ---: | ---: |
| 300 | prometheus_predict_linear | 716 | 0/6 | 7 | 0.0 | NA |
| 300 | ilr_history | 716 | 5/6 | 45 | 0.1 | 51.7321142578125 |
| 120 | prometheus_predict_linear | 716 | 1/6 | 7 | 0.125 | 52.078 |
| 120 | ilr_history | 716 | 5/6 | 45 | 0.1 | 51.7321142578125 |
| 600 | prometheus_predict_linear | 716 | 0/6 | 11 | 0.0 | NA |
| 600 | ilr_history | 716 | 5/6 | 45 | 0.1 | 51.7321142578125 |

Unavailable forecasts are not no-alert decisions. Every lookback is retained; no best setting is selected.
ILR counts above use the same covered decisions. Original full ILR counts remain in summary.json.
Service trajectories are short, irregular and affected by controller actions; linear trends are an applicability assumption, not guaranteed.
Native queries use only samples at or before primary availability. Baseline lead is a replay estimate, not a measured live notification.
[Summary](summary.json), [every decision](decisions.csv), [first events](first-events.csv), [native queries/responses](native-responses.jsonl.gz), [native fixture checks](native-checks.json).
