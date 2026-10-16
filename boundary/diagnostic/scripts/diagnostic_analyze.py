"""Raw-event replay and descriptive within-runner factorial contrasts."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import statistics

from diagnostic_spec import DESIGN, config, limits, load, matrix, plan, runtime_allocation
from diagnostic_run import expected_limits
from prediction_primary import score


def read_lines(path):
    if not path.exists():
        path = Path(str(path)+'.gz')
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def pooled_plan():
    result = plan()
    cfg = config()
    result['intervals'] = [{'offset': 0, 'seconds': cfg['warmup_seconds'], 'quota': result['quota'],
                            'role': 'warmup', 'measured': False},
                           {'offset': cfg['warmup_seconds'],
                            'seconds': cfg['window_seconds']*cfg['measurement_windows'],
                            'quota': result['quota'], 'role': 'pooled-diagnostic', 'measured': True}]
    return result


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def contrast(values):
    """Uncensored session p95 only; never average window quantiles."""
    if any(values.get(key) is None for key in ['long-idle', 'short-idle', 'long-busy', 'short-busy']):
        return {}
    li, si, lb, sb = (values[k] for k in ['long-idle', 'short-idle', 'long-busy', 'short-busy'])
    return {'period_short_minus_long_idle_ms': si-li, 'period_short_minus_long_busy_ms': sb-lb,
            'load_busy_minus_idle_long_ms': lb-li, 'load_busy_minus_idle_short_ms': sb-si,
            'interaction_ms': (sb-lb)-(si-li)}


def session_summary(folder):
    session = load(folder/'session.json')
    condition = session['condition']
    if (session['plan'] != plan() or session['allocation'] != runtime_allocation(config()['checkout_cpu'])
            or condition not in config()['conditions'] or condition['id'] != folder.name):
        raise ValueError('Session does not match the fixed diagnostic design')
    with gzip.open(folder/'primary-events.json.gz', 'rt', encoding='utf-8') as stream:
        primary = json.load(stream)
    windows = score(primary['events'], primary['drops'], plan())
    if windows != session['windows']:
        raise ValueError('Saved/live primary scores differ')
    pooled = score(primary['events'], primary['drops'], pooled_plan())
    checkout = next(w for w in pooled if w['measured'] and w['stream'] == 'checkout')
    ad = next(w for w in pooled if w['measured'] and w['stream'] == 'advertising')
    left, right = checkout['window_start_ms'], checkout['window_end_ms']
    frames = [f for f in read_lines(folder/'resource-samples.jsonl') if left <= f['timestamp_ms'] < right]
    reasons = list(session['reasons'])
    expected = {name: f'{q} {p}' for name, (q, p) in expected_limits(session['allocation'], condition).items()}
    q, p = limits(config()['background_cpu'], config()['other_period_us'])
    expected[session['background_name']] = f'{q} {p}'
    for frame in frames:
        for name, value in frame['containers'].items():
            if name in expected and value.get('cpu_max') is not None and value['cpu_max'] != expected[name]:
                reasons.append(name+':sampled_cpu_limit_changed')
    for start in range(config()['warmup_seconds'], plan()['total_seconds'], config()['window_seconds']):
        rows = [f for f in frames if session['load_origin_ms']+1000*start <= f['timestamp_ms']
                < session['load_origin_ms']+1000*(start+config()['window_seconds'])]
        for name in ['checkout', session['background_name'], session['generator_name']]:
            if not any(f['containers'].get(name, {}).get('delta') for f in rows):
                reasons.append(name+':missing_window_telemetry')
        if not any(f.get('host_cpu_fractions') for f in rows):
            reasons.append('missing_host_window_telemetry')
    def deltas(name):
        return [f['containers'][name]['delta'] for f in frames if f['containers'].get(name, {}).get('delta')]
    def cpu(name):
        rows = deltas(name)
        return sum(d['usage_usec'] for d in rows)/1e6/sum(d['sample_seconds'] for d in rows) if rows else None
    checkout_deltas = deltas('checkout')
    periods = sum(d.get('nr_periods', 0) for d in checkout_deltas)
    counts = {'oom_events': 0, 'die_events': 0}
    for event in read_lines(folder/'container-events.jsonl'):
        action = event.get('Action', event.get('status'))
        if action in ['oom', 'die']:
            counts[action+'_events'] += 1
    row = {'block_id': session['block_id'], 'condition': condition['id'],
           'period_us': condition['period_us'], 'loaded': condition['loaded'],
           'comparison_valid': session['comparison_valid'] and not reasons,
           'reasons': ';'.join(sorted(set(reasons))),
           **{key: checkout[key] for key in ['p95_ms', 'p95_censored', 'p95_lower_ms', 'p95_upper_ms',
                     'error_fraction', 'slo_safe', 'start_rate', 'dropped', 'timeout_count', 'unfinished']},
           'advertising_timely_fraction': ad['timely_fraction'],
           'checkout_cpu_cores': cpu('checkout'), 'background_cpu_cores': cpu(session['background_name']),
           'generator_cpu_cores': cpu(session['generator_name']), 'catalog_cpu_cores': cpu('product-catalog'),
           'checkout_throttled_period_fraction': sum(d.get('nr_throttled', 0) for d in checkout_deltas)/periods if periods else None,
           'checkout_throttled_ms_per_period': sum(d.get('throttled_usec', 0) for d in checkout_deltas)/1000/periods if periods else None,
           'host_busy_fraction': mean(1-f['host_cpu_fractions']['idle']-f['host_cpu_fractions']['iowait']
                                      for f in frames if f.get('host_cpu_fractions')),
           'host_steal_fraction': mean(f['host_cpu_fractions']['steal'] for f in frames if f.get('host_cpu_fractions')),
           'telemetry_samples': len(frames), **counts}
    return row, [{**w, 'block_id': row['block_id'], 'condition': row['condition']} for w in windows]


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def analyze(inputs, output):
    output.mkdir(parents=True, exist_ok=True)
    selected = {}
    for path in sorted(inputs.rglob('block.json')):
        block = load(path)
        key = block['block_id']
        if key not in {b['block_id'] for b in matrix()}:
            raise ValueError('Unexpected runner block')
        planned = next(b for b in matrix() if b['block_id'] == key)
        if (block['config'] != config() or block['order'] != planned['order']
                or block['design_sha256'] != hashlib.sha256(DESIGN.read_bytes()).hexdigest()
                or (os.getenv('GITHUB_SHA') and block['execution_commit'] != os.environ['GITHUB_SHA'])):
            raise ValueError('Block design or implementation differs')
        if key in selected and block['run_attempt'] == selected[key][0]['run_attempt']:
            raise ValueError('Duplicate block attempt')
        if key not in selected or block['run_attempt'] > selected[key][0]['run_attempt']:
            selected[key] = block, path.parent
    sessions, windows, contrasts, failures = [], [], [], []
    for planned in matrix():
        key = planned['block_id']
        if key not in selected:
            failures.append({'block_id': key, 'error': 'missing_block'})
            continue
        block, folder = selected[key]
        values, block_rows = {}, []
        for name in planned['order']:
            try:
                row, detail = session_summary(folder/name)
                row['run_attempt'] = block['run_attempt']
                sessions.append(row)
                block_rows.append(row)
                windows.extend(detail)
                values[name] = row['p95_ms'] if row['comparison_valid'] and not row['p95_censored'] else None
            except Exception as exc:
                failures.append({'block_id': key, 'condition': name, 'error': str(exc)})
        difference = contrast(values) if block.get('complete') else {}
        contrasts.append({'block_id': key, 'run_attempt': block['run_attempt'],
                          'complete_uncensored_contrast': bool(difference), **difference})
    write_csv(output/'sessions.csv', sessions)
    write_csv(output/'windows.csv', windows)
    write_csv(output/'paired-contrasts.csv', contrasts)
    summary = {'planned_blocks': len(matrix()), 'received_blocks': len(selected),
               'rescored_sessions': len(sessions), 'valid_sessions': sum(r['comparison_valid'] for r in sessions),
               'complete_uncensored_blocks': sum(r['complete_uncensored_contrast'] for r in contrasts),
               'failures': failures, 'contrasts': contrasts}
    (output/'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    lines = ['# CPU context diagnostic results', '',
             f'{len(sessions)}/16 sessions rescored; {summary["valid_sessions"]} valid; '
             f'{summary["complete_uncensored_blocks"]}/4 complete uncensored runner contrasts.', '',
             '| Runner | Condition | p95 ms | Error fraction | Actual background CPU | Valid |',
             '| --- | --- | ---: | ---: | ---: | --- |']
    for r in sessions:
        lines.append(f'| {r["block_id"]} | {r["condition"]} | {r["p95_ms"]} | {r["error_fraction"]} | '
                     f'{r["background_cpu_cores"]} | {r["comparison_valid"]} |')
    lines.extend(['', '## Within-runner p95 contrasts (milliseconds)', '',
                  '| Runner | Short−long, idle | Short−long, busy | Busy−idle, long | Busy−idle, short | Interaction |',
                  '| --- | ---: | ---: | ---: | ---: | ---: |'])
    keys = ['period_short_minus_long_idle_ms', 'period_short_minus_long_busy_ms',
            'load_busy_minus_idle_long_ms', 'load_busy_minus_idle_short_ms', 'interaction_ms']
    for r in contrasts:
        lines.append('| '+r['block_id']+' | '+' | '.join(str(round(r[k], 3)) if k in r else 'NA' for k in keys)+' |')
    lines.extend(['', 'Negative short−long means a lower p95 with the shorter scheduling period. '
                  'Positive busy−idle means a higher p95 under external CPU contention. '
                  'The interaction is the period contrast under contention minus the period contrast at idle.', '',
                  'These are descriptive interventions at one allocation, not a repaired/validated boundary model. '
                  'A null effect does not exclude other forms of contention or other causes. '
                  'Timeout p95 values are censored lower bounds; their numeric contrasts are not computed. '
                  'OOM/restarts are retained diagnostics, never SLO overrides. '
                  'Individual windows are repeated observations, not independent runner replications.', '',
                  'See [session measurements](sessions.csv), [all windows](windows.csv), '
                  '[paired contrasts](paired-contrasts.csv) and [completeness details](summary.json).', ''])
    (output/'RESULTS.md').write_text('\n'.join(lines), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.inputs, args.output_dir)
    print(json.dumps(result))
    if result['failures'] or result['valid_sessions'] != 16:
        raise SystemExit(1)
