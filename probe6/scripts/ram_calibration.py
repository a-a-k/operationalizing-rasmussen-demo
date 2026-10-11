from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import joint_resources as joint

ROOT = joint.ROOT
VERSION = 'ram-range-calibration-0.1.0'
DESIGN = 'probe6/ram-calibration-design-v0.1.0.json'
RUNTIME = 'probe6/ram-calibration-runtime-v0.1.0.json'
engine = joint.engine
load, write_json = joint.load, joint.write_json


def matrix(design: dict) -> list[dict]:
    points = [{'condition_id': f'ram-{mib:03d}', 'checkout_mib': mib}
              for mib in design['checkout_limits_mib']]
    return [{'condition_id': 'control', 'checkout_mib': 256}, *points]


def target_memory(design: dict, mib: int) -> dict:
    if mib not in [r['checkout_mib'] for r in matrix(design)]:
        raise ValueError('memory ceiling outside the fixed calibration grid')
    checkout = mib * 1024 ** 2
    return {'checkout': checkout, 'ad': design['memory_budget_bytes'] - checkout}


def verify(upstream: Path | None = None, check_runner: bool = False) -> dict:
    design, runtime = load(ROOT / DESIGN), load(ROOT / RUNTIME)
    if design['study_version'] != VERSION or runtime['study_version'] != VERSION:
        raise ValueError('calibration version mismatch')
    if design['checkout_limits_mib'] != [64, 48, 40, 36, 32, 28, 24, 20] or not design['include_unchanged_control']:
        raise ValueError('fixed grid differs')
    if design['replications_per_condition'] != 1 or design['checkout_rate'] != 40:
        raise ValueError('unexpected workload or replication count')
    if design['cpu_reference'] != joint.load(ROOT / joint.DESIGN)['reference']:
        raise ValueError('CPU allocation differs from the prior engineering reference')
    if design['memory_reference_bytes'] != {'checkout': 256 * 1024 ** 2, 'ad': 512 * 1024 ** 2}:
        raise ValueError('memory reference differs')
    if design['memory_budget_bytes'] != sum(design['memory_reference_bytes'].values()):
        raise ValueError('memory budget differs')
    for key in ('parent_runtime', 'parent_runner', 'compose_overlay'):
        if joint.sha256_file(ROOT / runtime[key]) != runtime[key + '_sha256']:
            raise ValueError(f'pinned input differs: {key}')
    return {'valid': True, 'study_version': VERSION, 'conditions': len(matrix(design)),
            'parent_verification': joint.verify(upstream, check_runner),
            'design_sha256': joint.sha256_file(ROOT / DESIGN), 'runtime_sha256': joint.sha256_file(ROOT / RUNTIME)}


def apply_target(q: dict, memory: dict, journal: Path) -> list[dict]:
    errors = []
    with journal.open('a', encoding='utf-8', buffering=1) as stream:
        for name, value in q.items():
            command = ['docker', 'update', '--cpus', f'{value:.9f}']
            if name in memory:
                command.extend(['--memory', str(memory[name]), '--memory-swap', str(memory[name])])
            command.append(name)
            started = engine.utc()
            try:
                done = engine.run(command, check=False)
                record = {'started_at': started, 'ended_at': engine.utc(), 'command': command,
                          'exit_code': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr}
            except Exception as exc:
                record = {'started_at': started, 'ended_at': engine.utc(), 'command': command,
                          'exit_code': None, 'exception': repr(exc)}
            stream.write(json.dumps(record) + '\n')
            if record['exit_code'] != 0: errors.append(record)
    # Finish both sides even if a client command fails. Snapshot verification,
    # not a readable post-update SUT failure, determines manipulation validity.
    return errors


def oom_events(path: Path, intervention: str | None, end: str | None) -> list[dict]:
    if not intervention or not end or not path.exists(): return []
    lower, upper = dt.datetime.fromisoformat(intervention).timestamp(), dt.datetime.fromisoformat(end).timestamp()
    events = []
    for line in path.read_text(encoding='utf-8').splitlines():
        event = json.loads(line)
        stamp = event['timeNano'] / 1e9 if 'timeNano' in event else event['time']
        if event.get('Action') == 'oom' and event.get('Actor', {}).get('Attributes', {}).get('name') == 'checkout' and lower <= stamp <= upper:
            events.append({'time_seconds': stamp, 'container_id': event['Actor']['ID']})
    return events


def point(upstream: Path, parent: dict, inherited: dict, design: dict, runtime: dict, row: dict, folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=False)
    bid = row['condition_id']
    prefix = joint.compose_prefix(upstream, joint.project_name(os.environ['GITHUB_RUN_ID'], bid, 'calibration'))
    generators = [bid + '-checkout-k6', bid + '-ad-k6']
    result = {**row, 'baseline_valid': False, 'valid': False, 'reason_codes': [], 'baseline': None,
              'test': None, 'intervention_at': None, 'measurement_ended_at': None, 'diagnostic_errors': []}
    event_file = (folder / 'docker-events.jsonl').open('w', encoding='utf-8')
    event_error = (folder / 'docker-events.stderr.log').open('w', encoding='utf-8')
    events = subprocess.Popen(['docker', 'events', '--since', engine.utc(), '--filter', 'type=container',
                              '--filter', f'label=com.docker.compose.project={prefix[3]}', '--format', '{{json .}}'],
                             stdout=event_file, stderr=event_error)
    sampler = None
    samples = folder / 'resource-samples.jsonl'
    q, reference = design['cpu_reference'], design['memory_reference_bytes']
    memory = target_memory(design, row['checkout_mib'])
    result.update(cpu=q, memory_bytes=memory)
    phase_design = {**joint.load(ROOT / joint.DESIGN), **design, 'reference': q}
    try:
        engine.run([*prefix, 'up', '--detach', '--no-build', '--pull', 'never'])
        engine.wait_for_stack(parent, runtime['health_check_timeout_seconds'])
        initial = engine.inspect_all(parent['required_running_containers'])
        write_json(folder / 'initial-container-inspect.json', initial)
        write_json(folder / 'observer-config.json', {
            'containers': [*q, 'astronomy-db', 'frontend', 'cart', 'product-catalog', *generators],
            'output': str(samples.resolve()), 'stop_file': str((folder / '.observer-stop').resolve()),
            'interval_seconds': 2, 'refresh_seconds': 6})
        sampler = subprocess.Popen(['sudo', '--non-interactive', sys.executable,
                                    str(ROOT / 'probe3/scripts/observe.py'), '--config', str(folder / 'observer-config.json')])
        result['baseline_update_errors'] = apply_target(q, reference, folder / 'updates.jsonl')
        start = joint.limit_check(q, reference)
        args = (upstream, parent, inherited, phase_design, runtime, bid, 'calibration')
        joint.phase(*args, 'warmup', design['warmup_seconds'], folder / 'warmup', *generators, samples)
        baseline = joint.phase(*args, 'baseline', design['baseline_seconds'], folder / 'baseline', *generators, samples)
        before = engine.inspect_all(parent['required_running_containers'])
        end = joint.limit_check(q, reference)
        pre_failures = engine.failures(initial, before, parent['system_under_test_containers'])
        reasons = result['reason_codes']
        if not baseline['valid']: reasons.extend(baseline['reason_codes'])
        if not baseline['checkout']['safe']: reasons.append('baseline_slo_unsafe')
        if not start['valid'] or not end['valid']: reasons.append('baseline_limits_invalid')
        if pre_failures: reasons.append('pre_intervention_system_failure')
        if baseline.get('resource_samples_missing'): reasons.append('baseline_resource_samples_missing')
        if baseline['advertising']['goodput_per_second'] <= 0: reasons.append('baseline_advertising_output_missing')
        if (baseline['advertising'].get('throttled_period_fraction_mean') or 0) <= 0:
            reasons.append('baseline_advertising_cpu_pressure_missing')
        result.update(baseline=baseline, baseline_limits_start=start, baseline_limits_end=end,
                      pre_intervention_failures=pre_failures, baseline_valid=not reasons)
        if reasons: return result
        result['intervention_at'] = engine.utc()
        result['intervention_update_errors'] = apply_target(q, memory, folder / 'updates.jsonl')
        limits_start = joint.limit_check(q, memory)
        joint.phase(*args, 'stabilization', design['stabilization_seconds'], folder / 'stabilization', *generators, samples)
        measured = joint.phase(*args, 'test', design['measurement_seconds'], folder / 'test', *generators, samples)
        limits_end = joint.limit_check(q, memory)
        result['measurement_ended_at'] = measured['ended_at']
        if not limits_start['valid'] or not limits_end['valid']: reasons.append('test_limits_invalid')
        if not measured['valid']: reasons.extend(measured['reason_codes'])
        for name in memory:
            a, b = limits_start['raw'][name], limits_end['raw'][name]
            if (a['running'] and b['running'] and a['pid'] == b['pid'] and a['container_id'] == b['container_id'] and
                    measured['resources'].get(name, {}).get('sample_count', 0) == 0):
                reasons.append(name + ':live_memory_samples_missing')
        after = engine.inspect_all(parent['required_running_containers'], tolerate_missing=True)
        result.update(test=measured, limits_start=limits_start, limits_end=limits_end,
                      system_failures=engine.failures(before, after, parent['system_under_test_containers']),
                      memory_cap_hit=(joint.memory_cap_hit(end, limits_start, measured, 'checkout') or
                                      joint.memory_cap_hit(limits_start, limits_end, measured, 'checkout')),
                      valid=not reasons)
    except Exception as exc:
        result['reason_codes'].append('infrastructure_exception')
        result['exception'] = repr(exc)
    finally:
        if sampler is not None:
            try:
                (folder / '.observer-stop').touch(); sampler.wait(timeout=15)
            except subprocess.TimeoutExpired:
                engine.run(['sudo', '--non-interactive', 'kill', '-TERM', str(sampler.pid)], check=False)
            except Exception as exc: result['diagnostic_errors'].append(repr(exc))
        try:
            done = engine.run([*prefix, 'logs', '--no-color', '--timestamps', '--tail', '200'], check=False)
            (folder / 'compose.log').write_text(done.stdout + done.stderr, encoding='utf-8')
        except Exception as exc: result['diagnostic_errors'].append(repr(exc))
        try:
            events.terminate()
            try: events.wait(timeout=5)
            except subprocess.TimeoutExpired: events.kill(); events.wait(timeout=5)
        except Exception as exc: result['diagnostic_errors'].append(repr(exc))
        event_file.close(); event_error.close()
        try:
            result['post_intervention_checkout_oom_events'] = oom_events(
                folder / 'docker-events.jsonl', result['intervention_at'], result['measurement_ended_at'])
        except Exception as exc: result['diagnostic_errors'].append(repr(exc))
        for command in [['docker', 'rm', '--force', *generators], [*prefix, 'down', '--volumes', '--remove-orphans']]:
            try: engine.run(command, check=False)
            except Exception as exc: result['diagnostic_errors'].append(repr(exc))
        for name in ['resource-samples.jsonl', 'docker-events.jsonl']:
            path = folder / name
            if path.exists():
                try:
                    with path.open('rb') as source, gzip.open(folder / (name + '.gz'), 'wb') as target:
                        while chunk := source.read(1024 * 1024): target.write(chunk)
                    path.unlink()
                except Exception as exc: result['diagnostic_errors'].append(repr(exc))
        write_json(folder / 'point-result.json', result)
    return result


def execute(upstream: Path, condition: str, output: Path) -> int:
    verification = verify(upstream, True)
    design, lock = load(ROOT / DESIGN), load(ROOT / RUNTIME)
    runtime = load(ROOT / lock['parent_runtime'])
    inherited = load(ROOT / runtime['parent_runtime']); inherited['workload'].update(runtime['workload'])
    parent = load(ROOT / inherited['parent_runtime'])
    row = next(r for r in matrix(design) if r['condition_id'] == condition)
    output.mkdir(parents=True, exist_ok=False)
    images = sorted({*parent['images'].values(), parent['workload']['k6_image']})
    for image in images: engine.run(['docker', 'pull', image])
    write_json(output / 'image-inspect.json', json.loads(engine.run(['docker', 'image', 'inspect', *images]).stdout))
    write_json(output / 'rendered-compose.json', json.loads(engine.run([
        *joint.compose_prefix(upstream, 'calibration-render'), 'config', '--no-path-resolution', '--format', 'json']).stdout))
    result = point(upstream, parent, inherited, design, runtime, row, output / 'point')
    record = {'study_version': VERSION, 'cohort': 'engineering-calibration', **row, 'point': result,
              'repository_commit': os.environ['GITHUB_SHA'], 'workflow_run_id': os.environ['GITHUB_RUN_ID'],
              'verification': verification, 'runner_image': os.getenv('ImageOS'), 'runner_image_version': os.getenv('ImageVersion')}
    write_json(output / 'calibration-result.json', record)
    print(json.dumps(record), flush=True)
    return 0


def analyze(source: Path, output: Path, commit: str) -> dict:
    design = load(ROOT / DESIGN)
    expected = {r['condition_id']: r for r in matrix(design)}
    points = {}
    for path in sorted(source.rglob('calibration-result.json')):
        record = load(path); cid = record['condition_id']
        if cid in points or cid not in expected: raise ValueError('duplicate or unknown calibration condition')
        if record['study_version'] != VERSION or record['cohort'] != 'engineering-calibration' or record['repository_commit'] != commit:
            raise ValueError('wrong calibration provenance')
        if record['checkout_mib'] != expected[cid]['checkout_mib']: raise ValueError('ceiling differs from the grid')
        for key, filename in [('design_sha256', DESIGN), ('runtime_sha256', RUNTIME)]:
            if record['verification'][key] != joint.sha256_file(ROOT / filename): raise ValueError('frozen input hash differs')
        p = record['point']
        if p['cpu'] != design['cpu_reference'] or p['memory_bytes'] != target_memory(design, record['checkout_mib']):
            raise ValueError('target allocation differs')
        for measurement in (p['baseline'], p['test']):
            if measurement is not None:
                m = measurement['checkout']
                safe = m['p95_ms'] is not None and m['p95_ms'] <= 500 and m['error_rate'] < 0.01
                if m['safe'] != safe: raise ValueError('SLO label differs from external latency/errors')
        if p['valid'] and (not p['baseline_valid'] or p['test'] is None or not p['test']['valid'] or p['reason_codes']):
            raise ValueError('invalid measurement marked valid')
        points[cid] = p
    rows = []
    for cid, spec in expected.items():
        p = points.get(cid)
        m = p['test'] if p else None
        rows.append({'condition_id': cid, 'checkout_mib': spec['checkout_mib'], 'received': p is not None,
            'baseline_valid': p['baseline_valid'] if p else None, 'valid': p['valid'] if p else None,
            'safe': m['checkout']['safe'] if m else None, 'p95_ms': m['checkout']['p95_ms'] if m else None,
            'error_rate': m['checkout']['error_rate'] if m else None,
            'checkout_memory_peak_mib': (m['resources'].get('checkout', {}).get('memory_current_bytes_max') or 0) / 1024 ** 2
                                        if m and m['resources'].get('checkout', {}).get('memory_current_bytes_max') is not None else None,
            'kernel_memory_cap_hit': p.get('memory_cap_hit') if p else None,
            'post_intervention_oom_events': len(p.get('post_intervention_checkout_oom_events', [])) if p else None,
            'system_failure': bool(p.get('system_failures')) if p else None,
            'ad_goodput': m['advertising']['goodput_per_second'] if m else None,
            'reason_codes': '|'.join(p['reason_codes']) if p else 'missing_condition', 'exception': p.get('exception') if p else None})
    missing = sorted(set(expected) - set(points))
    report = {'study_version': VERSION, 'repository_commit': commit, 'cohort': 'engineering-calibration',
              'status': 'incomplete' if missing else 'complete', 'planned_conditions': len(expected),
              'received_conditions': len(points), 'missing_conditions': missing, 'conditions': rows,
              'raw_points': points, 'interpretation': design['analysis'], 'automatic_follow_on_campaign': False}
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'summary.json', report)
    with (output / 'condition-level.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    lines = ['# RAM range: engineering observations', '',
        f"Received {len(points)}/{len(expected)} conditions. Missing: {missing}.", '',
        '| Condition | Checkout MiB | Valid | SLO safe | p95 ms | Error rate | Kernel cap hit | Post-update OOM events |',
        '| --- | ---: | --- | --- | ---: | ---: | --- | ---: |']
    lines.extend(f"| {r['condition_id']} | {r['checkout_mib']} | {r['valid']} | {r['safe']} | {r['p95_ms']} | {r['error_rate']} | {r['kernel_memory_cap_hit']} | {r['post_intervention_oom_events']} |" for r in rows)
    lines.extend(['', design['analysis'], '',
        'No joint-resource campaign was launched or selected automatically. OOM is diagnostic and never substitutes for the measured SLO label. Invalid readable measurements and absent conditions remain visible.', ''])
    (output / 'RESULTS.md').write_text('\n'.join(lines), encoding='utf-8')
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['verify', 'matrix', 'run', 'analyze'])
    parser.add_argument('--upstream-dir', type=Path)
    parser.add_argument('--condition-id')
    parser.add_argument('--artifact-dir', type=Path)
    parser.add_argument('--results-root', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--repository-commit')
    args = parser.parse_args()
    if args.command == 'run': return execute(args.upstream_dir.resolve(), args.condition_id, args.artifact_dir.resolve())
    if args.command == 'analyze':
        report = analyze(args.results_root, args.output_dir, args.repository_commit)
        print(json.dumps(report)); return 0 if report['status'] == 'complete' else 1
    verification = verify(args.upstream_dir.resolve() if args.upstream_dir else None)
    print(json.dumps({'include': matrix(load(ROOT / DESIGN))} if args.command == 'matrix' else verification))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
