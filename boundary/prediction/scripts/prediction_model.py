"""Fixed queue-inspired model, fitted only to this runner's calibration."""
from __future__ import annotations

import math
import sys

from prediction_spec import ROOT, allocation, base_config, config

sys.path.insert(0, str(ROOT / 'geometry/scripts'))
from geometry import aitchison, ilr, inverse_ilr


def predict(model, quota):
    c = model['critical_quota']
    return (model['offset_ms'] + 1000*math.log(20)*c/(base_config()['checkout_rate']*(quota-c))) if quota > c else math.inf


def fit(observations):
    exact = [r for r in observations if not r['p95_censored'] and r['p95_lower_ms'] is not None]
    cfg = config()['model']
    if len({r['quota'] for r in exact}) < cfg['minimum_exact_quota_levels']:
        return {'status': 'abstain', 'reason': 'fewer_than_three_exact_quota_levels'}
    if any(r['p95_lower_ms'] is None or r['p95_lower_ms'] <= 0 for r in observations):
        return {'status': 'abstain', 'reason': 'missing_or_nonpositive_quantile_bound'}
    step = cfg['critical_quota_grid_step']
    top_c = math.ceil(min(r['quota'] for r in exact)/step) - 1
    top_b = math.floor(min(r['p95_lower_ms'] for r in exact)/cfg['offset_grid_step_ms'])
    best = None
    targets = [math.log(r['p95_lower_ms']) for r in observations]
    for i in range(1, top_c + 1):
        c = i*step
        terms = [1000*math.log(20)*c/(base_config()['checkout_rate']*(r['quota']-c))
                 if r['quota'] > c else math.inf for r in observations]
        for j in range(top_b + 1):
            b = j*cfg['offset_grid_step_ms']
            loss = 0.0
            for r, target, term in zip(observations, targets, terms):
                residual = math.log(b + term) - target
                if r['p95_censored']:
                    residual = min(0.0, residual)
                loss += residual*residual
            candidate = (loss, c, b)
            if best is None or candidate < best:
                best = candidate
    if best is None or not math.isfinite(best[0]):
        return {'status': 'abstain', 'reason': 'no_finite_fit'}
    error_floor = max((r['quota'] for r in observations if r['error_fraction'] >= base_config()['checkout_error_limit']), default=0.0)
    return {'status': 'fitted', 'critical_quota': best[1], 'offset_ms': best[2],
            'effective_demand_cpu_seconds': best[1]/base_config()['checkout_rate'],
            'training_log_loss': best[0], 'observations': len(observations),
            'censored_observations': sum(r['p95_censored'] for r in observations),
            'error_guard_quota': error_floor,
            'parameter_grid_edge': best[1] == step or best[1] == top_c*step or best[2] == 0 or best[2] == top_b*cfg['offset_grid_step_ms']}


def permitted(model, quota):
    return model['status'] == 'fitted' and quota > model['error_guard_quota'] and predict(model, quota) <= base_config()['checkout_p95_limit_ms']


def helmert_basis(dimension):
    return tuple(tuple(1/math.sqrt(k*(k+1)) if i < k else -k/math.sqrt(k*(k+1)) if i == k else 0.0
                       for i in range(dimension)) for k in range(1, dimension))


def vector(quota):
    return tuple(allocation(quota)['cpu'].values())


def ilr_quota(quota):
    parts = list(allocation(quota)['cpu'])
    values = vector(quota)
    recovered = inverse_ilr(ilr(values, helmert_basis(len(values))), helmert_basis(len(values)))
    return math.fsum(values)*recovered[parts.index('checkout')]


def arc_length(q0, q1, intervals=256):
    # Additive exchange is generally a curve, not a straight line in ILR space.
    d = len(vector(q0))
    total = allocation(q0)['cpu']['checkout'] + allocation(q0)['cpu']['ad']
    def speed(q):
        donor, receiver = -1/q, 1/(total-q)
        return math.sqrt(donor*donor + receiver*receiver - (donor+receiver)**2/d)
    left, right = sorted([q0, q1])
    h = (right-left)/intervals
    return h/3*(speed(left) + speed(right) + math.fsum((4 if i % 2 else 2)*speed(left+i*h) for i in range(1, intervals)))


def forecast(model):
    grid = config()['validation_grid']
    start, end = max(grid), min(grid)
    result = {'model': model, 'recommended_quota': None, 'status': 'abstain'}
    if model['status'] != 'fitted':
        result['reason'] = model['reason']
        return result
    limit = base_config()['checkout_p95_limit_ms']
    if model['offset_ms'] >= limit or not permitted(model, start):
        result['reason'] = 'model_does_not_permit_validation_start'
        return result
    c = model['critical_quota']
    latency_boundary = c + 1000*math.log(20)*c/(base_config()['checkout_rate']*(limit-model['offset_ms']))
    boundary = max(latency_boundary, model['error_guard_quota'])
    quantum = config()['recommended_quota_quantum']
    recommendation = round(math.ceil(max(boundary, end)/quantum)*quantum, 8)
    while recommendation <= start and not permitted(model, recommendation):
        recommendation = round(recommendation + quantum, 8)
    if recommendation >= start:
        result['reason'] = 'no_positive_in_range_transfer_recommended'
        return result
    # Independently find the latency root through the full ILR/inverse path.
    left, right = c + 1e-10, start
    for _ in range(70):
        mid = (left+right)/2
        if predict(model, ilr_quota(mid)) > limit:
            left = mid
        else:
            right = mid
    root = (left+right)/2
    if abs(root-latency_boundary) > 1e-9:
        raise ValueError('Quota and ILR latency roots disagree')
    result.update(status='recommended', latency_boundary_quota=latency_boundary,
                  guarded_boundary_quota=boundary, latency_boundary_via_ilr=root,
                  boundary_below_tested_grid=boundary < end, recommended_quota=recommendation,
                  predicted_transfer_supremum_cpu=start-boundary, recommended_transfer_cpu=start-recommendation,
                  relative_endpoint_distance=aitchison(vector(start), vector(boundary)),
                  relative_arc_length=arc_length(start, boundary))
    return result


def point_prediction(frozen, quota):
    model = frozen['model']
    if model['status'] != 'fitted':
        return {'quota': quota, 'permitted': False, 'p95_prediction_ms': None, 'prediction_kind': 'abstain'}
    value = predict(model, quota)
    restored = ilr_quota(quota)
    other = predict(model, restored)
    if math.isfinite(value) and abs(value-other) > max(1e-7, abs(value)*1e-9):
        raise ValueError('Quota and ILR predictions disagree')
    boundary = frozen.get('guarded_boundary_quota')
    return {'quota': quota, 'permitted': permitted(model, quota),
            'p95_prediction_ms': value if math.isfinite(value) else None,
            'prediction_kind': 'finite' if math.isfinite(value) else 'no_stationary_prediction',
            'remaining_cpu_to_model_boundary': quota-boundary if boundary is not None else None,
            'relative_distance_to_model_boundary': aitchison(vector(quota), vector(boundary)) if boundary is not None else None,
            'relative_arc_to_model_boundary': arc_length(quota, boundary) if boundary is not None else None,
            'inverse_quota_error': abs(quota-restored)}
