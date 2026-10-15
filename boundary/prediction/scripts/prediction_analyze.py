"""Evaluate frozen predictions; validation data never enter model fitting."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from pathlib import Path

from prediction_spec import calibration_plan, config, load, matrix, validation_plan
from prediction_model import fit, forecast, point_prediction
from prediction_primary import score
from prediction_run import digest
from history_analyze import failure_diagnostics


def equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    return a == b


def evaluate(frozen, session, calibration_valid=True):
    baseline = [w for w in session['windows'] if w['stream'] == 'checkout' and w['measured'] and w['role'] == 'baseline']
    baseline_safe = len(baseline) == 1 and baseline[0]['slo_safe']
    usable = calibration_valid and session['comparison_valid'] and baseline_safe
    recommend = frozen['status'] == 'recommended'
    start = max(config()['validation_grid'])
    points = sorted((w for w in session['windows'] if w['stream'] == 'checkout' and w['measured'] and w['role'] == 'validation'), key=lambda r: r['offset_seconds'])
    previous_safe = start if baseline_safe else None
    first_unsafe = None
    rows = []
    for w in points:
        pred = point_prediction(frozen, w['quota'])
        in_prefix = baseline_safe and first_unsafe is None
        if in_prefix:
            if w['slo_safe']:
                previous_safe = w['quota']
            else:
                first_unsafe = w['quota']
        rows.append({**w, **pred, 'in_first_crossing_prefix': in_prefix,
                     'false_permission_in_prefix': bool(in_prefix and pred['permitted'] and not w['slo_safe']),
                     'p95_error_ms_if_exact': pred['p95_prediction_ms'] - w['p95_ms'] if not w['p95_censored'] and pred['p95_prediction_ms'] is not None and w['p95_ms'] is not None else None})
    recommendation_row = next((r for r in rows if r['quota'] == frozen.get('recommended_quota')), None)
    lower = start-previous_safe if previous_safe is not None else None
    upper = start-first_unsafe if first_unsafe is not None else None
    predicted = frozen.get('predicted_transfer_supremum_cpu')
    summary = {'comparison_valid': usable, 'baseline_checkout_safe': baseline_safe,
               'model_status': frozen['status'], 'primary_eligible': usable and recommend,
               'unsafe_allowed': any(r['false_permission_in_prefix'] for r in rows) if usable and recommend else None,
               'recommended_quota': frozen.get('recommended_quota'),
               'recommended_transfer_cpu': frozen.get('recommended_transfer_cpu'),
               'predicted_transfer_cpu': predicted, 'last_safe_transfer_cpu': lower,
               'first_unsafe_transfer_cpu': upper, 'observed_crossing': upper is not None,
               'no_crossing_grid_censored': baseline_safe and upper is None,
               'overprediction_beyond_observed_bracket_cpu': max(0, predicted-upper) if predicted is not None and upper is not None and usable else None,
               'underprediction_before_observed_bracket_cpu': max(0, lower-predicted) if predicted is not None and upper is not None and usable else None,
               'recommended_point_safe': recommendation_row['slo_safe'] if recommendation_row else None,
               'permitted_transition_violations': sum(w['stream'] == 'checkout' and w['role'] == 'transition' and not w['slo_safe'] and point_prediction(frozen, w['quota'])['permitted'] for w in session['windows'])}
    return summary, rows


def select_blocks(inputs):
    selected, attempts = {}, []
    expected = {r['block_id']: r for r in matrix()}
    for path in sorted(inputs.rglob('block.json')):
        data = load(path)
        ident = data['block_id']
        if data['config'] != config() or ident not in expected or any(data[k] != v for k, v in expected[ident].items()):
            raise ValueError('Unexpected block or design')
        attempts.append({k: data[k] for k in ['block_id', 'run_id', 'run_attempt', 'calibration_infrastructure_valid', 'validation_infrastructure_valid', 'reasons']})
        if ident in selected:
            previous = load(selected[ident])
            if any(previous[k] != data[k] for k in ['run_id', 'execution_commit']):
                raise ValueError('Different campaigns cannot be merged')
            if int(data['run_attempt']) == int(previous['run_attempt']):
                raise ValueError('Duplicate block attempt')
            if int(data['run_attempt']) < int(previous['run_attempt']):
                continue
        selected[ident] = path
    if len({(load(p)['run_id'], load(p)['execution_commit']) for p in selected.values()}) > 1:
        raise ValueError('Mixed campaign provenance')
    return selected, attempts


def rescore(folder, expected_plan, block):
    session = load(folder / 'session.json')
    if session['config'] != config() or session['plan'] != expected_plan or any(session[k] != block[k] for k in ['block_id', 'run_id', 'run_attempt', 'execution_commit']):
        raise ValueError('Session plan or provenance mismatch')
    if session['infrastructure_valid']:
        with gzip.open(folder / 'primary-events.json.gz', 'rt', encoding='utf-8') as stream:
            primary = json.load(stream)
        if score(primary['events'], primary['drops'], session['plan']) != session['windows']:
            raise ValueError('Independent primary rescore differs')
        if session['comparison_valid'] != (not session['quality_reasons']):
            raise ValueError('Comparison quality flag mismatch')
    elif session['comparison_valid']:
        raise ValueError('Infrastructure-invalid session cannot be comparison-valid')
    return session


def analyze(inputs, output):
    output.mkdir(parents=True, exist_ok=False)
    selected, attempts = select_blocks(inputs)
    blocks, points, windows, diagnostics = [], [], [], []
    for ident, path in sorted(selected.items()):
        block, folder = load(path), path.parent
        observations, calibration_valid = [], True
        for quota in block['calibration_order']:
            name = f'calibration-{round(quota*1000):03d}'
            if not (folder / name / 'session.json').exists():
                calibration_valid = False
                continue
            session = rescore(folder / name, calibration_plan(quota), block)
            calibration_valid = calibration_valid and session['comparison_valid']
            observations.extend(w for w in session['windows'] if w['stream'] == 'checkout' and w['measured'])
            windows.extend({'block_id': ident, 'session_id': name, **w} for w in session['windows'])
            diagnostics.append({'block_id': ident, 'session_id': name, 'events': failure_diagnostics(folder / name, session)})
        if not (folder / 'frozen-forecast.json').exists() or not (folder / 'validation/session.json').exists():
            blocks.append({'block_id': ident, 'primary_eligible': False, 'unsafe_allowed': None,
                           'reason': 'missing_frozen_forecast_or_validation'})
            continue
        frozen = load(folder / 'frozen-forecast.json')
        if frozen['config'] != config() or any(frozen[k] != block[k] for k in ['block_id', 'run_id', 'run_attempt', 'execution_commit']):
            raise ValueError('Frozen forecast provenance mismatch')
        if digest(folder / 'frozen-forecast.json') != block['frozen_forecast_sha256']:
            raise ValueError('Frozen forecast hash mismatch')
        for relative, sha in frozen['calibration_hashes'].items():
            if digest(folder / relative) != sha:
                raise ValueError('Calibration input changed after freeze')
        model = fit(observations) if calibration_valid else {'status': 'abstain', 'reason': 'calibration_quality_failure'}
        recalculated = forecast(model)
        for key, value in recalculated.items():
            if not equal(value, frozen[key]):
                raise ValueError('Calibration-only model/forecast replay differs: ' + key)
        if frozen['calibration_observations'] != observations:
            raise ValueError('Frozen calibration observations differ')
        plan = validation_plan(frozen)
        if frozen['plan'] != plan or not equal(frozen['point_predictions'], [point_prediction(frozen, q) for q in plan['quotas']]):
            raise ValueError('Frozen validation plan or predictions differ')
        session = rescore(folder / 'validation', plan, block)
        if session['started_ms'] <= frozen['frozen_ms']:
            raise ValueError('Validation began before model freeze')
        summary, rows = evaluate(frozen, session, calibration_valid)
        blocks.append({'block_id': ident, 'run_attempt': block['run_attempt'], **summary,
                       'latency_boundary_quota': frozen.get('latency_boundary_quota'),
                       'relative_endpoint_distance': frozen.get('relative_endpoint_distance'),
                       'relative_arc_length': frozen.get('relative_arc_length'),
                       'quota_ilr_root_error': abs(frozen['latency_boundary_quota']-frozen['latency_boundary_via_ilr']) if frozen['status'] == 'recommended' else None,
                       'reason': '; '.join(session['reasons'] + session['quality_reasons']) or frozen.get('reason', '')})
        points.extend({'block_id': ident, **r} for r in rows)
        windows.extend({'block_id': ident, 'session_id': 'validation', **w} for w in session['windows'])
        diagnostics.append({'block_id': ident, 'session_id': 'validation', 'events': failure_diagnostics(folder / 'validation', session)})
    for name, rows in [('blocks', blocks), ('points', points), ('windows', windows)]:
        with (output / (name + '.csv')).open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
            writer.writeheader()
            writer.writerows(rows)
    eligible = [r for r in blocks if r['primary_eligible']]
    expected = {r['block_id'] for r in matrix()}
    summary = {'expected_blocks': len(expected), 'received_blocks': len(selected),
               'missing_blocks': sorted(expected-selected.keys()), 'primary_eligible': len(eligible),
               'unsafe_allowed': sum(r['unsafe_allowed'] for r in eligible), 'blocks': blocks, 'attempts': attempts,
               'primary': 'At least one model-permitted unsafe point in the first-crossing prefix of the descending validation.',
               'unit': 'One independently calibrated and validated runner block, not a window or request.',
               'scope': 'Checkout SLO at the declared observation times on a descending path. No global system safety, recovery validity, confidence guarantee, or empirical CoDA accuracy advantage.'}
    for name, data in [('summary', summary), ('diagnostics', diagnostics)]:
        (output / (name + '.json')).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    lines = ['# Frozen boundary prediction check', '',
             f'Received {len(selected)}/{len(expected)} blocks. Primary-eligible: {len(eligible)}. Unsafe allowed transfer: {summary["unsafe_allowed"]}/{len(eligible)}.', '',
             '| Block | Eligible | Unsafe allowed | Recommended transfer CPU | Last safe / first unsafe transfer CPU |',
             '|---|---|---|---|---|']
    for row in blocks:
        lines.append(f'| {row["block_id"]} | {row["primary_eligible"]} | {row.get("unsafe_allowed")} | {row.get("recommended_transfer_cpu")} | {row.get("last_safe_transfer_cpu")} / {row.get("first_unsafe_transfer_cpu")} |')
    lines += ['', 'A sampled bracket is not an exact continuous boundary. No observed crossing is censored, not a certified exact prediction.',
              'Only checkout defines the scope gate. Advertising failures and all restart/OOM diagnostics remain visible.',
              'The primary cohorts start 10 seconds after each update and last 60 seconds; transition/gap outcomes are separately retained, not certified safe.',
              'Timeout quantiles are not exact successful response times. Inspect p95_censored and errors before interpreting prediction errors.',
              'Quota/ILR equality checks implementation of the same model and physical path; it does not improve the model itself.',
              'Abstentions, invalid baselines, technical failures and incomplete blocks must accompany the primary fraction. No binary success threshold is applied.']
    (output / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ['expected_blocks', 'received_blocks', 'primary_eligible', 'unsafe_allowed']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    analyze(args.inputs, args.output_dir)
