# Refined engineering execution

This separate gate used [design 0.1.1](../../design-v0.1.1.json). It is not one
of the eight new descriptive histories.

All 19 windows were recorded. Every one of 4,448 attempt starts had a matching
forwarding-worker receipt. The external client recorded 3,402 responses, matching
the generator's completed iterations; 3,240 were successful. No iterations were
dropped. The final window contained no attempts in either logical group.

Each updated observer produced 38 available group diagnoses, all agreeing with
the event-derived state and applied policy. Four group diagnoses were unavailable
because the planned metadata delay prevented trustworthy reconstruction. Two
had no attempts. These are not safe decisions or computational errors.

The fixed-schema ablation made six incorrect policy decisions and later could
not resolve replacement components. The updated direct and compositional
observers agreed throughout. The native PromQL engine passed all 20 applicable
input fixtures. This establishes engineering readiness, not superiority of CoDA
over an equally updated direct rule.

[Summary](analysis/summary.json), [every diagnosis](analysis/diagnostic-comparison.csv),
[execution windows](analysis/execution-windows.csv), [full geometry](analysis/geometry.json),
[native engine](engine.json), [native verification](promql-validation.json),
[export provenance](provenance.json), [replay inputs](inputs/).

Reproduce from the repository root:

```sh
python -B evolving-state/scripts/analyze.py --inputs evolving-state/results/engineering-v0.1.1/inputs --output artifacts/evolving-engineering-1
```
