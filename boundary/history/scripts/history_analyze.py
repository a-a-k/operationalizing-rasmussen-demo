"""Paired, time-aligned contrasts; no learned model or boundary fit."""
from __future__ import annotations

import argparse
import csv
import gzip
import itertools
import json
from pathlib import Path
import statistics

from history_spec import config, contrast, load, matrix, score, workload_config


def read_events(path):
    if path.exists():
        with path.open(encoding='utf-8') as stream:
            return [json.loads(line) for line in stream if line.strip()]
    with gzip.open(str(path) + '.gz', 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def failure_diagnostics(folder, trial):
    failures = []
    if not (folder / 'container-events.jsonl').exists() and not (folder / 'container-events.jsonl.gz').exists():
        if trial['infrastructure_valid']:
            raise ValueError('Failure-event diagnostic is missing from a completed path')
        return failures
    for row in read_events(folder / 'container-events.jsonl'):
        if row.get('Action') not in ('oom', 'die', 'restart', 'kill'):
            continue
        attrs = row.get('Actor', {}).get('Attributes', {})
        failures.append({'action': row['Action'], 'service': attrs.get('name'),
                         'time_ms': row.get('timeNano', row.get('time', 0)*10**9)/1e6,
                         'exit_code': attrs.get('exitCode')})
    origin = min(w['window_start_ms'] for w in trial['windows']) if trial['windows'] else None
    for row in failures:
        row['load_age_seconds'] = (row['time_ms'] - origin)/1000 if origin is not None else None
    return failures


def select_blocks(inputs):
    selected, attempts = {}, []
    expected = {r['block_id']: r for r in matrix()}
    for path in sorted(inputs.rglob('block.json')):
        row = load(path)
        ident = row['block_id']
        if row['config'] != config() or ident not in expected:
            raise ValueError('Unexpected block or design')
        if any(row[k] != v for k, v in expected[ident].items()):
            raise ValueError('Block allocation or order mismatch')
        attempts.append({k: row[k] for k in ['block_id', 'run_id', 'run_attempt', 'infrastructure_valid', 'reasons', 'paths']})
        if ident in selected:
            prior = load(selected[ident])
            if any(prior[k] != row[k] for k in ['run_id', 'execution_commit']):
                raise ValueError('Cannot pool separate campaigns or implementations')
            if int(prior['run_attempt']) == int(row['run_attempt']):
                raise ValueError('Duplicate block in same attempt')
            if int(prior['run_attempt']) > int(row['run_attempt']):
                continue
        selected[ident] = path
    if len({(load(p)['run_id'], load(p)['execution_commit']) for p in selected.values()}) > 1:
        raise ValueError('Mixed campaign provenance')
    return selected, attempts


def analyze(inputs, output):
    output.mkdir(parents=True, exist_ok=False)
    selected, attempts = select_blocks(inputs)
    trials, windows, pairs, diagnostics = [], [], [], []
    for ident, block_path in sorted(selected.items()):
        block = load(block_path)
        by_path = {}
        for name in block['order']:
            path = block_path.parent / name / 'trial.json'
            if not path.exists():
                trials.append({'block_id': ident, 'path': name, 'target_quota': block['target_quota'],
                               'infrastructure_valid': False, 'comparison_valid': False, 'reasons': 'missing path'})
                continue
            trial = load(path)
            if trial['config'] != config() or trial['workload_config'] != workload_config():
                raise ValueError('Path uses different measurement rules')
            if any(trial[k] != block[k] for k in ['block_id', 'target_quota', 'order', 'run_id', 'run_attempt', 'execution_commit']):
                raise ValueError('Path is not from the selected complete block attempt')
            if trial['infrastructure_valid']:
                with gzip.open(path.parent / 'primary-events.json.gz', 'rt', encoding='utf-8') as stream:
                    primary = json.load(stream)
                if score(primary['events'], primary['drops']) != trial['windows']:
                    raise ValueError('Independent primary rescore mismatch')
                if trial['comparison_valid'] != (not trial['quality_reasons']):
                    raise ValueError('Comparison quality flag mismatch')
            failures = failure_diagnostics(path.parent, trial)
            diagnostics.append({'block_id': ident, 'path': name, 'events': failures})
            trials.append({'block_id': ident, 'path': name, 'target_quota': block['target_quota'],
                           'position': trial['position'], 'run_attempt': trial['run_attempt'],
                           'infrastructure_valid': trial['infrastructure_valid'], 'comparison_valid': trial['comparison_valid'],
                           'reasons': '; '.join(trial['reasons'] + trial['quality_reasons']),
                           'load_failure_events': sum(e['load_age_seconds'] is not None and e['load_age_seconds'] >= 0 for e in failures),
                           'transition_end_delay_ms': trial['transition']['updates'][-1]['ended_ms'] - trial['transition']['planned_ms'] if trial['transition'] else None})
            for w in trial['windows']:
                windows.append({'block_id': ident, 'path': name, 'target_quota': block['target_quota'],
                                'comparison_valid': trial['comparison_valid'], **w})
            by_path[name] = trial
        for left, right in [('decrease', 'control'), ('recover', 'control'), ('decrease', 'recover')]:
            if not all(n in by_path for n in [left, right]):
                continue
            a, b = by_path[left], by_path[right]
            left_windows = {w['offset_seconds']: w for w in a['windows'] if w['stream'] == 'checkout' and w['measured']}
            right_windows = {w['offset_seconds']: w for w in b['windows'] if w['stream'] == 'checkout' and w['measured']}
            for offset in sorted(left_windows.keys() & right_windows.keys()):
                pairs.append(contrast(left_windows[offset], right_windows[offset],
                    {'block_id': ident, 'target_quota': block['target_quota'],
                     'repetition': block['repetition'], 'comparison_valid': a['comparison_valid'] and b['comparison_valid']},
                    left + '-' + right))
    groups = []
    for key, rows in itertools.groupby(sorted(pairs, key=lambda r: (r['target_quota'], r['contrast'], r['offset_seconds'])),
                                       key=lambda r: (r['target_quota'], r['contrast'], r['offset_seconds'])):
        all_rows = list(rows)
        eligible = [r for r in all_rows if r['comparison_valid'] and r['p95_difference_ms'] is not None]
        values = [r['p95_difference_ms'] for r in eligible]
        groups.append({'target_quota': key[0], 'contrast': key[1], 'load_age_seconds': key[2],
                       'since_transition_seconds': key[2] - config()['transition_seconds'],
                       'received_pairs': len(all_rows), 'usable_pairs': len(values),
                       'p95_delta_min_ms': min(values) if values else None,
                       'p95_delta_median_ms': statistics.median(values) if values else None,
                       'p95_delta_max_ms': max(values) if values else None,
                       'within_50_ms': sum(r['within_50_ms'] for r in eligible),
                       'same_slo_label': sum(r['same_slo_label'] for r in eligible)})
    for name, rows in [('trials', trials), ('windows', windows), ('pairs', pairs), ('contrasts', groups)]:
        with (output / (name + '.csv')).open('w', newline='', encoding='utf-8') as stream:
            fields = list(dict.fromkeys(k for row in rows for k in row))
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    expected = {r['block_id'] for r in matrix()}
    summary = {'expected_blocks': len(expected), 'received_blocks': len(selected),
               'missing_blocks': sorted(expected - selected.keys()),
               'paths_received': len(trials), 'comparison_valid_paths': sum(t['comparison_valid'] for t in trials),
               'attempts': attempts, 'contrasts': groups,
               'unit': 'One runner block, not an individual window or path.',
               'scope': 'Descriptive paired history contrasts. No equivalence test, stationarity guarantee, performance model, or directed margin estimate.',
               'primary_rescore': 'All infrastructure-valid paths independently rescored.'}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    (output / 'diagnostics.json').write_text(json.dumps(diagnostics, indent=2) + '\n', encoding='utf-8')
    lines = ['# Endpoint history comparison', '',
             f'Received {len(selected)}/{len(expected)} runner blocks; {summary["comparison_valid_paths"]}/{len(trials)} received paths meet controlled-comparison checks.', '',
             'Differences are left minus right. Each row compares distinct runners at one aligned time; rows across time reuse those runners.', '',
             '| Endpoint CPU | Contrast | Seconds after planned transition | Usable pairs | p95 difference min / median / max (ms) | Within 50 ms | Same SLO label |',
             '|---|---|---:|---:|---|---:|---:|']
    for r in groups:
        delta = ' / '.join(f'{r[k]:.1f}' for k in ['p95_delta_min_ms', 'p95_delta_median_ms', 'p95_delta_max_ms']) if r['usable_pairs'] else 'NA'
        lines.append(f'| {r["target_quota"]:.2f} | {r["contrast"]} | {r["since_transition_seconds"]} | {r["usable_pairs"]} | {delta} | {r["within_50_ms"]} | {r["same_slo_label"]} |')
    lines += ['', '50 ms is a predeclared practical resolution, not a statistical equivalence claim. Inspect all paired differences and errors.',
              'Matching SLO labels alone does not establish matching latency or stationarity. Similarity in the final window does not establish a universal settling time.',
              'Timeout-duration observations remain failures and must not be fitted as successful service completion times.',
              'Restart/OOM diagnostics remain visible and never change measured SLO labels.',
              'Missing blocks: ' + (', '.join(summary['missing_blocks']) or 'none')]
    (output / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ['expected_blocks', 'received_blocks', 'comparison_valid_paths', 'missing_blocks']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    analyze(args.inputs, args.output_dir)
