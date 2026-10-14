# Preserved primary warning-confirmation inputs

Twenty gzip packs preserve all 840 measurement windows from the independent
confirmation. They contain native checkout durations and iteration counters,
advertising counters, confirmed-order acknowledgments and corresponding
database commit timestamps, together with the original input-file hashes.
They are not reconstructed from safe/unsafe labels or warning scores.

[The audit summary](summary.json) covers every received pair. Recheck using
the unchanged external-outcome auditor:

```bash
python -B probe7/scripts/audit_primary.py --inputs probe8/results/confirmation-v0.1.0/primary --output-dir artifacts/warning-primary-recheck
```

Use a new output directory. This is a saved-data check, not a runtime execution.
Compressed bytes are included in the repository checksum manifest.
