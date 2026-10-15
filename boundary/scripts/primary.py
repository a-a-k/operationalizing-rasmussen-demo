"""Primary cohort measurements and client-outstanding diagnostics."""
from __future__ import annotations

from bisect import bisect_right
import datetime as dt
import json
import math
from pathlib import Path


def quantile(values, p):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def parse_events(text):
    rows = []
    for line in text.splitlines():
        if line.startswith('CAL '):
            rows.append(json.loads(line[4:]))
    if not rows:
        raise ValueError('No primary start/finish records')
    return rows


def read_drops(path: Path):
    rows = []
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if row.get('type') == 'Point' and row.get('metric') == 'dropped_iterations':
                data = row['data']
                rows.append({'stream': data['tags']['scenario'], 'count': int(data['value']),
                             't': dt.datetime.fromisoformat(data['time'].replace('Z', '+00:00')).timestamp() * 1000})
    return rows


def summarize(events, drops, cfg):
    output = []
    for name, rate in [('checkout', cfg['checkout_rate']), ('advertising', cfg['advertising_rate'])]:
        rows = [r for r in events if r['stream'] == name]
        starts, finishes = {}, {}
        origins = {r['origin'] for r in rows}
        if len(origins) != 1:
            raise ValueError('Missing or inconsistent scenario origin')
        origin = origins.pop()
        for row in rows:
            target = starts if row['kind'] == 'start' else finishes if row['kind'] == 'finish' else None
            if target is None or row['id'] in target:
                raise ValueError('Invalid or duplicate primary event')
            target[row['id']] = row
        if set(finishes) - set(starts):
            raise ValueError('Finish without a start')
        for ident, row in finishes.items():
            if row['t'] < starts[ident]['t']:
                raise ValueError('Negative operation duration')
        start_times = sorted(r['t'] for r in starts.values())
        finish_times = sorted(r['t'] for r in finishes.values())
        # Fixed warmup remains visible as three diagnostic minutes.
        window = cfg['window_seconds']
        total = cfg['warmup_seconds'] + window * cfg['measurement_windows']
        for offset in range(0, total, window):
            left, right = origin + offset * 1000, origin + (offset + window) * 1000
            cohort = [r for r in starts.values() if left <= r['t'] < right]
            complete = [finishes[r['id']] for r in cohort if r['id'] in finishes]
            dropped = sum(r['count'] for r in drops if r['stream'] == name and left <= r['t'] < right)
            latency = [r['latency_ms'] for r in complete if r['latency_ms'] is not None]
            if any(not math.isfinite(v) or v < 0 for v in latency):
                raise ValueError('Invalid latency observation')
            successes = sum(r['success'] for r in complete)
            attempts = len(cohort) + dropped
            error_fraction = (attempts - successes) / attempts if attempts else None
            p95 = quantile(latency, .95)
            outstanding = [bisect_right(start_times, t) - bisect_right(finish_times, t)
                           for t in range(int(left), int(right) + 1, 1000)]
            actual_completions = sum(left <= r['t'] < right for r in finishes.values())
            delivered = len(cohort) / (rate * window)
            load_valid = cfg['minimum_start_fraction'] <= delivered <= cfg['maximum_start_fraction'] and dropped == 0
            output.append({
                'stream': name, 'offset_seconds': offset, 'measured': offset >= cfg['warmup_seconds'],
                'window_start_ms': left, 'window_end_ms': right,
                'expected_starts': rate * window, 'started': len(cohort), 'finished': len(complete),
                'successful': successes, 'dropped': dropped, 'unfinished': len(cohort) - len(complete),
                'latency_observations': len(latency), 'start_rate': len(cohort) / window,
                'completion_rate': actual_completions / window, 'start_fraction': delivered,
                'load_valid': load_valid, 'p50_ms': quantile(latency, .5), 'p95_ms': p95,
                'p99_ms': quantile(latency, .99), 'error_fraction': error_fraction,
                'latency_unsafe': p95 > cfg['checkout_p95_limit_ms'] if p95 is not None and name == 'checkout' else None,
                'slo_safe': p95 is not None and error_fraction is not None and p95 <= cfg['checkout_p95_limit_ms']
                            and error_fraction < cfg['checkout_error_limit'] if name == 'checkout' else None,
                'timely_fraction': sum(r['success'] and r['latency_ms'] <= cfg['advertising_deadline_ms']
                                       for r in complete) / attempts if attempts and name == 'advertising' else None,
                'client_outstanding_start': outstanding[0], 'client_outstanding_end': outstanding[-1],
                'client_outstanding_max': max(outstanding),
                'client_outstanding_mean': sum(outstanding) / len(outstanding),
            })
    return output
