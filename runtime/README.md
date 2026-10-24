# Shared runtime dependencies

Only stack, sampling and actuator support for the two retained studies is here.

- `base-lock.json`: pinned Demo source, base images, k6 and health inventory.
- `cpu-lock.json`: additional CPU-study images and health timeout.
- `compose.lock.yaml`, `cpu-overlay.yaml`, `otel.env`: executed container settings.
- `runtime_support.py`: readiness, Compose arguments, limit application and
  actual cgroup quota readback.
- `sample_resources.py`: the original read-only native resource sampler.
- `quota_driver.py`: original cgroupfs setup, guarded to an empty disposable
  hosted runner.
- `prometheus.json`: checksum-pinned engine for native arithmetic validation.

Executed designs retain historical runtime labels. `runtime_path` resolves the
two labels to these lock files without changing scientific settings. Unused
fields from earlier locks are omitted. [Relocation provenance](relocation-provenance.json)
records source and extracted-function AST hashes. Sampling, Compose and environment
files are exact LF copies. Local verification never starts containers or changes
the local Docker daemon.
