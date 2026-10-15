"""Run three fresh-stack paths sequentially inside each hosted-runner block."""
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

from history_spec import (ROOT, DESIGN, allocation, config, initial_allocation, load,
                          matrix, origins, score, updates, workload_config)
from run import command, quota_check, save, stack
from primary import parse_events, read_drops


def first_origin(stdout, stderr, process, timeout=60):
    deadline = time.monotonic() + timeout
    with stdout.open(encoding='utf-8') as out, stderr.open(encoding='utf-8') as err:
        while time.monotonic() < deadline:
            for stream in [out, err]:
                while True:
                    pos = stream.tell()
                    line = stream.readline()
                    if not line.endswith('\n'):
                        stream.seek(pos)
                        break
                    if line.startswith('CAL '):
                        row = json.loads(line[4:])
                        if row['stream'] == 'checkout':
                            return row['origin']
            if process.poll() is not None:
                raise RuntimeError('Generator ended before the first checkout record')
            time.sleep(.1)
    raise RuntimeError('No checkout origin received within 60 seconds')


def transition(initial, final, origin, journal):
    cfg = config()
    planned = origin + 1000*cfg['transition_seconds']
    remaining = (planned - time.time()*1000)/1000
    if remaining > 0:
        time.sleep(remaining)
    rows = []
    for name in updates(initial, final):
        start = time.time()*1000
        result = command(['docker', 'update', '--cpus', str(final['cpu'][name]), name], check=False, timeout=20)
        rows.append({'service': name, 'cpu': final['cpu'][name], 'started_ms': start,
                     'ended_ms': time.time()*1000, 'exit_code': result.returncode, 'stderr': result.stderr})
        save(journal, {'planned_ms': planned, 'updates': rows})
        if result.returncode:
            raise RuntimeError('Endpoint quota update failed: ' + result.stderr)
    return {'planned_ms': planned, 'updates': rows, 'timing_valid':
            planned <= rows[0]['started_ms'] <= rows[-1]['ended_ms'] <=
            planned + 1000*cfg['transition_completion_tolerance_seconds']}


def compress_logs(output):
    for path in output.rglob('*'):
        if path.suffix not in ('.log', '.jsonl') or path.stat().st_size < 100000:
            continue
        with path.open('rb') as source, gzip.open(str(path) + '.gz', 'wb') as target:
            while chunk := source.read(1024*1024):
                target.write(chunk)
        path.unlink()


def run_path(upstream, output, block, path, position, runtime, parent):
    cfg, load_cfg = config(), workload_config()
    initial, final = initial_allocation(path, block['target_quota']), allocation(block['target_quota'])
    output.mkdir(parents=True, exist_ok=False)
    ident = block['block_id'] + '-' + path
    result = {**block, 'trial_id': ident, 'path': path, 'position': position,
              'config': cfg, 'workload_config': load_cfg, 'initial_allocation': initial,
              'final_allocation': final, 'infrastructure_valid': False, 'comparison_valid': False,
              'windows': [], 'reasons': [], 'quality_reasons': [], 'transition': None,
              'execution_commit': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
              'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'design_sha256': hashlib.sha256(DESIGN.read_bytes()).hexdigest()}
    compose = stack.prefix(upstream, 'history-' + os.environ['GITHUB_RUN_ID'] + '-' + ident)
    gen = ident + '-load'
    sampler = events = process = None
    handles = []
    try:
        save(output / 'rendered-compose.json', json.loads(command([*compose, 'config', '--no-path-resolution', '--format', 'json']).stdout))
        ef = (output / 'container-events.jsonl').open('w', encoding='utf-8')
        ee = (output / 'container-events.stderr.log').open('w', encoding='utf-8')
        handles.extend([ef, ee])
        events = subprocess.Popen(['docker', 'events', '--filter', 'type=container', '--filter',
            'label=com.docker.compose.project=history-' + os.environ['GITHUB_RUN_ID'] + '-' + ident,
            '--format', '{{json .}}'], stdout=ef, stderr=ee)
        command([*compose, 'up', '-d', '--no-build', '--pull', 'never'])
        ready = {**parent, 'required_running_containers': parent['required_running_containers'] + ['accounting', 'kafka'],
                 'mandatory_healthy_containers': parent['mandatory_healthy_containers'] + ['kafka']}
        stack.engine.wait_for_stack(ready, runtime['health_timeout_seconds'])
        stack.apply(initial, None, output / 'initial-updates.jsonl')
        initial_check = quota_check(initial, load_cfg)
        save(output / 'initial-quota-checks.json', initial_check)
        if not initial_check['valid']:
            raise RuntimeError('Initial quota mismatch: ' + str(initial_check['reasons']))
        samples = output / 'resource-samples.jsonl'
        save(output / 'observer-config.json', {'containers': list(initial['cpu']) + [gen],
             'output': str(samples), 'stop_file': str(output / '.observer-stop'), 'interval_seconds': 2, 'refresh_seconds': 6})
        sampler = subprocess.Popen(['sudo', '-n', sys.executable, str(ROOT / 'probe3/scripts/observe.py'),
                                  '--config', str(output / 'observer-config.json')])
        save(output / 'load-design.json', load_cfg)
        k6 = output / 'k6'
        k6.mkdir()
        stdout, stderr = k6 / 'stdout.log', k6 / 'stderr.log'
        out, err = stdout.open('w', encoding='utf-8'), stderr.open('w', encoding='utf-8')
        handles.extend([out, err])
        args = ['docker', 'run', '--name', gen, '--user', f'{os.getuid()}:{os.getgid()}',
                '--network', 'opentelemetry-demo', '-v', f'{k6}:/artifacts',
                '-v', f'{ROOT / "boundary/k6/load.js"}:/scripts/load.js:ro',
                '-v', f'{output / "load-design.json"}:/scripts/design.json:ro',
                '-v', f'{upstream / "pb"}:/proto:ro', '-e', f'TRIAL_ID={ident}', parent['workload']['k6_image'],
                'run', '--quiet', '--log-format', 'raw', '--out', 'json=/artifacts/raw-metrics.jsonl', '/scripts/load.js']
        started = time.time()*1000
        process = subprocess.Popen(args, stdout=out, stderr=err)
        origin = first_origin(stdout, stderr, process)
        result['transition'] = transition(initial, final, origin, output / 'transition.json')
        endpoint_check = quota_check(final, load_cfg)
        save(output / 'endpoint-quota-checks.json', endpoint_check)
        result['quality_reasons'].extend(endpoint_check['reasons'])
        if not result['transition']['timing_valid']:
            result['quality_reasons'].append('transition_outside_fixed_timing_tolerance')
        total = load_cfg['warmup_seconds'] + load_cfg['measurement_windows']*load_cfg['window_seconds']
        process.wait(timeout=max(1, (origin + total*1000 - time.time()*1000)/1000) + load_cfg['graceful_stop_seconds'] + 60)
        out.close()
        err.close()
        save(k6 / 'run-status.json', {'started_ms': started, 'ended_ms': time.time()*1000, 'exit_code': process.returncode})
        save(k6 / 'container-inspect.json', json.loads(command(['docker', 'inspect', gen]).stdout))
        if process.returncode:
            raise RuntimeError('Load generator failed with exit ' + str(process.returncode))
        primary = parse_events(stdout.read_text(encoding='utf-8') + '\n' + stderr.read_text(encoding='utf-8'))
        drops = read_drops(k6 / 'raw-metrics.jsonl')
        summary = load(k6 / 'summary.json')
        for kind, metric in [('start', 'calibration_starts'), ('finish', 'calibration_finishes')]:
            if sum(r['kind'] == kind for r in primary) != summary['metrics'][metric]['values']['count']:
                raise ValueError('Primary log/counter mismatch')
        if origins(primary)['checkout'] != origin:
            raise ValueError('Live and retained origins disagree')
        with gzip.open(output / 'primary-events.json.gz', 'wt', encoding='utf-8') as stream:
            json.dump({'events': primary, 'drops': drops}, stream)
        result['windows'] = score(primary, drops)
        final_check = quota_check(final, load_cfg)
        save(output / 'final-quota-checks.json', final_check)
        result['quality_reasons'].extend(final_check['reasons'])
        if not all(w['load_valid'] for w in result['windows']):
            result['quality_reasons'].append('load_delivery_mismatch')
        result['infrastructure_valid'] = True
        result['comparison_valid'] = not result['quality_reasons']
        print(json.dumps({'trial': ident, 'comparison_valid': result['comparison_valid'],
              'p95_ms': [w['p95_ms'] for w in result['windows'] if w['stream'] == 'checkout' and w['measured']]}), flush=True)
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
        inspected = command(['docker', 'inspect', *initial['cpu']], check=False)
        save(output / 'final-container-inspect.json', json.loads(inspected.stdout or '[]'))
        save(output / 'trial.json', result)
        command(['docker', 'rm', '-f', gen], check=False)
        # Only this explicitly named path's Compose project and volumes are removed.
        # Failure aborts the block: never reuse an incompletely reset stack.
        command([*compose, 'down', '--volumes', '--remove-orphans'])
        compress_logs(output)
    return result


def run_block(upstream, output, block_id):
    block = next(r for r in matrix() if r['block_id'] == block_id)
    cfg, load_cfg = config(), workload_config()
    runtime = load(ROOT / load_cfg['runtime'])
    parent = load(ROOT / runtime['parent_runtime'])
    output.mkdir(parents=True, exist_ok=False)
    result = {**block, 'config': cfg, 'run_id': os.environ['GITHUB_RUN_ID'],
              'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'), 'execution_commit': os.environ['GITHUB_SHA'],
              'paths': [], 'infrastructure_valid': False, 'reasons': []}
    try:
        actual = command(['git', '-C', str(upstream), 'rev-parse', 'HEAD']).stdout.strip()
        if actual != runtime['upstream_commit']:
            raise ValueError('Upstream commit mismatch')
        save(output / 'host-context.json', {'upstream_commit': actual, 'runner_image': os.getenv('ImageVersion'),
             'cpu': json.loads(command(['lscpu', '--json']).stdout),
             'kernel': command(['uname', '-r']).stdout.strip(),
             'docker': json.loads(command(['docker', 'version', '--format', '{{json .}}']).stdout)})
        images = sorted({*parent['images'].values(), *runtime['additional_images'].values(), parent['workload']['k6_image']})
        for image in images:
            command(['docker', 'pull', image])
        save(output / 'image-inspect.json', json.loads(command(['docker', 'image', 'inspect', *images]).stdout))
        for position, path in enumerate(block['order'], 1):
            trial = run_path(upstream, output / path, block, path, position, runtime, parent)
            result['paths'].append({'path': path, 'infrastructure_valid': trial['infrastructure_valid'],
                                    'comparison_valid': trial['comparison_valid']})
        result['infrastructure_valid'] = all(p['infrastructure_valid'] for p in result['paths'])
    except Exception as exc:
        result['reasons'].append(str(exc))
        (output / 'block-failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        print(traceback.format_exc(), flush=True)
    finally:
        save(output / 'block.json', result)
    return 0 if result['infrastructure_valid'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['matrix', 'config', 'run'])
    parser.add_argument('--block-id')
    parser.add_argument('--upstream-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if args.command == 'matrix':
        print(json.dumps({'include': matrix()}))
    elif args.command == 'config':
        print(json.dumps(workload_config()))
    else:
        raise SystemExit(run_block(args.upstream_dir.resolve(), args.output_dir.resolve(), args.block_id))
