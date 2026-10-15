"""Fixed blocked history comparison using the unchanged static workload."""
from __future__ import annotations

import hashlib
import itertools
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'boundary/scripts'))
from spec import allocation, load
from primary import summarize

DESIGN = ROOT / 'boundary/history/design-v0.1.0.json'


def config():
    return load(DESIGN)


def workload_config():
    cfg = config()
    return {**load(ROOT / cfg['static_design']), 'warmup_seconds': cfg['post_start_seconds'],
            'window_seconds': cfg['window_seconds'], 'measurement_windows': cfg['post_windows']}


def matrix():
    cfg = config()
    output = []
    for quota in cfg['target_checkout_cpu']:
        orders = sorted(itertools.permutations(cfg['paths']), key=lambda p: hashlib.sha256(
            f'{cfg["order_salt"]}|{quota:.2f}|{"|".join(p)}'.encode()).hexdigest())
        if len(orders) != cfg['repetitions_per_target']:
            raise ValueError('Every permutation must occur exactly once per target')
        for rep, order in enumerate(orders, 1):
            output.append({'block_id': f'endpoint-{round(quota*1000):03d}-r{rep}',
                           'target_quota': quota, 'repetition': rep, 'order': list(order)})
    return output


def initial_allocation(path, target):
    initial = config()['paths'][path]
    return allocation(target if initial is None else initial)


def updates(initial, final):
    # Lower the donor first. Control also executes two explicit no-op updates.
    return sorted(['checkout', 'ad'], key=lambda n: (final['cpu'][n] - initial['cpu'][n], n))


def origins(events):
    values = {name: {r['origin'] for r in events if r['stream'] == name}
              for name in ['checkout', 'advertising']}
    if any(len(v) != 1 for v in values.values()):
        raise ValueError('Missing or inconsistent stream origin')
    values = {k: next(iter(v)) for k, v in values.items()}
    if abs(values['checkout'] - values['advertising']) > 1000:
        raise ValueError('Scenario starts differ by more than one second')
    return values


def score(events, drops):
    cfg, load_cfg = config(), workload_config()
    origin = origins(events)['checkout']
    intervals = [(i, cfg['window_seconds'], False) for i in range(0, cfg['transition_seconds'], cfg['window_seconds'])]
    intervals += [(cfg['transition_seconds'], cfg['post_start_seconds'] - cfg['transition_seconds'], False)]
    intervals += [(cfg['post_start_seconds'] + i*cfg['window_seconds'], cfg['window_seconds'], True)
                  for i in range(cfg['post_windows'])]
    output = []
    for offset, duration, measured in intervals:
        # Use common wall-clock cohorts for both streams, retaining prior outstanding work.
        shifted = [{**r, 'origin': origin + 1000*offset} for r in events]
        rows = summarize(shifted, drops, {**load_cfg, 'warmup_seconds': 0,
                         'window_seconds': duration, 'measurement_windows': 1})
        for row in rows:
            row.update(offset_seconds=offset, measured=measured, duration_seconds=duration,
                       since_planned_transition_seconds=offset - cfg['transition_seconds'])
            finishes = [r for r in events if r['stream'] == row['stream'] and r['kind'] == 'finish']
            starts = {r['id']: r for r in events if r['stream'] == row['stream'] and r['kind'] == 'start'}
            cohort = [r for r in finishes if row['window_start_ms'] <= starts[r['id']]['t'] < row['window_end_ms']]
            row['status_zero_finishes'] = sum(r.get('status') == 0 for r in cohort)
            row['near_http_deadline_finishes'] = sum(r['latency_ms'] is not None and
                r['latency_ms'] >= load_cfg['http_timeout_seconds']*1000 - 10 for r in cohort) if row['stream'] == 'checkout' else None
        output.extend(rows)
    return output


def contrast(left, right, block, names):
    delta = left['p95_ms'] - right['p95_ms'] if left['p95_ms'] is not None and right['p95_ms'] is not None else None
    return {**block, 'contrast': names, 'offset_seconds': left['offset_seconds'],
            'since_transition_seconds': left['since_planned_transition_seconds'],
            'p95_left_ms': left['p95_ms'], 'p95_right_ms': right['p95_ms'], 'p95_difference_ms': delta,
            'within_50_ms': abs(delta) <= config()['meaningful_p95_difference_ms'] if delta is not None else None,
            'error_left': left['error_fraction'], 'error_right': right['error_fraction'],
            'safe_left': left['slo_safe'], 'safe_right': right['slo_safe'],
            'same_slo_label': left['slo_safe'] == right['slo_safe'],
            'outstanding_left': left['client_outstanding_end'], 'outstanding_right': right['client_outstanding_end']}
