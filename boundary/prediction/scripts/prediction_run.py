"""Calibration and frozen fresh-stack validation are separate workflow steps."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from prediction_spec import (ROOT, DESIGN, runtime_allocation, base_config, calibration_plan,
                             config, load, load_config, matrix, validation_plan)
from prediction_model import fit, forecast, point_prediction
from prediction_primary import score
from primary import parse_events, read_drops
from run import command, quota_check, save, stack
sys.path.insert(0, str(ROOT / 'boundary/history/scripts'))
from history_run import first_origin, compress_logs


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance():
    return {'execution_commit': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
            'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT', '1')}


def run_session(upstream, output, block_id, name, plan):
    output.mkdir(parents=True, exist_ok=False)
    runtime = load(ROOT / base_config()['runtime'])
    parent = load(ROOT / runtime['parent_runtime'])
    cfg = load_config(plan)
    state = runtime_allocation(plan['quota'])
    result = {'session_id': name, 'block_id': block_id, **provenance(), 'config': config(),
              'plan': plan, 'started_ms': time.time()*1000, 'infrastructure_valid': False,
              'comparison_valid': False, 'reasons': [], 'quality_reasons': [], 'windows': [], 'updates': []}
    project = 'prediction-' + os.environ['GITHUB_RUN_ID'] + '-' + block_id + '-' + name
    compose = stack.prefix(upstream, project)
    gen = project + '-load'
    sampler = events = process = None
    handles = []
    try:
        save(output / 'rendered-compose.json', json.loads(command([*compose, 'config', '--no-path-resolution', '--format', 'json']).stdout))
        ef = (output / 'container-events.jsonl').open('w', encoding='utf-8')
        ee = (output / 'container-events.stderr.log').open('w', encoding='utf-8')
        handles.extend([ef, ee])
        events = subprocess.Popen(['docker', 'events', '--filter', 'type=container', '--filter',
            'label=com.docker.compose.project=' + project, '--format', '{{json .}}'], stdout=ef, stderr=ee)
        command([*compose, 'up', '-d', '--no-build', '--pull', 'never'])
        ready = {**parent, 'required_running_containers': parent['required_running_containers'] + ['accounting', 'kafka'],
                 'mandatory_healthy_containers': parent['mandatory_healthy_containers'] + ['kafka']}
        stack.engine.wait_for_stack(ready, runtime['health_timeout_seconds'])
        stack.apply(state, None, output / 'initial-updates.jsonl')
        initial = quota_check(state, cfg)
        save(output / 'initial-quota-checks.json', initial)
        if not initial['valid']:
            raise RuntimeError('Initial quotas mismatch: ' + str(initial['reasons']))
        save(output / 'load-design.json', cfg)
        save(output / 'observer-config.json', {'containers': list(state['cpu']) + [gen],
             'output': str(output / 'resource-samples.jsonl'), 'stop_file': str(output / '.observer-stop'),
             'interval_seconds': 2, 'refresh_seconds': 6})
        sampler = subprocess.Popen(['sudo', '-n', sys.executable, str(ROOT / 'probe3/scripts/observe.py'),
                                  '--config', str(output / 'observer-config.json')])
        k6 = output / 'k6'
        k6.mkdir()
        stdout, stderr = k6 / 'stdout.log', k6 / 'stderr.log'
        out, err = stdout.open('w', encoding='utf-8'), stderr.open('w', encoding='utf-8')
        handles.extend([out, err])
        args = ['docker', 'run', '--name', gen, '--user', f'{os.getuid()}:{os.getgid()}',
                '--network', 'opentelemetry-demo', '-v', f'{k6}:/artifacts',
                '-v', f'{ROOT / "boundary/prediction/k6/load.js"}:/scripts/load.js:ro',
                '-v', f'{output / "load-design.json"}:/scripts/design.json:ro', '-v', f'{upstream / "pb"}:/proto:ro',
                '-e', f'TRIAL_ID={block_id}-{name}', parent['workload']['k6_image'],
                'run', '--quiet', '--log-format', 'raw', '--out', 'json=/artifacts/raw-metrics.jsonl', '/scripts/load.js']
        started = time.time()*1000
        process = subprocess.Popen(args, stdout=out, stderr=err)
        origin = first_origin(stdout, stderr, process)
        result['load_origin_ms'] = origin
        for index, item in enumerate(plan['updates']):
            planned = origin + 1000*item['offset']
            delay = (planned-time.time()*1000)/1000
            if delay > 0:
                time.sleep(delay)
            if process.poll() is not None:
                raise RuntimeError('Generator ended before the planned intervention')
            next_state = runtime_allocation(item['quota'])
            update = {'planned_ms': planned, 'quota': item['quota'], 'commands': []}
            for service in ['checkout', 'ad']:
                beginning = time.time()*1000
                response = command(['docker', 'update', '--cpus', str(next_state['cpu'][service]), service], check=False, timeout=20)
                update['commands'].append({'service': service, 'started_ms': beginning, 'ended_ms': time.time()*1000,
                                           'exit_code': response.returncode, 'stderr': response.stderr})
                if response.returncode:
                    save(output / f'update-{index:02d}.json', update)
                    raise RuntimeError('CPU update failed: ' + response.stderr)
            state = next_state
            update['timing_valid'] = planned <= update['commands'][0]['started_ms'] <= update['commands'][-1]['ended_ms'] <= planned + config()['update_tolerance_seconds']*1000
            save(output / f'update-{index:02d}.json', update)
            check = quota_check(state, cfg)
            save(output / f'quota-check-{index:02d}.json', check)
            result['updates'].append(update)
            result['quality_reasons'].extend(check['reasons'])
            if not update['timing_valid']:
                result['quality_reasons'].append(f'late_update_{index}')
        process.wait(timeout=max(1, (origin + plan['total_seconds']*1000 - time.time()*1000)/1000) + cfg['graceful_stop_seconds'] + 60)
        out.close()
        err.close()
        save(k6 / 'run-status.json', {'started_ms': started, 'ended_ms': time.time()*1000, 'exit_code': process.returncode})
        save(k6 / 'container-inspect.json', json.loads(command(['docker', 'inspect', gen]).stdout))
        if process.returncode:
            raise RuntimeError('Generator exit ' + str(process.returncode))
        primary = parse_events(stdout.read_text(encoding='utf-8') + '\n' + stderr.read_text(encoding='utf-8'))
        drops = read_drops(k6 / 'raw-metrics.jsonl')
        summary = load(k6 / 'summary.json')
        for kind, metric in [('start', 'calibration_starts'), ('finish', 'calibration_finishes')]:
            if sum(r['kind'] == kind for r in primary) != summary['metrics'][metric]['values']['count']:
                raise ValueError('Primary event/counter mismatch')
        if {r['origin'] for r in primary if r['stream'] == 'checkout'} != {origin}:
            raise ValueError('Live and retained origin mismatch')
        with gzip.open(output / 'primary-events.json.gz', 'wt', encoding='utf-8') as stream:
            json.dump({'events': primary, 'drops': drops}, stream)
        result['windows'] = score(primary, drops, plan)
        final = quota_check(state, cfg)
        save(output / 'final-quota-checks.json', final)
        result['quality_reasons'].extend(final['reasons'])
        if not all(w['load_valid'] for w in result['windows']):
            result['quality_reasons'].append('load_delivery_mismatch')
        result['infrastructure_valid'] = True
        result['comparison_valid'] = not result['quality_reasons']
        print(json.dumps({'session': name, 'valid': result['comparison_valid'],
              'checkout': [{k: w[k] for k in ['quota', 'p95_ms', 'p95_censored', 'error_fraction', 'slo_safe']}
                           for w in result['windows'] if w['stream'] == 'checkout' and w['measured']]}), flush=True)
    except Exception as exc:
        result['reasons'].append(str(exc))
        (output / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        print(traceback.format_exc(), flush=True)
    finally:
        if process and process.poll() is None:
            command(['docker', 'stop', '--time', '2', gen], check=False)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if sampler:
            (output / '.observer-stop').touch()
            try:
                sampler.wait(timeout=10)
            except subprocess.TimeoutExpired:
                command(['sudo', '-n', 'kill', '-TERM', str(sampler.pid)], check=False)
        if events:
            events.terminate()
            try:
                events.wait(timeout=5)
            except subprocess.TimeoutExpired:
                events.kill()
        for handle in handles:
            handle.close()
        logs = command([*compose, 'logs', '--no-color', '--timestamps', '--tail', '100'], check=False)
        (output / 'container-logs.txt').write_text(logs.stdout + logs.stderr, encoding='utf-8')
        inspected = command(['docker', 'inspect', *state['cpu']], check=False)
        save(output / 'final-container-inspect.json', json.loads(inspected.stdout or '[]'))
        result['ended_ms'] = time.time()*1000
        save(output / 'session.json', result)
        command(['docker', 'rm', '-f', gen], check=False)
        # Delete only this explicitly named experimental Compose project's volumes.
        # A failed reset aborts the enclosing stage; no state is reused silently.
        command([*compose, 'down', '--volumes', '--remove-orphans'])
        compress_logs(output)
    return result


def calibrate(upstream, output, block_id):
    block = next(r for r in matrix() if r['block_id'] == block_id)
    output.mkdir(parents=True, exist_ok=False)
    result = {**block, **provenance(), 'config': config(), 'design_sha256': digest(DESIGN),
              'calibration': [], 'calibration_infrastructure_valid': False,
              'validation_infrastructure_valid': False, 'reasons': []}
    try:
        runtime = load(ROOT / base_config()['runtime'])
        parent = load(ROOT / runtime['parent_runtime'])
        actual = command(['git', '-C', str(upstream), 'rev-parse', 'HEAD']).stdout.strip()
        if actual != runtime['upstream_commit']:
            raise ValueError('Upstream commit mismatch')
        save(output / 'host-context.json', {'upstream_commit': actual, 'runner_image': os.getenv('ImageVersion'),
             'cpu': json.loads(command(['lscpu', '--json']).stdout), 'kernel': command(['uname', '-r']).stdout.strip(),
             'docker': json.loads(command(['docker', 'version', '--format', '{{json .}}']).stdout)})
        images = sorted({*parent['images'].values(), *runtime['additional_images'].values(), parent['workload']['k6_image']})
        for image in images:
            command(['docker', 'pull', image])
        save(output / 'image-inspect.json', json.loads(command(['docker', 'image', 'inspect', *images]).stdout))
        observations, hashes = [], {}
        for quota in block['calibration_order']:
            name = f'calibration-{round(quota*1000):03d}'
            session = run_session(upstream, output / name, block_id, name, calibration_plan(quota))
            result['calibration'].append({'name': name, 'infrastructure_valid': session['infrastructure_valid'],
                                          'comparison_valid': session['comparison_valid']})
            observations.extend(w for w in session['windows'] if w['stream'] == 'checkout' and w['measured'])
            for filename in ['session.json', 'primary-events.json.gz']:
                path = output / name / filename
                if path.exists():
                    hashes[path.relative_to(output).as_posix()] = digest(path)
        result['calibration_infrastructure_valid'] = all(r['infrastructure_valid'] for r in result['calibration'])
        quality = len(result['calibration']) == len(config()['calibration_quotas']) and all(r['comparison_valid'] for r in result['calibration'])
        model = fit(observations) if quality else {'status': 'abstain', 'reason': 'calibration_quality_failure'}
        frozen = forecast(model)
        frozen['plan'] = validation_plan(frozen)
        frozen['point_predictions'] = [point_prediction(frozen, q) for q in frozen['plan']['quotas']]
        frozen.update(block_id=block_id, **provenance(), config=config(), calibration_hashes=hashes,
                      calibration_observations=observations, frozen_ms=time.time()*1000)
        save(output / 'frozen-forecast.json', frozen)
        result['frozen_forecast_sha256'] = digest(output / 'frozen-forecast.json')
        print(json.dumps({'block': block_id, 'forecast': {k: v for k, v in frozen.items() if k in
              ['status', 'reason', 'recommended_quota', 'latency_boundary_quota', 'recommended_transfer_cpu', 'model']}}), flush=True)
    except Exception as exc:
        result['reasons'].append(str(exc))
        (output / 'calibration-failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        print(traceback.format_exc(), flush=True)
    finally:
        save(output / 'block.json', result)
    return 0 if result['calibration_infrastructure_valid'] and 'frozen_forecast_sha256' in result else 1


def validate(upstream, output, block_id):
    block = load(output / 'block.json')
    frozen_path = output / 'frozen-forecast.json'
    if block['block_id'] != block_id or any(block[k] != v for k, v in provenance().items()):
        raise ValueError('Validation is not on the same block attempt')
    if digest(frozen_path) != block['frozen_forecast_sha256']:
        raise ValueError('Forecast changed before validation')
    frozen = load(frozen_path)
    for relative, expected in frozen['calibration_hashes'].items():
        if digest(output / relative) != expected:
            raise ValueError('Calibration changed after freeze')
    session = run_session(upstream, output / 'validation', block_id, 'validation', frozen['plan'])
    if digest(frozen_path) != block['frozen_forecast_sha256']:
        raise ValueError('Forecast changed during validation')
    block['validation_infrastructure_valid'] = session['infrastructure_valid']
    block['validation_comparison_valid'] = session['comparison_valid']
    save(output / 'block.json', block)
    return 0 if session['infrastructure_valid'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['matrix', 'config', 'calibrate', 'validate'])
    parser.add_argument('--block-id')
    parser.add_argument('--upstream-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if args.command == 'matrix':
        print(json.dumps({'include': matrix()}))
    elif args.command == 'config':
        print(json.dumps(load_config(calibration_plan(.30))))
    else:
        run = calibrate if args.command == 'calibrate' else validate
        raise SystemExit(run(args.upstream_dir.resolve(), args.output_dir.resolve(), args.block_id))
