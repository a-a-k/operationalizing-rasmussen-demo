from __future__ import annotations

import hashlib
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'boundary/scripts'))
from spec import allocation as static_allocation, load

DESIGN = ROOT / 'boundary/prediction/design-v0.1.0.json'


def allocation(quota):
    # Numerical root finding needs continuous quotas, not rounded CPU limits.
    result = static_allocation(0.30)
    result['cpu']['checkout'] = quota
    result['cpu']['ad'] = 0.70 - quota
    if min(result['cpu'].values()) <= 0 or not math.isclose(
            math.fsum(result['cpu'].values()), 3.4, rel_tol=0, abs_tol=1e-12):
        raise ValueError('Invalid closed allocation')
    return result


def runtime_allocation(quota):
    # Docker's fixed-point CPU option must not receive binary-float tails.
    if not math.isclose(quota, round(quota, 8), rel_tol=0, abs_tol=1e-12):
        raise ValueError('Runtime quota exceeds the declared precision')
    return static_allocation(round(quota, 8))


def config():
    return load(DESIGN)


def base_config():
    return load(ROOT / config()['static_design'])


def matrix():
    cfg = config()
    rows = []
    for rep in range(1, cfg['runners'] + 1):
        name = f'prediction-r{rep}'
        order = sorted(cfg['calibration_quotas'], key=lambda q: hashlib.sha256(
            f'{cfg["order_salt"]}|{name}|{q:.2f}'.encode()).hexdigest())
        rows.append({'block_id': name, 'repetition': rep, 'calibration_order': order})
    return rows


def calibration_plan(quota):
    cfg = config()
    total = cfg['calibration_warmup_seconds'] + cfg['window_seconds']*cfg['calibration_windows']
    return {'kind': 'calibration', 'quota': quota, 'total_seconds': total, 'updates': [],
            'intervals': [{'offset': t, 'seconds': cfg['window_seconds'], 'quota': quota,
                           'measured': t >= cfg['calibration_warmup_seconds'], 'role': 'calibration'}
                          for t in range(0, total, cfg['window_seconds'])]}


def validation_plan(forecast):
    cfg = config()
    quotas = list(cfg['validation_grid'])
    q = forecast.get('recommended_quota')
    if q is not None and min(quotas) <= q <= max(quotas):
        quotas.append(q)
    quotas = sorted(set(quotas), reverse=True)
    intervals = [{'offset': t, 'seconds': cfg['window_seconds'], 'quota': quotas[0],
                  'measured': t == cfg['validation_baseline_seconds'], 'role': 'baseline'}
                 for t in range(0, cfg['validation_baseline_seconds'] + cfg['window_seconds'], cfg['window_seconds'])]
    updates = []
    for index, quota in enumerate(quotas[1:]):
        t = cfg['validation_first_update_seconds'] + index*cfg['validation_step_seconds']
        updates.append({'offset': t, 'quota': quota})
        intervals.append({'offset': t, 'seconds': cfg['post_update_guard_seconds'], 'quota': quota,
                          'measured': False, 'role': 'transition'})
        intervals.append({'offset': t + cfg['post_update_guard_seconds'], 'seconds': cfg['window_seconds'],
                          'quota': quota, 'measured': True, 'role': 'validation'})
    return {'kind': 'validation', 'quota': quotas[0], 'quotas': quotas, 'updates': updates,
            'intervals': intervals, 'total_seconds': max(r['offset'] + r['seconds'] for r in intervals)}


def load_config(plan):
    # The unchanged executor convention sums these fields to obtain total duration.
    return {**base_config(), 'warmup_seconds': plan['total_seconds'], 'measurement_windows': 0}
