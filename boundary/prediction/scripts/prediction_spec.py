from __future__ import annotations

import hashlib
import math
import os
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'boundary/scripts'))
from spec import allocation as static_allocation, load

DESIGN = ROOT / os.environ.get('BOUNDARY_PREDICTION_DESIGN', 'boundary/prediction/design-v0.1.1.json')


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
    quantum = config()['recommended_quota_quantum']
    if not math.isfinite(quota) or not math.isclose(quota/quantum, round(quota/quantum), rel_tol=0, abs_tol=1e-10):
        raise ValueError('Runtime quota is off the executable CPU grid')
    # Compute the receiver as the remainder, never round both limits upward.
    return static_allocation(round(quota, 8))


def ceil_runtime_quota(quota):
    quantum = Decimal(str(config()['recommended_quota_quantum']))
    return float((Decimal(str(quota))/quantum).to_integral_value(rounding=ROUND_CEILING)*quantum)


def preflight_quotas():
    quantum = Decimal(str(config()['recommended_quota_quantum']))
    low = Decimal(str(min(config()['validation_grid'])))
    high = Decimal(str(max(config()['validation_grid'])))
    return [float(quantum*i) for i in range(int(high/quantum), int(low/quantum)-1, -1)]


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
    fine_band = None
    if q is not None and cfg.get('fine_band_half_width_cpu') is not None:
        quantum = Decimal(str(cfg['recommended_quota_quantum']))
        width = Decimal(str(cfg['fine_band_half_width_cpu']))
        left = max(Decimal(str(min(quotas))), Decimal(str(q))-width)
        right = min(Decimal(str(max(quotas))), Decimal(str(q))+width)
        lo = int((left/quantum).to_integral_value(rounding=ROUND_CEILING))
        hi = int(right/quantum)
        quotas.extend(float(i*quantum) for i in range(lo, hi+1))
        fine_band = {'center': q, 'lower': float(lo*quantum), 'upper': float(hi*quantum),
                     'quantum': float(quantum)}
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
    plan = {'kind': 'validation', 'quota': quotas[0], 'quotas': quotas, 'updates': updates,
            'intervals': intervals, 'total_seconds': max(r['offset'] + r['seconds'] for r in intervals)}
    if cfg.get('fine_band_half_width_cpu') is not None:
        plan['fine_band'] = fine_band
    return plan


def load_config(plan):
    # The unchanged executor convention sums these fields to obtain total duration.
    return {**base_config(), 'warmup_seconds': plan['total_seconds'], 'measurement_windows': 0}
