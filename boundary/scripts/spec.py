from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / 'boundary/design-v0.1.0.json'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def matrix():
    cfg = load(DESIGN)
    return [{'trial_id': f'cpu-{round(q * 1000):03d}-r{r}', 'quota': q, 'repetition': r}
            for r in range(1, cfg['repetitions'] + 1) for q in cfg['checkout_cpu_grid']]


def allocation(quota):
    cfg = load(DESIGN)
    reference = load(ROOT / cfg['reference_design'])
    cpu = dict(zip(reference['parts'], reference['reference_cpu']))
    cpu[cfg['receiver']] = round(cpu[cfg['receiver']] + cpu['checkout'] - quota, 8)
    cpu['checkout'] = quota
    if min(cpu.values()) <= 0 or abs(sum(cpu.values()) - cfg['cpu_budget']) > 1e-9:
        raise ValueError('Invalid closed allocation')
    return {'cpu': cpu, 'memory': dict(zip(reference['parts'], [v * 2**20 for v in reference['reference_memory_mib']]))}
