"""Independent calibrations and uploaded checkpoint precede two fresh tests."""
from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from period_spec import (ROOT, DESIGN, allocation, base_config, command, config, digest, fit,
                         load, load_config, matrix, plan, prediction, quota_check, recommend,
                         render, save, stack, start_stack)
from prediction_primary import score
from primary import parse_events, read_drops
sys.path.insert(0, str(ROOT/'boundary/history/scripts'))
from history_run import first_origin, compress_logs


def provenance():
    return {'execution_commit': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
            'run_attempt': int(os.environ.get('GITHUB_RUN_ATTEMPT', '1'))}


def hosted_only():
    if os.getenv('GITHUB_ACTIONS') != 'true' or os.getenv('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('Runtime is restricted to disposable GitHub-hosted runners')


def check_compose(upstream, output):
    output.mkdir(parents=True, exist_ok=True)
    original = json.loads(command([*stack.prefix(upstream, 'period-schema'), 'config', '--format', 'json']).stdout)
    for period in config()['periods_us']:
        for quota in [min(config()['calibration_quotas']), max(config()['calibration_quotas'])]:
            for limited in [False, True]:
                path = output/f'{period}-{quota}-{limited}.json'
                save(path, render(original, allocation(quota), period, limited))
                command(['docker', 'compose', '--project-directory', str(upstream), '-f', str(path), 'config', '--quiet'])
    print('Startup and target Compose schemas passed', flush=True)


def run_session(upstream, output, block_id, name, quota, period, phase):
    output.mkdir(parents=True, exist_ok=False)
    runtime = load(ROOT/base_config()['runtime'])
    parent = load(ROOT/runtime['parent_runtime'])
    session_plan = plan(quota, phase)
    cfg, state = load_config(session_plan), allocation(quota)
    project = 'period-'+os.environ['GITHUB_RUN_ID']+'-'+block_id+'-'+name
    gen = project+'-load'
    result = {'block_id': block_id, 'session_id': name, 'quota': quota, 'period_us': period, 'phase': phase,
              'plan': session_plan, 'allocation': state, 'generator_name': gen, **provenance(),
              'infrastructure_valid': False, 'comparison_valid': False, 'reasons': [], 'windows': []}
    compose = stack.prefix(upstream, project)
    handles, sampler, events, process = [], None, None, None
    try:
        original = json.loads(command([*compose, 'config', '--format', 'json']).stdout)
        save(output/'rendered-source-compose.json', original)
        save(output/'startup-compose.json', render(original, state, period, False))
        save(output/'runtime-compose.json', render(original, state, period, True))
        compose = ['docker', 'compose', '--project-name', project, '--project-directory', str(upstream),
                   '-f', str(output/'startup-compose.json')]
        ef, ee = (output/'container-events.jsonl').open('w'), (output/'container-events.stderr.log').open('w')
        handles.extend([ef, ee])
        events = subprocess.Popen(['docker', 'events', '--filter', 'type=container', '--filter',
            'label=com.docker.compose.project='+project, '--format', '{{json .}}'], stdout=ef, stderr=ee)
        ready = {**parent, 'required_running_containers': parent['required_running_containers']+['accounting', 'kafka'],
                 'mandatory_healthy_containers': parent['mandatory_healthy_containers']+['kafka']}
        condition = {'id': name, 'period_us': period}
        start_stack(compose, ready, runtime['health_timeout_seconds'], state, condition, output/'initial-updates.jsonl')
        initial = quota_check(state, condition, require_running=True)
        save(output/'initial-quota-checks.json', initial)
        if not initial['valid']:
            raise RuntimeError('Initial limits mismatch: '+str(initial['reasons']))
        save(output/'load-design.json', cfg)
        save(output/'observer-config.json', {'output': str(output/'resource-samples.jsonl'),
             'stop_file': str(output/'.observer-stop'), 'interval_seconds': 2})
        sampler = subprocess.Popen(['sudo', '-n', sys.executable,
                    str(ROOT/'boundary/diagnostic/scripts/diagnostic_observe.py'), '--config', str(output/'observer-config.json')])
        k6 = output/'k6'
        k6.mkdir()
        stdout, stderr = k6/'stdout.log', k6/'stderr.log'
        out, err = stdout.open('w', encoding='utf-8'), stderr.open('w', encoding='utf-8')
        handles.extend([out, err])
        args = ['docker', 'run', '--name', gen, '--user', f'{os.getuid()}:{os.getgid()}',
                '--network', 'opentelemetry-demo', '-v', f'{k6}:/artifacts',
                '-v', f'{ROOT/"boundary/prediction/k6/load.js"}:/scripts/load.js:ro',
                '-v', f'{output/"load-design.json"}:/scripts/design.json:ro', '-v', f'{upstream/"pb"}:/proto:ro',
                '-e', f'TRIAL_ID={block_id}-{name}', parent['workload']['k6_image'],
                'run', '--quiet', '--log-format', 'raw', '--out', 'json=/artifacts/raw-metrics.jsonl', '/scripts/load.js']
        process = subprocess.Popen(args, stdout=out, stderr=err)
        origin = first_origin(stdout, stderr, process)
        result['load_origin_ms'] = origin
        process.wait(timeout=session_plan['total_seconds']+cfg['graceful_stop_seconds']+60)
        out.close()
        err.close()
        save(k6/'run-status.json', {'exit_code': process.returncode})
        save(k6/'container-inspect.json', json.loads(command(['docker', 'inspect', gen]).stdout))
        if process.returncode:
            raise RuntimeError('Generator exit '+str(process.returncode))
        primary = parse_events(stdout.read_text(encoding='utf-8')+'\n'+stderr.read_text(encoding='utf-8'))
        drops = read_drops(k6/'raw-metrics.jsonl')
        summary = load(k6/'summary.json')
        for kind, metric in [('start', 'calibration_starts'), ('finish', 'calibration_finishes')]:
            if sum(r['kind'] == kind for r in primary) != summary['metrics'][metric]['values']['count']:
                raise ValueError('Primary event/counter mismatch')
        if {r['origin'] for r in primary if r['stream'] == 'checkout'} != {origin}:
            raise ValueError('Live/retained origin mismatch')
        with gzip.open(output/'primary-events.json.gz', 'wt', encoding='utf-8') as stream:
            json.dump({'events': primary, 'drops': drops}, stream)
        result['windows'] = score(primary, drops, session_plan)
        final = quota_check(state, condition)
        save(output/'final-quota-checks.json', final)
        result['reasons'].extend(final['reasons'])
        if not all(w['load_valid'] for w in result['windows']):
            result['reasons'].append('load_delivery_mismatch')
        result['infrastructure_valid'] = True
    except Exception as exc:
        result['reasons'].append(str(exc))
        (output/'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        print(traceback.format_exc(), flush=True)
    finally:
        if process and process.poll() is None:
            command(['docker', 'stop', '--time', '2', gen], check=False)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if sampler:
            (output/'.observer-stop').touch()
            try:
                sampler.wait(timeout=10)
            except subprocess.TimeoutExpired:
                command(['sudo', '-n', 'kill', '-TERM', str(sampler.pid)], check=False)
                result['reasons'].append('observer_did_not_stop')
            if sampler.poll() != 0:
                result['reasons'].append('observer_failed')
        if events:
            events.terminate()
            try:
                events.wait(timeout=5)
            except subprocess.TimeoutExpired:
                events.kill()
        for handle in handles:
            handle.close()
        logs = command([*compose, 'logs', '--no-color', '--timestamps', '--tail', '100'], check=False)
        (output/'container-logs.txt').write_text(logs.stdout+logs.stderr, encoding='utf-8')
        inspected = command(['docker', 'inspect', *state['cpu']], check=False)
        save(output/'final-container-inspect.json', json.loads(inspected.stdout or '[]'))
        result['comparison_valid'] = result['infrastructure_valid'] and not result['reasons']
        save(output/'session.json', result)
        command(['docker', 'rm', '-f', gen], check=False)
        # Reset only this explicit experimental Compose project and its volumes.
        command([*compose, 'down', '--volumes', '--remove-orphans'])
        compress_logs(output)
    print(json.dumps({'session': name, 'phase': phase, 'quota': quota, 'period_us': period,
          'valid': result['comparison_valid'], 'reasons': result['reasons'],
          'checkout': [{k: w[k] for k in ['p95_ms', 'p95_censored', 'error_fraction', 'slo_safe']}
                       for w in result['windows'] if w['measured'] and w['stream'] == 'checkout']}), flush=True)
    return result


def calibrate(upstream, output, block_id):
    hosted_only()
    block = next(b for b in matrix() if b['block_id'] == block_id)
    output.mkdir(parents=True, exist_ok=False)
    result = {**block, **provenance(), 'config': config(), 'design_sha256': digest(DESIGN),
              'sessions': [], 'calibration_complete': False, 'test_complete': False, 'reasons': []}
    try:
        runtime = load(ROOT/base_config()['runtime'])
        parent = load(ROOT/runtime['parent_runtime'])
        if command(['git', '-C', str(upstream), 'rev-parse', 'HEAD']).stdout.strip() != runtime['upstream_commit']:
            raise RuntimeError('Upstream revision mismatch')
        host = {'cpu': json.loads(command(['lscpu', '--json']).stdout),
                'docker_info': json.loads(command(['docker', 'info', '--format', '{{json .}}']).stdout),
                'kernel': command(['uname', '-r']).stdout.strip(), 'runner_image': os.getenv('ImageVersion')}
        save(output/'host-context.json', host)
        if host['docker_info']['CgroupDriver'] != 'cgroupfs':
            raise RuntimeError('Exact-quota cgroupfs driver is not active')
        images = sorted({*parent['images'].values(), *runtime['additional_images'].values(), parent['workload']['k6_image']})
        for image in images:
            command(['docker', 'pull', image])
        save(output/'image-inspect.json', json.loads(command(['docker', 'image', 'inspect', *images]).stdout))
        observations = {str(p): [] for p in config()['periods_us']}
        quality = {str(p): True for p in config()['periods_us']}
        hashes = {}
        for condition in block['calibration_order']:
            name, period = condition['id'], condition['period_us']
            session = run_session(upstream, output/name, block_id, name, condition['quota'], period, 'calibration')
            result['sessions'].append({'session_id': name, 'infrastructure_valid': session['infrastructure_valid'],
                                       'comparison_valid': session['comparison_valid']})
            save(output/'block.json', result)
            if not session['infrastructure_valid']:
                raise RuntimeError('Calibration infrastructure failure; stop this whole block')
            observations[str(period)].extend(w for w in session['windows'] if w['stream'] == 'checkout' and w['measured'])
            quality[str(period)] &= session['comparison_valid']
            for filename in ['session.json', 'primary-events.json.gz']:
                relative = name+'/'+filename
                hashes[relative] = digest(output/relative)
        models = {p: fit(rows) if quality[p] else {'status': 'abstain', 'reason': 'calibration_quality_failure'}
                  for p, rows in observations.items()}
        recommendation = recommend(models['100000'])
        target = recommendation if recommendation is not None else config()['fallback_target_cpu']
        frozen = {**block, **provenance(), 'config': config(), 'design_sha256': digest(DESIGN),
                  'models': models, 'calibration_observations': observations, 'calibration_hashes': hashes,
                  'target_quota': target, 'target_is_recommendation': recommendation is not None,
                  'predictions': {p: prediction(m, target) for p, m in models.items()}, 'frozen_ms': time.time()*1000}
        save(output/'frozen-models.json', frozen)
        result['frozen_sha256'] = digest(output/'frozen-models.json')
        result['calibration_complete'] = True
        print(json.dumps({'block': block_id, 'models': models, 'target': target, 'predictions': frozen['predictions']}), flush=True)
    except Exception as exc:
        result['reasons'].append(str(exc))
        (output/'calibration-failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        print(traceback.format_exc(), flush=True)
    save(output/'block.json', result)
    return 0 if result['calibration_complete'] else 1


def validate(upstream, output, block_id):
    hosted_only()
    block = load(output/'block.json')
    frozen = load(output/'frozen-models.json')
    if block['block_id'] != block_id or any(block[k] != v for k, v in provenance().items()):
        raise ValueError('Tests are not on the calibration runner attempt')
    if digest(output/'frozen-models.json') != block['frozen_sha256']:
        raise ValueError('Frozen models changed before tests')
    for relative, expected in frozen['calibration_hashes'].items():
        if digest(output/relative) != expected:
            raise ValueError('Calibration changed after freeze')
    for period in frozen['test_order']:
        name = f'test-{period}'
        session = run_session(upstream, output/name, block_id, name, frozen['target_quota'], period, 'test')
        block['sessions'].append({'session_id': name, 'infrastructure_valid': session['infrastructure_valid'],
                                  'comparison_valid': session['comparison_valid']})
        save(output/'block.json', block)
        if not session['infrastructure_valid']:
            return 1
    if digest(output/'frozen-models.json') != block['frozen_sha256']:
        raise ValueError('Frozen models changed during tests')
    block['test_complete'] = True
    save(output/'block.json', block)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['matrix', 'config', 'check-compose', 'calibrate', 'test'])
    parser.add_argument('--block-id')
    parser.add_argument('--upstream-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if args.command == 'matrix':
        print(json.dumps({'include': [{'block_id': b['block_id']} for b in matrix()]}))
    elif args.command == 'config':
        print(json.dumps(load_config(plan(.14, 'test'))))
    elif args.command == 'check-compose':
        check_compose(args.upstream_dir.resolve(), args.output_dir.resolve())
    else:
        function = calibrate if args.command == 'calibrate' else validate
        raise SystemExit(function(args.upstream_dir.resolve(), args.output_dir.resolve(), args.block_id))
