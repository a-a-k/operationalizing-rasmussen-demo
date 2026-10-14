# Matched service-indicator control

This is a retrospective aggregation of predictions that were produced online during Series 9 by the model frozen before that campaign. No model, feature, neighbor count or threshold was fitted after Series 9.

All three observers use the same labeled library, five-nearest-pair mechanism, service-headroom context, two-cycle target and pre-frozen threshold-selection procedure. `service_indicators` sees only current service headrooms and their last changes; the other observers additionally see the complete CPU/RAM allocation history in ILR or raw-share coordinates.

| Observer input | First violations warned | False decisions | Histories with false signals | Precision | Median lead (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| ilr_history | 44/104 | 346 | 106 | 0.130653 | 51.635 |
| share_history | 41/104 | 277 | 98 | 0.150307 | 51.634 |
| service_indicators | 6/104 | 33 | 33 | 0.195122 | 51.716 |

The aligned comparison isolates what the recorded allocation history adds to the same learned warning mechanism. It does not by itself establish that ILR is superior to complete raw shares; that remains a representational comparison.

Prometheus `predict_linear` remains a separate practical reference in the original Series 9 result. It is not included in this matched table because it does not use the historical labeled library or the nearest-history rule.

[Machine-readable summary](summary.json), [all aligned decisions](decisions.csv), [event-level outcomes](first-events.csv), and [integrity checks](prediction-integrity.csv).
