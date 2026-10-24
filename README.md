# Runtime drift observation

This replication package contains two studies of runtime state observation.

| Study | Question | Evidence |
|---|---|---|
| [Evolving state](evolving-state/README.md) | Can state, movement and effective policies remain interpretable through supported component changes? | [Eight histories](evolving-state/results/campaign-v0.1.1/README.md) |
| [CPU change detection](drift-monitor/README.md) | How does representation affect full-covariance MEWMA on the same measured CPU histories? | [250 pairs and all attempts](drift-monitor/results/campaign-v0.1.1/README.md) |

The evolving-state study retains real attempt events, versioned correspondence,
policies and passive online diagnoses. Its [directional analysis](evolving-state/results/campaign-v0.1.1/directional-v0.1.0/README.md)
reports orientation and conditional contact with current policies. Updated direct
fractions and a [two-log-odds baseline](evolving-state/results/campaign-v0.1.1/directional-v0.1.0/reduced-v0.1.0/README.md)
receive the same available information.

The CPU study retains the frozen model, all 20 fitting/calibration histories,
273 test attempts and the first-qualified selection of 250 pairs. Both the
original threshold and the explicitly retrospective `1.10h` result can be
recomputed from recorded measurements and online scores.

Read [RESULTS.md](RESULTS.md) for interpretation and [REPRODUCING.md](REPRODUCING.md)
for commands. Runtime workloads run only through the dedicated manual GitHub
Actions workflows. Saved-data replay and unit checks start no workloads.

```sh
python -m pip install -r requirements.txt
python -B scripts/verify_archive.py
```

Verification checks hashes, links, result reconstruction, baselines, and the
[shared runtime](runtime/README.md). Optional plotting uses
`evolving-state/plot-requirements.txt`.

The [MIT license](LICENSE) covers this package. Upstream components retain
their own licenses.
