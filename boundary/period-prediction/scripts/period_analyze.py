"""Verify frozen models and report matched-period and cross-period errors."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
from pathlib import Path
import statistics

from period_spec import (DESIGN, allocation, config, digest, fit, load, matrix, plan,
                         pooled_plan, prediction, recommend, legacy)
from prediction_primary import score
from diagnostic_run import expected_limits
from diagnostic_analyze import read_lines


def prediction_error(predicted, measured):
    result = {'predicted_p95_ms': predicted, 'signed_error_ms': None, 'absolute_error_ms': None,
              'absolute_log_error': None, 'error_lower_bound_ms': None}
    if predicted is None:
        return result
    if measured['p95_lower_ms'] is not None:
        result['error_lower_bound_ms'] = measured['p95_lower_ms']-predicted
    if not measured['p95_censored'] and measured['p95_ms'] is not None:
        error = measured['p95_ms']-predicted
        result.update(signed_error_ms=error, absolute_error_ms=abs(error),
                      absolute_log_error=abs(math.log(measured['p95_ms']/predicted)))
    return result


def paired_summary(rows, predictions):
    long, short = rows['100000'], rows['20000']
    a, b = prediction_error(predictions['100000'], long), prediction_error(predictions['20000'], short)
    exact = not long['p95_censored'] and not short['p95_censored'] and long['p95_ms'] is not None and short['p95_ms'] is not None
    observed_shift = long['p95_ms']-short['p95_ms'] if exact else None
    predicted_shift = predictions['100000']-predictions['20000'] if all(v is not None for v in predictions.values()) else None
    return {'long_p95_ms': long['p95_ms'], 'short_p95_ms': short['p95_ms'],
            'long_matched_prediction_ms': predictions['100000'], 'short_matched_prediction_ms': predictions['20000'],
            'long_matched_error_ms': a['signed_error_ms'], 'short_matched_error_ms': b['signed_error_ms'],
            'observed_long_minus_short_ms': observed_shift, 'predicted_long_minus_short_ms': predicted_shift,
            'matched_error_difference_ms': observed_shift-predicted_shift if observed_shift is not None and predicted_shift is not None else None}


def replay(folder, phase, quota, period):
    session = load(folder/'session.json')
    expected_plan = plan(quota, phase)
    if (session['plan'] != expected_plan or session['period_us'] != period
            or session['quota'] != quota or session['allocation'] != allocation(quota)
            or (os.getenv('GITHUB_SHA') and session['execution_commit'] != os.environ['GITHUB_SHA'])):
        raise ValueError('Session differs from the fixed design')
    with gzip.open(folder/'primary-events.json.gz', 'rt', encoding='utf-8') as stream:
        primary = json.load(stream)
    windows = score(primary['events'], primary['drops'], expected_plan)
    if windows != session['windows']:
        raise ValueError('Saved/live primary scores differ')
    rows = score(primary['events'], primary['drops'], pooled_plan(quota)) if phase == 'test' else windows
    checkout = next(w for w in rows if w['stream'] == 'checkout' and w['measured'])
    reasons = list(session['reasons'])
    if not all(w['load_valid'] for w in windows):
        reasons.append('independent_load_delivery_mismatch')
    for filename in ['initial-quota-checks.json', 'final-quota-checks.json']:
        if not load(folder/filename)['valid']:
            reasons.append(filename+':limits_mismatch')
    left = session['load_origin_ms']+config()['warmup_seconds']*1000
    right = session['load_origin_ms']+expected_plan['total_seconds']*1000
    frames = [f for f in read_lines(folder/'resource-samples.jsonl') if left <= f['timestamp_ms'] < right]
    expected = {name: f'{q} {p}' for name, (q, p) in
                expected_limits(session['allocation'], {'period_us': period}).items()}
    for frame in frames:
        for name, value in frame['containers'].items():
            if name in expected and value.get('cpu_max') is not None and value['cpu_max'] != expected[name]:
                reasons.append(name+':sampled_cpu_limit_changed')
    measured = [w for w in windows if w['stream'] == 'checkout' and w['measured']]
    for w in measured:
        subset = [f for f in frames if w['window_start_ms'] <= f['timestamp_ms'] < w['window_end_ms']]
        for name in ['checkout', session['generator_name']]:
            if not any(f['containers'].get(name, {}).get('delta') for f in subset):
                reasons.append(name+':missing_window_telemetry')
        if not any(f.get('host_cpu_fractions') for f in subset):
            reasons.append('missing_host_window_telemetry')
    deltas = [f['containers']['checkout']['delta'] for f in frames if f['containers'].get('checkout', {}).get('delta')]
    seconds = sum(d['sample_seconds'] for d in deltas)
    periods = sum(d.get('nr_periods', 0) for d in deltas)
    events = read_lines(folder/'container-events.jsonl')
    row = {**checkout, 'block_id': session['block_id'], 'session_id': session['session_id'],
           'phase': phase, 'period_us': period, 'quota': quota,
           'comparison_valid': session['comparison_valid'] and not reasons,
           'reasons': ';'.join(sorted(set(reasons))), 'telemetry_samples': len(frames),
           'checkout_cpu_cores': sum(d['usage_usec'] for d in deltas)/1e6/seconds if seconds else None,
           'checkout_throttled_seconds_per_second': sum(d.get('throttled_usec', 0) for d in deltas)/1e6/seconds if seconds else None,
           'checkout_throttled_period_fraction': sum(d.get('nr_throttled', 0) for d in deltas)/periods if periods else None,
           'host_steal_fraction': statistics.fmean(f['host_cpu_fractions']['steal'] for f in frames if f.get('host_cpu_fractions')) if any(f.get('host_cpu_fractions') for f in frames) else None,
           'oom_events': sum(e.get('Action', e.get('status')) == 'oom' for e in events)}
    return row, windows, session


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)


def select_blocks(inputs):
    selected = {}
    for path in sorted(inputs.rglob('block.json')):
        block = load(path)
        key = block['block_id']
        planned = next((b for b in matrix() if b['block_id'] == key), None)
        if (planned is None or block['config'] != config() or block['design_sha256'] != digest(DESIGN)
                or any(block[k] != v for k, v in planned.items())
                or (os.getenv('GITHUB_SHA') and block['execution_commit'] != os.environ['GITHUB_SHA'])):
            raise ValueError('Block does not match the design/implementation')
        if key in selected and block['run_attempt'] == selected[key][0]['run_attempt']:
            raise ValueError('Duplicate block attempt')
        if key not in selected or block['run_attempt'] > selected[key][0]['run_attempt']:
            selected[key] = block, path.parent
    return selected


def analyze(inputs, output):
    output.mkdir(parents=True, exist_ok=True)
    selected = select_blocks(inputs)
    sessions, windows, errors, pairs, failures = [], [], [], [], []
    for planned in matrix():
        key = planned['block_id']
        if key not in selected:
            failures.append({'block_id': key, 'error': 'missing_block'})
            continue
        block, folder = selected[key]
        try:
            if digest(folder/'frozen-models.json') != block['frozen_sha256']:
                raise ValueError('Frozen model hash mismatch')
            frozen = load(folder/'frozen-models.json')
            if any(frozen[k] != block[k] for k in ['block_id', 'run_id', 'run_attempt', 'execution_commit', 'config', 'design_sha256']):
                raise ValueError('Frozen/block provenance mismatch')
            observations = {str(p): [] for p in config()['periods_us']}
            quality = dict.fromkeys(observations, True)
            telemetry_valid = True
            for condition in planned['calibration_order']:
                name, p, q = condition['id'], condition['period_us'], condition['quota']
                for filename in ['session.json', 'primary-events.json.gz']:
                    relative = name+'/'+filename
                    if digest(folder/relative) != frozen['calibration_hashes'][relative]:
                        raise ValueError('Frozen calibration hash mismatch')
                row, detail, cached = replay(folder/name, 'calibration', q, p)
                sessions.append({**row, 'run_attempt': block['run_attempt']})
                windows.extend({**w, 'block_id': key, 'session_id': name, 'period_us': p} for w in detail)
                observations[str(p)].extend(w for w in detail if w['stream'] == 'checkout' and w['measured'])
                if max(w['window_end_ms'] for w in detail) >= frozen['frozen_ms']:
                    raise ValueError('Model freeze does not follow calibration')
                quality[str(p)] &= cached['comparison_valid']
                telemetry_valid &= row['comparison_valid']
            models = {p: fit(rows) if quality[p] else {'status': 'abstain', 'reason': 'calibration_quality_failure'}
                      for p, rows in observations.items()}
            if models != frozen['models'] or observations != frozen['calibration_observations']:
                raise ValueError('Independent calibration fit differs from frozen models')
            recommendation = recommend(models['100000'])
            target = recommendation if recommendation is not None else config()['fallback_target_cpu']
            predictions = {p: prediction(m, target) for p, m in models.items()}
            if (target != frozen['target_quota'] or predictions != frozen['predictions']
                    or frozen['test_order'] != planned['test_order']
                    or frozen['target_is_recommendation'] != (recommendation is not None)):
                raise ValueError('Target/order/prediction changed after calibration')
            test_rows = {}
            for p in planned['test_order']:
                name = f'test-{p}'
                row, detail, cached = replay(folder/name, 'test', target, p)
                if cached['load_origin_ms'] <= frozen['frozen_ms']:
                    raise ValueError('Test began before model freeze')
                sessions.append({**row, 'run_attempt': block['run_attempt']})
                windows.extend({**w, 'block_id': key, 'session_id': name, 'period_us': p} for w in detail)
                test_rows[str(p)] = row
                telemetry_valid &= row['comparison_valid']
                for model_period, value in predictions.items():
                    errors.append({'block_id': key, 'run_attempt': block['run_attempt'], 'quota': target,
                                   'model_period_us': int(model_period), 'test_period_us': p,
                                   'model_status': models[model_period]['status'],
                                   'prediction_status': 'finite' if value is not None else 'no_stationary_prediction' if models[model_period]['status'] == 'fitted' else 'abstain',
                                   'model_permits_target': legacy.permitted(models[model_period], target) if models[model_period]['status'] == 'fitted' else None,
                                   'matched_period': int(model_period) == p, 'comparison_valid': row['comparison_valid'],
                                   'measured_p95_ms': row['p95_ms'], 'p95_censored': row['p95_censored'],
                                   'slo_safe': row['slo_safe'], **prediction_error(value, row)})
            pairs.append({'block_id': key, 'run_attempt': block['run_attempt'], 'quota': target,
                          'target_is_recommendation': recommendation is not None,
                          'comparison_valid': bool(telemetry_valid and block['test_complete']),
                          **paired_summary(test_rows, predictions)})
        except Exception as exc:
            failures.append({'block_id': key, 'error': str(exc)})
    write_csv(output/'sessions.csv', sessions)
    write_csv(output/'windows.csv', windows)
    write_csv(output/'prediction-errors.csv', errors)
    write_csv(output/'paired-errors.csv', pairs)
    summary = {'planned_blocks': len(matrix()), 'received_blocks': len(selected),
               'rescored_sessions': len(sessions), 'valid_sessions': sum(s['comparison_valid'] for s in sessions),
               'complete_pairs': sum(p['comparison_valid'] for p in pairs), 'failures': failures, 'pairs': pairs}
    (output/'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    lines = ['# CPU-period matched model prediction', '',
             f'{len(sessions)}/48 sessions rescored; {summary["valid_sessions"]} valid; '
             f'{summary["complete_pairs"]}/4 complete runner pairs.', '',
             '| Runner | CPU | Measured 100 ms | Prediction 100 ms | Error | Measured 20 ms | Prediction 20 ms | Error |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    columns = ['quota', 'long_p95_ms', 'long_matched_prediction_ms', 'long_matched_error_ms',
               'short_p95_ms', 'short_matched_prediction_ms', 'short_matched_error_ms']
    for row in pairs:
        lines.append('| '+row['block_id']+' | '+' | '.join('NA' if row[k] is None else str(round(row[k], 3)) for k in columns)+' |')
    lines.extend(['', 'All latency/error numbers are milliseconds; signed error = measured minus predicted. '
                  'Positive error is optimistic prediction. Each model was calibrated at its own CPU period. '
                  'Both fresh tests use the same physical quota, selected before either test using only '
                  'the 100-ms model (or the predeclared fallback if it abstained).', '',
                  'Compare observed period shift with the shift predicted by the separately fitted models '
                  'in [paired errors](paired-errors.csv). All four model/test combinations, including the '
                  'unchanged 100-ms forecast under the short period, are in [prediction errors](prediction-errors.csv). '
                  'Absolute errors prevent a large switch from underprediction to overprediction from being '
                  'misreported as better accuracy. Censored/undefined predictions have no exact error estimate.', '',
                  'This is a static endpoint check, not validation during a descending adaptation path, '
                  'not a repaired model and not attribution of every earlier residual to throttling. '
                  'No success-frequency threshold or significance claim. Single windows are not independent runners.', '',
                  'See [sessions](sessions.csv), [all windows](windows.csv) and [completeness](summary.json).', ''])
    (output/'RESULTS.md').write_text('\n'.join(lines), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.inputs, args.output_dir)
    print(json.dumps(result))
    if result['failures'] or result['complete_pairs'] != config()['runners']:
        raise SystemExit(1)
