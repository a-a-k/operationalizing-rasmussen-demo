"""Prespecified descriptive trajectories and separate requirement boundaries."""
from __future__ import annotations

import math

from prediction_spec import base_config, config
from prediction_model import predict, vector
from prediction_primary import score
from geometry import aitchison


def merge_streams(windows, frozen):
    cfg = base_config()
    groups = {}
    for window in windows:
        groups.setdefault(window['offset_seconds'], {})[window['stream']] = window
    cache = {}
    output = []
    for offset, streams in sorted(groups.items()):
        checkout, ad = streams['checkout'], streams['advertising']
        q = checkout['quota']
        if q not in cache:
            value = predict(frozen['model'], q) if frozen['model']['status'] == 'fitted' else math.inf
            cache[q] = {'predicted_p95_ms': value if math.isfinite(value) else None,
                        'relative_distance_from_start': aitchison(vector(max(config()['validation_grid'])), vector(q))}
        latency = cfg['checkout_p95_limit_ms']-checkout['p95_ms'] if checkout['p95_ms'] is not None else None
        error = cfg['checkout_error_limit']-checkout['error_fraction'] if checkout['error_fraction'] is not None else None
        timely = ad['timely_fraction']-config()['advertising_timely_requirement'] if ad['timely_fraction'] is not None else None
        output.append({'offset_seconds': offset, 'duration_seconds': checkout['duration_seconds'],
            'checkout_cpu': q, 'advertising_cpu': round(.70-q, 8),
            'checkout_p95_ms': checkout['p95_ms'], 'checkout_p95_censored': checkout['p95_censored'],
            'checkout_error_fraction': checkout['error_fraction'], 'advertising_timely_fraction': ad['timely_fraction'],
            'checkout_latency_margin_ms': latency, 'checkout_error_margin': error,
            'advertising_timely_margin': timely,
            'all_three_requirements_met': latency is not None and latency >= 0 and error is not None and error > 0 and timely is not None and timely >= 0,
            'client_outstanding_start': checkout['client_outstanding_start'],
            'client_outstanding_end': checkout['client_outstanding_end'],
            'load_valid': checkout['load_valid'] and ad['load_valid'], **cache[q]})
    return output


def threshold_crossings(frozen, session, calibration_valid):
    cfg = base_config()
    checkout = sorted((r for r in session['windows'] if r['stream'] == 'checkout' and r['measured']),
                      key=lambda r: r['offset_seconds'])
    baselines = [r for r in checkout if r['role'] == 'baseline']
    points = [r for r in checkout if r['role'] == 'validation']
    model = frozen['model']
    rows = []
    for limit in config()['secondary_latency_thresholds_ms']:
        baseline_safe = len(baselines) == 1 and baselines[0]['p95_ms'] is not None and baselines[0]['p95_ms'] <= limit and baselines[0]['error_fraction'] < cfg['checkout_error_limit']
        eligible = calibration_valid and session['comparison_valid'] and baseline_safe and model['status'] == 'fitted'
        last_safe = max(config()['validation_grid']) if baseline_safe else None
        first = None
        if baseline_safe:
            for point in points:
                if point['p95_ms'] is not None and point['p95_ms'] <= limit and point['error_fraction'] < cfg['checkout_error_limit']:
                    last_safe = point['quota']
                else:
                    first = point
                    break
        latency_boundary = None
        if model['status'] == 'fitted' and limit > model['offset_ms']:
            c = model['critical_quota']
            latency_boundary = c + 1000*math.log(20)*c/(cfg['checkout_rate']*(limit-model['offset_ms']))
        permitted = (first['quota'] > model['error_guard_quota'] and predict(model, first['quota']) <= limit) if first and model['status'] == 'fitted' else None
        rows.append({'threshold_ms': limit, 'eligible': eligible, 'baseline_safe': baseline_safe,
            'observed_crossing': first is not None, 'last_safe_quota': last_safe,
            'first_unsafe_quota': first['quota'] if first else None,
            'first_unsafe_offset_seconds': first['offset_seconds'] if first else None,
            'first_unsafe_p95_ms': first['p95_ms'] if first else None,
            'first_unsafe_permitted': permitted, 'predicted_latency_boundary_cpu': latency_boundary,
            'error_guard_quota': model.get('error_guard_quota'),
            'sampled_bracket_width_cpu': last_safe-first['quota'] if first is not None and last_safe is not None else None})
    return rows


def secondary_results(frozen, session, primary, calibration_valid):
    original = session['plan']
    seconds = config()['dynamic_window_seconds']
    intervals, index, quota = [], 0, original['quota']
    for offset in range(0, original['total_seconds'], seconds):
        while index < len(original['updates']) and original['updates'][index]['offset'] <= offset:
            quota = original['updates'][index]['quota']
            index += 1
        intervals.append({'offset': offset, 'seconds': min(seconds, original['total_seconds']-offset),
                          'quota': quota, 'measured': False, 'role': 'descriptive_10s'})
    plan = {**original, 'intervals': intervals}
    detailed = score(primary['events'], primary['drops'], plan)
    dynamic = merge_streams(detailed, frozen)
    for row in dynamic:
        row['baseline_or_later'] = row['offset_seconds'] >= config()['validation_baseline_seconds']
    original_windows = [r for r in session['windows'] if r['measured']]
    return dynamic, merge_streams(original_windows, frozen), threshold_crossings(frozen, session, calibration_valid)
