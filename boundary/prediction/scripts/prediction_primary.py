"""Retain all outcomes and distinguish censored quantiles from exact timings."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import math

from prediction_spec import base_config
from primary import quantile


def bounded_quantile(values, probability):
    values = sorted(values)
    if not values:
        return None
    rank = (len(values)-1)*probability
    lo, hi = math.floor(rank), math.ceil(rank)
    if math.isinf(values[hi]):
        return math.inf
    return values[lo] + (values[hi]-values[lo])*(rank-lo)


def intervals(plan):
    supplied = sorted(plan['intervals'], key=lambda r: r['offset'])
    result, end, quota = [], 0, plan['quota']
    for item in supplied:
        if item['offset'] < end:
            raise ValueError('Overlapping cohorts')
        if item['offset'] > end:
            result.append({'offset': end, 'seconds': item['offset']-end, 'quota': quota,
                           'measured': False, 'role': 'gap'})
        result.append(item)
        end, quota = item['offset'] + item['seconds'], item['quota']
    if end != plan['total_seconds']:
        raise ValueError('Plan duration mismatch')
    return result


def score(events, drops, plan):
    cfg, output = base_config(), []
    origin_values = {name: {r['origin'] for r in events if r['stream'] == name}
                     for name in ['checkout', 'advertising']}
    if any(len(v) != 1 for v in origin_values.values()):
        raise ValueError('Missing or inconsistent scenario origin')
    origins = {n: next(iter(v)) for n, v in origin_values.items()}
    if abs(origins['checkout'] - origins['advertising']) > 1000:
        raise ValueError('Scenario starts differ by more than one second')
    for name, rate in [('checkout', cfg['checkout_rate']), ('advertising', cfg['advertising_rate'])]:
        starts, finishes = {}, {}
        for event in events:
            if event['stream'] != name:
                continue
            mapping = starts if event['kind'] == 'start' else finishes if event['kind'] == 'finish' else None
            if mapping is None or event['id'] in mapping:
                raise ValueError('Duplicate or invalid event')
            mapping[event['id']] = event
        if set(finishes) - set(starts):
            raise ValueError('Finish without start')
        if any(r['t'] < starts[ident]['t'] for ident, r in finishes.items()):
            raise ValueError('Negative operation time')
        ordered = sorted(starts.values(), key=lambda r: r['t'])
        start_times = [r['t'] for r in ordered]
        finish_times = sorted(r['t'] for r in finishes.values())
        for item in intervals(plan):
            left = origins['checkout'] + 1000*item['offset']
            right = left + 1000*item['seconds']
            cohort = ordered[bisect_left(start_times, left):bisect_left(start_times, right)]
            complete = [finishes[r['id']] for r in cohort if r['id'] in finishes]
            dropped = sum(r['count'] for r in drops if r['stream'] == name and left <= r['t'] < right)
            latency = [r['latency_ms'] for r in complete if r['latency_ms'] is not None]
            if any(not math.isfinite(v) or v < 0 for v in latency):
                raise ValueError('Invalid latency')
            lower, upper = [], []
            for start in cohort:
                finish = finishes.get(start['id'])
                value = finish.get('latency_ms') if finish else None
                lower.append(value if value is not None else 0.0)
                upper.append(math.inf if value is None or finish.get('error_code') == 1050 else value)
            lo, hi = bounded_quantile(lower, .95), bounded_quantile(upper, .95)
            attempts = len(cohort) + dropped
            error = (attempts - sum(r['success'] for r in complete))/attempts if attempts else None
            p95 = quantile(latency, .95)
            delivered = len(cohort)/(rate*item['seconds'])
            outstanding = [bisect_right(start_times, t) - bisect_right(finish_times, t)
                           for t in range(int(left), int(right)+1, 1000)]
            output.append({
                'stream': name, 'quota': item['quota'], 'offset_seconds': item['offset'],
                'duration_seconds': item['seconds'], 'measured': item['measured'], 'role': item['role'],
                'window_start_ms': left, 'window_end_ms': right, 'started': len(cohort),
                'finished': len(complete), 'dropped': dropped, 'unfinished': len(cohort)-len(complete),
                'start_rate': len(cohort)/item['seconds'],
                'completion_rate': (bisect_left(finish_times, right)-bisect_left(finish_times, left))/item['seconds'],
                'load_valid': cfg['minimum_start_fraction'] <= delivered <= cfg['maximum_start_fraction'] and dropped == 0,
                'p95_ms': p95, 'p95_lower_ms': lo, 'p95_censored': hi is None or math.isinf(hi) or not math.isclose(lo, hi, rel_tol=1e-12, abs_tol=1e-9),
                'p95_upper_ms': hi if hi is not None and math.isfinite(hi) else None,
                'timeout_count': sum(r.get('error_code') == 1050 for r in complete),
                'error_fraction': error,
                'slo_safe': (p95 is not None and p95 <= cfg['checkout_p95_limit_ms'] and error is not None and error < cfg['checkout_error_limit']) if name == 'checkout' else None,
                'timely_fraction': sum(r['success'] and r['latency_ms'] <= cfg['advertising_deadline_ms'] for r in complete)/attempts if name == 'advertising' and attempts else None,
                'client_outstanding_start': outstanding[0], 'client_outstanding_end': outstanding[-1],
                'client_outstanding_max': max(outstanding)})
    return output
