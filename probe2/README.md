# Probe 2: joint allocation context

This follow-up holds a critical service's local quota at 0.19 CPU while changing
whether one service or all three critical services are reduced. It tests whether
one local quota represents the rest of a closed allocation.

The primary within-block witness requires all three singleton conditions to be
safe and the joint condition to be unsafe. It occurred in 8/28 valid blocks.
Across all attempted blocks, every valid singleton point was safe and 9/32 joint
points were unsafe.

- [Full interpretation](../RESULTS.md#probe-2-local-quota-versus-joint-context)
- [Fixed follow-up design](design.json)
- [Pinned runtime](runtime.json)
- [Aggregate and block-level result](results/summary.json)
- [Execution provenance](results/provenance.json)
- [Pilot selection provenance](pilot-provenance.json)
- [Authoritative workflow](../.github/workflows/probe2.yml)

The pilot returned no formally eligible candidate. Its sole observed interaction
window, 0.19 CPU at 40 requests/s, was fixed for this separate follow-up. Pilot
observations are not included in the reported 8/28 or 9/32.

There is no fitted alert threshold and no majority success criterion. The result
is a constructive representational probe, not an estimate of detector accuracy.

Lightweight tests may be run locally:

```bash
python -m unittest discover -s probe2/tests -v
```

The complete Docker/cgroup experiment is restricted to GitHub Actions.
