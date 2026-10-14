# Primary-input replay

Twenty-four compressed input packs preserve the measurements needed to rescore
all 988 main evaluation windows. Warmup is outside this evaluation set.

- Checkout: every completed request and operation duration, native counters and
  recorded scenario configuration. Failed responses and timeouts stay in the
  latency population; failed, dropped and unfinished scheduled operations stay
  in the unsuccessful-operation denominator.
- Advertising: native counters and quantile summary, including attempts,
  completions, timely nonempty replies and useful replies completed inside the
  measurement window. Unfinished attempts are not removed from the denominator.
- Accounting: every client-confirmed order ID, its client acknowledgment
  timestamp, and its corresponding PostgreSQL transaction-commit timestamp.
  Missing commits remain null. These are extracted from native acknowledgment
  logs and database snapshots, not from the already assigned SLO labels.
- Recorded outcome fields and original source-file SHA-256 hashes provide a
  comparison target and extraction provenance.

The [audit summary](summary.json) records successful rescoring of 989,760
checkout requests, 989,480 confirmed orders and 52,736,915 advertising attempts.
These requests are dependent observations inside histories, not independent
scientific replications.

```bash
python -B probe7/scripts/audit_primary.py --inputs probe7/results/main-v0.2.0/primary --output-dir artifacts/guarded-primary-replay
```

This verifies counters, durations, fractions, delay quantiles and external
safe/unsafe labels against the recorded fields. It runs no services and uses
only the Python standard library. Changing a recorded outcome or a relevant
primary value fails loudly.

These compact packs are not lossless copies of all native telemetry. They do
not reconstruct complete HTTP metric streams, resource samples, unrelated
database rows or logs. Full native files are separate downloaded execution
artifacts; their hosted 14-day retention is not a permanent archive. The packs
and all scored observations are committed and do not depend on that retention.
Compressed bytes are hashed exactly, without text newline normalization.
