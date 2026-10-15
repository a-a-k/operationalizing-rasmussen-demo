"""Describe static calibration; do not silently pool correlated windows as trials."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
import statistics

from spec import DESIGN, load, matrix
from primary import summarize


def analyze(inputs, output):
    output.mkdir(parents=True, exist_ok=False)
    received, paths, attempts = {}, {}, []
    windows, trials = [], []
    for path in sorted(inputs.rglob('trial.json')):
        result = load(path)
        ident = result['trial_id']
        if result['config'] != load(DESIGN):
            raise ValueError('Trial uses a different design')
        attempts.append({'trial_id': ident, 'run_attempt': result['run_attempt'],
                         'infrastructure_valid': result['infrastructure_valid'], 'reasons': result['reasons']})
        if ident in received:
            if received[ident]['execution_commit'] != result['execution_commit'] or received[ident]['run_id'] != result['run_id']:
                raise ValueError('Cannot merge different executions')
            if int(result['run_attempt']) == int(received[ident]['run_attempt']):
                raise ValueError('Duplicate trial within one attempt')
            if int(result['run_attempt']) < int(received[ident]['run_attempt']):
                continue
        received[ident], paths[ident] = result, path
    for ident, result in sorted(received.items()):
        path = paths[ident]
        raw = path.parent / 'primary-events.json.gz'
        if result['infrastructure_valid']:
            with gzip.open(raw, 'rt', encoding='utf-8') as stream:
                primary = json.load(stream)
            rescored = summarize(primary['events'], primary['drops'], result['config'])
            saved = [{k: v for k, v in w.items() if k != 'resources'} for w in result['windows']]
            if rescored != saved:
                raise ValueError('Independent primary rescore mismatch')
        for w in result['windows']:
            windows.append({'trial_id': ident, 'quota': result['quota'], 'repetition': result['repetition'],
                            'infrastructure_valid': result['infrastructure_valid'],
                            **{k: v for k, v in w.items() if k != 'resources'}})
        checkout = [w for w in result['windows'] if w['stream'] == 'checkout' and w['measured']]
        ad = [w for w in result['windows'] if w['stream'] == 'advertising' and w['measured']]
        complete = len(checkout) == 3 and len(ad) == 3
        load_valid = complete and all(w['load_valid'] for w in checkout + ad)
        statuses = {w['slo_safe'] for w in checkout}
        label = ('all-safe' if statuses == {True} else 'all-unsafe' if statuses == {False} else 'mixed') if complete else 'incomplete'
        trials.append({'trial_id': ident, 'quota': result['quota'], 'repetition': result['repetition'],
                       'infrastructure_valid': result['infrastructure_valid'], 'load_valid': load_valid,
                       'label': label, 'safe_windows': sum(w['slo_safe'] for w in checkout),
                       'latency_unsafe_windows': sum(w['latency_unsafe'] is True for w in checkout),
                       'p95_first_ms': checkout[0]['p95_ms'] if checkout else None,
                       'p95_last_ms': checkout[-1]['p95_ms'] if checkout else None,
                       'error_fraction_last': checkout[-1]['error_fraction'] if checkout else None,
                       'outstanding_last': checkout[-1]['client_outstanding_end'] if checkout else None,
                       'run_attempt': result['run_attempt'], 'reasons': '; '.join(result['reasons'])})
    expected = {r['trial_id'] for r in matrix()}
    if set(received) - expected:
        raise ValueError('Unexpected trial IDs')
    grouped = []
    for q in load(DESIGN)['checkout_cpu_grid']:
        all_trials = [t for t in trials if t['quota'] == q]
        eligible = [t for t in all_trials if t['infrastructure_valid'] and t['load_valid']]
        values = [t['p95_last_ms'] for t in eligible if t['p95_last_ms'] is not None]
        grouped.append({'quota': q, 'received': len(all_trials), 'eligible': len(eligible),
                        'all_safe': sum(t['label'] == 'all-safe' for t in eligible),
                        'all_unsafe': sum(t['label'] == 'all-unsafe' for t in eligible),
                        'mixed': sum(t['label'] == 'mixed' for t in eligible),
                        'last_p95_min_ms': min(values) if values else None,
                        'last_p95_median_ms': statistics.median(values) if values else None,
                        'last_p95_max_ms': max(values) if values else None})
    for name, rows in [('windows', windows), ('trials', trials), ('quotas', grouped)]:
        with (output / (name + '.csv')).open('w', newline='', encoding='utf-8') as stream:
            if rows:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    summary = {'expected_trials': len(expected), 'received_trials': len(received),
               'missing_trials': sorted(expected - set(received)), 'quotas': grouped, 'attempts': attempts,
               'attempt_policy': 'Latest run attempt per trial ID, irrespective of SLO outcome; all attempt statuses retained.',
               'independent_unit': 'Fresh-runner trial; the three post-warmup windows are repeated observations.',
               'scope': 'Static reproducibility only. No fitted model, dynamic boundary claim, or CoDA comparison.',
               'primary_rescore': 'Every infrastructure-valid trial matches retained start/finish records.'}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    lines = ['# Static CPU boundary calibration', '',
             f'Received {len(received)}/{len(expected)} fresh-runner trials.', '',
             'Each label summarizes all three measured windows of one runner. Warmup and invalid-load observations remain in windows.csv.', '',
             '| Checkout CPU | Usable runners | All safe | All unsafe | Mixed | Final-window p95 range (ms) |',
             '|---|---:|---:|---:|---:|---:|']
    for r in grouped:
        bounds = f'{r["last_p95_min_ms"]:.1f}–{r["last_p95_max_ms"]:.1f}' if r['last_p95_min_ms'] is not None else 'NA'
        lines.append(f'| {r["quota"]:.2f} | {r["eligible"]}/{r["received"]} | {r["all_safe"]} | {r["all_unsafe"]} | {r["mixed"]} | {bounds} |')
    lines += ['', 'No deterministic boundary is inferred from a safe/unsafe pair of finite-window measurements.',
              'The final-window range is descriptive; all earlier windows and error outcomes must also be inspected.',
              'Client outstanding operations do not measure internal server queue lengths.',
              'Failed load delivery is not silently discarded: see trials.csv and windows.csv.',
              '', 'Missing trials: ' + (', '.join(summary['missing_trials']) or 'none')]
    (output / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    analyze(args.inputs, args.output_dir)
