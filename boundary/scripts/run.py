"""A fresh static allocation per runner; workload is continuous throughout."""
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

from spec import ROOT, DESIGN, allocation, load, matrix
from primary import parse_events, read_drops, summarize

sys.path.insert(0, str(ROOT / 'probe7/scripts'))
import runtime as stack


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def command(args, check=True, timeout=600):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'Command failed: {args}\n{result.stderr[-6000:]}')
    return result


def quota_check(state, cfg):
    result = stack.quotas(state)
    for name, row in result['rows'].items():
        value = row.get('cgroup', {}).get('cpu.max')
        if value is not None and int(value.split()[1]) != cfg['cpu_period_us']:
            result['reasons'].append(name + ':cpu_period_mismatch')
    result['valid'] = not result['reasons']
    return result


def run(upstream, output, trial_id):
    cfg = load(DESIGN)
    trial = next(r for r in matrix() if r['trial_id'] == trial_id)
    runtime = load(ROOT / cfg['runtime'])
    parent = load(ROOT / runtime['parent_runtime'])
    state = allocation(trial['quota'])
    output.mkdir(parents=True, exist_ok=False)
    result = {**trial, 'version': cfg['version'], 'config': cfg, 'allocation': state,
              'execution_commit': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
              'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'), 'infrastructure_valid': False,
              'windows': [], 'reasons': [], 'design_sha256': hashlib.sha256(DESIGN.read_bytes()).hexdigest()}
    project = 'boundary-' + os.environ['GITHUB_RUN_ID'] + '-' + trial_id
    compose = stack.prefix(upstream, project)
    gen = project + '-load'
    sampler = events = None
    handles = []
    try:
        actual = command(['git', '-C', str(upstream), 'rev-parse', 'HEAD']).stdout.strip()
        if actual != runtime['upstream_commit']:
            raise ValueError('Upstream commit mismatch')
        save(output / 'host-context.json', {'upstream_commit': actual, 'runner_image': os.getenv('ImageVersion'),
             'cpu': json.loads(command(['lscpu', '--json']).stdout),
             'kernel': command(['uname', '-r']).stdout.strip(),
             'docker': json.loads(command(['docker', 'version', '--format', '{{json .}}']).stdout)})
        for image in sorted({*parent['images'].values(), *runtime['additional_images'].values(), parent['workload']['k6_image']}):
            command(['docker', 'pull', image])
        rendered = json.loads(command([*compose, 'config', '--no-path-resolution', '--format', 'json']).stdout)
        save(output / 'rendered-compose.json', rendered)
        images = sorted({s['image'] for s in rendered['services'].values() if s.get('profiles') != ['disabled']})
        save(output / 'image-inspect.json', json.loads(command(['docker', 'image', 'inspect', *images, parent['workload']['k6_image']]).stdout))
        ef = (output / 'container-events.jsonl').open('w', encoding='utf-8')
        ee = (output / 'container-events.stderr.log').open('w', encoding='utf-8')
        handles.extend([ef, ee])
        events = subprocess.Popen(['docker', 'events', '--filter', 'type=container', '--filter',
                                  'label=com.docker.compose.project=' + project, '--format', '{{json .}}'], stdout=ef, stderr=ee)
        command([*compose, 'up', '-d', '--no-build', '--pull', 'never'])
        ready = {**parent, 'required_running_containers': parent['required_running_containers'] + ['accounting', 'kafka'],
                 'mandatory_healthy_containers': parent['mandatory_healthy_containers'] + ['kafka']}
        stack.engine.wait_for_stack(ready, runtime['health_timeout_seconds'])
        stack.apply(state, None, output / 'limit-updates.jsonl')
        initial = quota_check(state, cfg)
        save(output / 'initial-quota-checks.json', initial)
        if not initial['valid']:
            raise ValueError(f'Initial quota mismatch: {initial["reasons"]}')
        samples = output / 'resource-samples.jsonl'
        save(output / 'observer-config.json', {'containers': list(state['cpu']) + [gen],
             'output': str(samples), 'stop_file': str(output / '.observer-stop'), 'interval_seconds': 2, 'refresh_seconds': 6})
        sampler = subprocess.Popen(['sudo', '-n', sys.executable, str(ROOT / 'probe3/scripts/observe.py'),
                                    '--config', str(output / 'observer-config.json')])
        k6 = output / 'k6'
        k6.mkdir()
        args = ['docker', 'run', '--name', gen, '--user', f'{os.getuid()}:{os.getgid()}',
                '--network', 'opentelemetry-demo', '-v', f'{k6}:/artifacts',
                '-v', f'{ROOT / "boundary/k6/load.js"}:/scripts/load.js:ro',
                '-v', f'{DESIGN}:/scripts/design.json:ro', '-v', f'{upstream / "pb"}:/proto:ro',
                '-e', f'TRIAL_ID={trial_id}', parent['workload']['k6_image'],
                'run', '--quiet', '--log-format', 'raw', '--out', 'json=/artifacts/raw-metrics.jsonl', '/scripts/load.js']
        begin = time.time()
        total = cfg['warmup_seconds'] + cfg['window_seconds'] * cfg['measurement_windows']
        completed = command(args, check=False, timeout=total + cfg['graceful_stop_seconds'] + 180)
        (k6 / 'stdout.log').write_text(completed.stdout, encoding='utf-8')
        (k6 / 'stderr.log').write_text(completed.stderr, encoding='utf-8')
        save(k6 / 'run-status.json', {'started_ms': begin * 1000, 'ended_ms': time.time() * 1000, 'exit_code': completed.returncode})
        save(k6 / 'container-inspect.json', json.loads(command(['docker', 'inspect', gen]).stdout))
        if completed.returncode:
            raise RuntimeError(f'Load generator failed: {completed.stderr[-3000:]}')
        primary = parse_events(completed.stdout + '\n' + completed.stderr)
        drops = read_drops(k6 / 'raw-metrics.jsonl')
        summary = load(k6 / 'summary.json')
        for kind, metric in [('start', 'calibration_starts'), ('finish', 'calibration_finishes')]:
            if sum(r['kind'] == kind for r in primary) != summary['metrics'][metric]['values']['count']:
                raise ValueError('Primary log/counter mismatch')
        origins = {r['origin'] for r in primary}
        if max(origins) - min(origins) > 1000:
            raise ValueError('Concurrent scenarios started over one second apart')
        result['windows'] = summarize(primary, drops, cfg)
        with gzip.open(output / 'primary-events.json.gz', 'wt', encoding='utf-8') as f:
            json.dump({'events': primary, 'drops': drops}, f)
        final = quota_check(state, cfg)
        save(output / 'final-quota-checks.json', final)
        result['reasons'].extend(final['reasons'])
        for row in result['windows']:
            row['resources'] = stack.resources(samples, row['window_start_ms'], row['window_end_ms'], state)
        result['infrastructure_valid'] = not result['reasons']
        print(json.dumps({'trial': trial_id, 'valid': result['infrastructure_valid'],
                         'checkout': [{k: w[k] for k in ['offset_seconds', 'p95_ms', 'error_fraction', 'load_valid', 'client_outstanding_end']}
                                      for w in result['windows'] if w['stream'] == 'checkout' and w['measured']]}), flush=True)
    except Exception as exc:
        result['reasons'].append(str(exc))
        (output / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        print(traceback.format_exc(), flush=True)
    finally:
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
        save(output / 'trial.json', result)
        command(['docker', 'rm', '-f', gen], check=False)
        command([*compose, 'down', '--volumes', '--remove-orphans'], check=False)
        # Lossless compression preserves raw evidence while keeping artifacts small.
        for path in output.rglob('*'):
            if path.suffix not in ('.log', '.jsonl') or path.stat().st_size < 100000:
                continue
            with path.open('rb') as source, gzip.open(str(path) + '.gz', 'wb') as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            path.unlink()
    return 0 if result['infrastructure_valid'] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['matrix', 'run'])
    parser.add_argument('--trial-id')
    parser.add_argument('--upstream-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if args.command == 'matrix':
        print(json.dumps({'include': matrix()}))
    else:
        raise SystemExit(run(args.upstream_dir.resolve(), args.output_dir.resolve(), args.trial_id))


if __name__ == '__main__':
    main()
