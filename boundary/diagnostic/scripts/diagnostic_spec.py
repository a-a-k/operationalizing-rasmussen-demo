from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'boundary/prediction/scripts'))
from prediction_spec import base_config, load, load_config, runtime_allocation

DESIGN = ROOT / 'boundary/diagnostic/design-v0.1.0.json'


def config():
    return load(DESIGN)


def matrix():
    cfg = config()
    return [{'block_id': f'diagnostic-r{i+1}',
             'order': [cfg['conditions'][j]['id'] for j in order]}
            for i, order in enumerate(cfg['condition_orders'])]


def plan():
    cfg = config()
    total = cfg['warmup_seconds'] + cfg['measurement_windows']*cfg['window_seconds']
    return {'kind': 'static-diagnostic', 'quota': cfg['checkout_cpu'], 'updates': [],
            'total_seconds': total,
            'intervals': [{'offset': t, 'seconds': cfg['window_seconds'],
                           'quota': cfg['checkout_cpu'], 'role': 'diagnostic',
                           'measured': t >= cfg['warmup_seconds']}
                          for t in range(0, total, cfg['window_seconds'])]}


def limits(cpu, period):
    quota = Decimal(str(cpu))*period
    if quota != int(quota) or quota < 1000 or not 1000 <= period <= 1000000:
        raise ValueError('CPU quota/period cannot be represented exactly')
    return int(quota), period


def render(source, condition):
    """Set limits at creation, avoiding incompatible NanoCPUs/update semantics."""
    rendered = copy.deepcopy(source)
    state = runtime_allocation(config()['checkout_cpu'])
    for name, cpu in state['cpu'].items():
        service = rendered['services'][name]
        service.pop('cpus', None)
        resource_limits = service.setdefault('deploy', {}).setdefault('resources', {}).setdefault('limits', {})
        resource_limits.pop('cpus', None)
        resource_limits['memory'] = str(state['memory'][name])
        period = condition['period_us'] if name == 'checkout' else config()['other_period_us']
        quota, period = limits(cpu, period)
        service.update(cpu_quota=quota, cpu_period=period,
                       mem_limit=str(state['memory'][name]), memswap_limit=str(state['memory'][name]))
    return rendered


if __name__ == '__main__':
    print(json.dumps({'include': matrix()}))
