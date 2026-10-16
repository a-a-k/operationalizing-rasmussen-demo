from __future__ import annotations

import copy
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'boundary/diagnostic/scripts'))
from diagnostic_spec import limits
from diagnostic_run import command, save, stack, start_stack, quota_check
from prediction_spec import base_config, load, load_config, static_allocation
import prediction_model as legacy

DESIGN = ROOT/'boundary/period-prediction/design-v0.1.0.json'


def config():
    return load(DESIGN)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matrix():
    cfg = config()
    result = []
    for index in range(cfg['runners']):
        name = f'period-r{index+1}'
        conditions = [{'period_us': p, 'quota': q, 'id': f'cal-{p}-{round(q*1000):03d}'}
                      for p in cfg['periods_us'] for q in cfg['calibration_quotas']]
        conditions.sort(key=lambda c: hashlib.sha256(f'{cfg["order_salt"]}|{name}|{c["id"]}'.encode()).hexdigest())
        result.append({'block_id': name, 'calibration_order': conditions,
                       'test_order': cfg['periods_us'][::1 if index % 2 == 0 else -1]})
    return result


def allocation(quota):
    quantum = config()['quota_quantum']
    if not math.isfinite(quota) or not math.isclose(quota/quantum, round(quota/quantum), abs_tol=1e-10):
        raise ValueError('Quota is off the executable grid')
    return static_allocation(quota)


def plan(quota, phase):
    cfg = config()
    count = cfg['calibration_windows'] if phase == 'calibration' else cfg['test_windows']
    total = cfg['warmup_seconds']+cfg['window_seconds']*count
    return {'kind': phase, 'quota': quota, 'updates': [], 'total_seconds': total,
            'intervals': [{'offset': t, 'seconds': cfg['window_seconds'], 'quota': quota,
                           'measured': t >= cfg['warmup_seconds'], 'role': phase}
                          for t in range(0, total, cfg['window_seconds'])]}


def pooled_plan(quota):
    result = plan(quota, 'test')
    cfg = config()
    result['intervals'] = [{'offset': 0, 'seconds': cfg['warmup_seconds'], 'quota': quota, 'measured': False, 'role': 'warmup'},
                           {'offset': cfg['warmup_seconds'], 'seconds': cfg['window_seconds']*cfg['test_windows'],
                            'quota': quota, 'measured': True, 'role': 'pooled-test'}]
    return result


def render(source, state, period, limited):
    result = copy.deepcopy(source)
    for name, cpu in state['cpu'].items():
        service = result['services'][name]
        for key in ['cpus', 'cpu_period', 'cpu_quota']:
            service.pop(key, None)
        resource = service.setdefault('deploy', {}).setdefault('resources', {}).setdefault('limits', {})
        resource.pop('cpus', None)
        resource['memory'] = str(state['memory'][name])
        service.update(mem_limit=str(state['memory'][name]), memswap_limit=str(state['memory'][name]))
        quota, actual_period = limits(cpu, period if name == 'checkout' else 100000)
        if limited:
            service.update(cpu_quota=quota, cpu_period=actual_period)
    return result


def fit(observations):
    if legacy.config()['model'] != load(ROOT/config()['model_reference'])['model']:
        raise ValueError('Legacy model settings differ from the fixed reference')
    return legacy.fit(observations)


def prediction(model, quota):
    if model['status'] != 'fitted':
        return None
    value = legacy.predict(model, quota)
    return value if math.isfinite(value) else None


def recommend(model):
    if model['status'] != 'fitted':
        return None
    c, b = model['critical_quota'], model['offset_ms']
    if b >= base_config()['checkout_p95_limit_ms']:
        return None
    boundary = c+1000*math.log(20)*c/(base_config()['checkout_rate']*(base_config()['checkout_p95_limit_ms']-b))
    boundary = max(boundary, model['error_guard_quota'], config()['target_range'][0])
    quantum = Decimal(str(config()['quota_quantum']))
    quota = float((Decimal(str(boundary))/quantum).to_integral_value(rounding=ROUND_CEILING)*quantum)
    while quota < config()['target_range'][1] and not legacy.permitted(model, quota):
        quota = round(quota+float(quantum), 8)
    return quota if quota < config()['target_range'][1] else None


if __name__ == '__main__':
    print(json.dumps({'include': matrix()}))
