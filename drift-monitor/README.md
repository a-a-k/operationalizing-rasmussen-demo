# CPU representation and full-covariance MEWMA

This separate study compares ten orthonormal contrasts of all eleven measured
CPU shares with ten ILR coordinates of the same composition. Both observers
use full covariance, the same temporal weighting, and the same available CPU
measurements. Quotas identify interventions but are not detector inputs.

The [executed base definition](design-v0.1.0.json) gives timing and background
preparation. The [active extension](design-v0.1.1.json) defines 250 planned paired
blocks and reuses the frozen model without refitting. Original design bytes
remain unchanged; historical runtime labels resolve through the shared runtime.

[Results and full replay inputs](results/campaign-v0.1.1/README.md) retain the
original model, all 20 fitting/calibration histories, all 273 attempted test pairs
and first-qualified selection of 250 pairs. Both reported threshold rows can be
reproduced, including the retrospective `1.10h` sensitivity analysis.

```sh
python -m pip install -r requirements.txt
python -B drift-monitor/scripts/replay_evidence.py --output artifacts/cpu-replay
```

Runtime execution is available through the manual [background workflow](../.github/workflows/compositional-mewma.yml)
and [250-pair workflow](../.github/workflows/compositional-mewma-extended.yml).
Read-only native sampling and quota/stack helpers are in [runtime/](../runtime/README.md).
