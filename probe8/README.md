# Passive short-horizon warnings

Separate rule development and independent runtime confirmation. Nothing is
pooled with previous campaigns. The existing resource-allocation controller,
budgets, images and three external requirements remain unchanged.

## Target and available information

At a currently valid, safe evaluation window, warn about any requirement
violation in either of the next two cycles under the unchanged guarded policy.
The horizon was fixed before development-score calculation; it represents two
upcoming allocation decisions, not a known statistical null. Signals at cycles
19 and 20 are not evaluated because the planned two-cycle future is unavailable.
Other truncated unknown futures are never coded as safe negatives.

Every method receives current service headrooms and their most recent changes.
Allocation methods additionally receive the entire observed prefix, including
its initial state. No future confirmation outcome enters prediction.

| Method | Allocation representation and history geometry |
| --- | --- |
| ilr_history | Full CPU/RAM ILR prefix, Aitchison geometry within each resource |
| share_history | All CPU/RAM shares at the same prefix endpoints, Euclidean geometry |
| local_history | The three selected orthonormal log-ratio coordinates |
| service_indicators | Same current headroom/change features, no allocation prefix |

Full shares and ILR receive identical complete endpoint information, not
delta-only features that discard different initial states. One isotropic
training RMS scale per representation/resource retains the respective geometry;
there is no per-coordinate standardization that would destroy ILR isometry.
Only CPU moves within these histories; RAM remains an initial context.

## Concrete rule and threshold development

Match workload and epoch. Within each old runner pair find the nearest eligible
prefix, average its tied labels, then average across the nearest five runner
pairs, including ties at the fifth distance. This neighbor frequency is a
score, not a calibrated probability. All methods use the same candidate pool,
tie rule and current service features.

For development, exclude the entire query runner pair from library and scale
fitting. Select a threshold maximizing positive-window recall subject to no
more than 5% false warnings on negative development decisions; ties prefer
fewer false decisions, then higher threshold. The engineering operating point
is one false decision per twenty non-event opportunities, not a scientific
success criterion. Every development threshold is retained, not only the chosen
point. Dependence among windows and subsequent threshold selection mean these
counts are development information, not independent performance.

Development used 24 archived pairs, 889 eligible known targets, 12 positive:

| Method | Frozen threshold | True warning decisions | False warning decisions |
| --- | ---: | ---: | ---: |
| Full ILR history | .2 | 5/12 | 43/877 |
| Full share history | .2 | 5/12 | 36/877 |
| Selected local history | .4 | 3/12 | 8/877 |
| Service indicators | .4 | 2/12 | 4/877 |

These results do not establish ILR superiority. They establish a specific,
nontrivial rule to freeze and test on new histories, with visible alarm burden.
[Frozen model](frozen-model-v0.1.0.json),
[definition](warning-design-v0.1.0.json),
[all development decisions and thresholds](results/development-v0.1.0/README.md).
Development execution 38544485211 used commit
c0eb2adf830afe88081dc7b4b5e1000a79855973 and started no services.

## Independent confirmation

The [runtime definition](runtime-design-v0.1.0.json) fixes twenty new fresh
runner pairs across all six initial-state/workload cells, balanced 10:10 in
policy order. Twelve busy pairs and eight moderate pairs run in one matrix
wave. Each pair hosts adaptive and unchanged-control stacks separately;
both preserve the original twenty-cycle observation budget. There are no
replacement runners or outcome-triggered expansions.

The [observer wrapper](scripts/live_runner.py) reuses the parent runtime without
editing it. Predictions are emitted only after primary data become available,
recorded before the next controller action, and never influence donor selection,
resource limits, rollback or restoration. Prediction overhead and availability
timestamps are preserved. A failed observer does not erase the measured outcome,
but is explicitly recorded and makes its job fail after preserving the history.

Primary comparison: first-violation histories warned in the chosen horizon
before the first violating window begins, missed events, false warning
decisions, precision, achieved false-warning rate and measured lead intervals.
Current unsafe windows are not called early warnings. Lead to the violating
window's start is conservative with respect to outcome availability; the true
latent instant is not inferred. Unknown future labels, incomplete histories,
failed baselines and missing runners remain visible.

All predictions are replayed from the frozen old-data model for integrity.
External outcomes are independently rescored from native primary inputs before
evaluation. The primary operating points are not refitted. A secondary
descriptive curve evaluates only thresholds already enumerated during
development, and is not a new selected live detector. Different achieved false
warning rates require care: more detections with more false signals are not
automatically superiority.

No confirmation results are present yet. A successful warning rule would
support its utility in these constructed guarded conditions, not universal
superiority of CoDA over every predictor on the same invertible state.

## Execution

- [Development workflow](../.github/workflows/warning-development.yml): saved
  data only. Its committed frozen output is the confirmation input.
- [Confirmation workflow](../.github/workflows/warning-confirmation.yml):
  explicit manual dispatch with the exact expected_sha; all runtime work in Actions.

Local lightweight checks start no services:

```bash
python -B -m unittest discover -s probe8/tests -v
```

Do not rerun development or alter thresholds after seeing confirmation outcomes.
