# Probe 1: directional pair

This probe compares two fixed endpoints from the same three-service reference
allocation. A5 is farther from the reference under both Euclidean and Aitchison
radial distance, while B5 moves farther along a predefined checkout-risk balance.

The primary paired outcome is `Y = 1(A5 safe and B5 unsafe)`. The run produced
221 reversals in 256 valid pairs. A5 was safe in every pair; B5 was unsafe in
221 and safe in 35.

- [Full interpretation](../RESULTS.md#probe-1-direction-versus-radial-magnitude)
- [Fixed design](design.json)
- [Pinned runtime](runtime.json)
- [Aggregate result](results/summary.json)
- [Replicate-level result](results/replicate-level.csv)
- [Execution provenance](results/provenance.json)
- [Authoritative workflow](../.github/workflows/probe1.yml)

The workflow materializes the exact endpoint specification from `design.json`,
randomizes pair order deterministically, admits only trials that pass runtime and
manipulation gates, retries infrastructure-invalid pairs within the fixed bound,
and applies the analysis in `scripts/analyze_lean.py`.

Lightweight tests may be run locally:

```bash
python -m unittest discover -s probe1/tests -v
```

The complete Docker/cgroup experiment is restricted to GitHub Actions.
