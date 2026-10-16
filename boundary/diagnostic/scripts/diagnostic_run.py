"""Separate 2x2 CPU-context intervention; existing boundary models stay frozen."""
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

from diagnostic_spec import ROOT, DESIGN, base_config, config, limits, load, load_config, matrix, plan, render, runtime_allocation
from prediction_primary import score
from primary import parse_events, read_drops
from run import command, save, stack
sys.path.insert(0, str(ROOT / 'boundary/history/scripts'))
from history_run import first_origin, compress_logs


def expected_limits(state, condition):
    return {name: limits(cpu, condition['period_us'] if name == 'checkout' else config()['other_period_us'])
            for name, cpu in state['cpu'].items()}


def start_stack(compose, ready, timeout, state, condition, journal):
    command([*compose, 'up', '-d', '--no-build', '--pull', 'never'])
    stack.engine.wait_for_stack(ready, timeout)
    for name, (quota, period) in expected_limits(state, condition).items():
        started = time.time()*1000
        response = command(['docker', 'update', '--cpu-period', str(period), '--cpu-quota', str(quota), name], check=False)
        with journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'service': name, 'quota_us': quota, 'period_us': period,
                                    'started_ms': started, 'ended_ms': time.time()*1000,
                                    'exit_code': response.returncode, 'stderr': response.stderr})+'\n')
        if response.returncode:
            raise RuntimeError('Explicit CPU update failed: '+name+': '+response.stderr)
    stack.engine.wait_for_stack(ready, timeout)


def check_snapshot(items, actual, state, condition, require_running=False):
    expected = expected_limits(state, condition)
    rows, errors = {}, []
    for item in items:
        name = item['Name'].lstrip('/')
        host, status = item['HostConfig'], item['State']
        quota, period = expected[name]
        if (host.get('NanoCpus', 0) != 0 or host['CpuQuota'] != quota or host['CpuPeriod'] != period
                or host['Memory'] != state['memory'][name] or host['MemorySwap'] != state['memory'][name]):
            errors.append(name+':configured_limits_mismatch')
        fields = actual.get(name, {})
        if fields.get('cpu.max') is not None:
            if fields['cpu.max'] != f'{quota} {period}':
                errors.append(name+':effective_cpu_mismatch')
            if fields['memory.max'] != str(state['memory'][name]) or fields['memory.swap.max'] != '0':
                errors.append(name+':effective_memory_mismatch')
        elif status['Running']:
            errors.append(name+':cgroup_unreadable')
        if require_running and not status['Running']:
            errors.append(name+':not_running_before_load')
        rows[name] = {'configured': host, 'state': status, 'restart_count': item['RestartCount'], 'cgroup': fields}
    if set(rows) != set(expected):
        errors.append('missing_container')
    return {'valid': not errors, 'reasons': errors, 'rows': rows,
            'requested_cpu_total': sum(state['cpu'].values())}


def quota_check(state, condition, require_running=False):
    items = json.loads(command(['docker', 'inspect', *state['cpu']]).stdout)
    pids = {r['Name'].lstrip('/'): r['State']['Pid'] for r in items}
    code = ("import json,pathlib,sys; out={}"
            "\nfor n,pid in json.loads(sys.argv[1]).items():"
            "\n try:"
            "\n  root=pathlib.Path('/proc')/str(pid)/'root/sys/fs/cgroup'; "
            "out[n]={k:(root/k).read_text().strip() for k in ['cpu.max','memory.max','memory.swap.max']}"
            "\n except OSError as e: out[n]={'error':str(e)}"
            "\nprint(json.dumps(out))")
    actual = json.loads(command(['sudo', '-n', sys.executable, '-c', code, json.dumps(pids)]).stdout)
    return check_snapshot(items, actual, state, condition, require_running)


def background_check(name):
    item = json.loads(command(['docker', 'inspect', name]).stdout)[0]
    host = item['HostConfig']
    quota, period = limits(config()['background_cpu'], config()['other_period_us'])
    if (not item['State']['Running'] or host['CpuQuota'] != quota or host['CpuPeriod'] != period
            or host['Memory'] != 32*2**20 or host['MemorySwap'] != 32*2**20):
        raise RuntimeError('Auxiliary container stopped or its configured limits changed')
    return item


def check_compose(upstream, output):
    """Schema/path checks only: this command does not start containers."""
    output.mkdir(parents=True, exist_ok=True)
    original = json.loads(command([*stack.prefix(upstream, 'diagnostic-schema'), 'config', '--format', 'json']).stdout)
    for condition in config()['conditions']:
        for limited in [False, True]:
            path = output/(condition['id']+('-target' if limited else '-startup')+'.json')
            save(path, render(original, condition, limited=limited))
            command(['docker', 'compose', '--project-directory', str(upstream), '-f', str(path), 'config', '--quiet'])
    print('All startup and target Compose configurations passed schema checks', flush=True)


def run_session(upstream, output, block_id, condition):
    output.mkdir(parents=True, exist_ok=False)
    runtime = load(ROOT/base_config()['runtime'])
    parent = load(ROOT/runtime['parent_runtime'])
    session_plan = plan()
    cfg = load_config(session_plan)
    state = runtime_allocation(config()['checkout_cpu'])
    name = condition['id']
    project = 'cpu-diagnostic-'+os.environ['GITHUB_RUN_ID']+'-'+block_id+'-'+name
    gen, background = project+'-load', project+'-background'
    result = {'block_id': block_id, 'condition': condition, 'plan': session_plan,
              'allocation': state, 'generator_name': gen, 'background_name': background,
              'infrastructure_valid': False, 'comparison_valid': False, 'reasons': [], 'windows': []}
    compose = stack.prefix(upstream, project)
    handles, sampler, events, process = [], None, None, None
    try:
        # Resolve all original bind paths before saving the executable configuration.
        original = json.loads(command([*compose, 'config', '--format', 'json']).stdout)
        save(output/'rendered-source-compose.json', original)
        save(output/'startup-compose.json', render(original, condition, limited=False))
        save(output/'runtime-compose.json', render(original, condition))
        compose = ['docker', 'compose', '--project-name', project, '--project-directory', str(upstream),
                   '-f', str(output/'startup-compose.json')]
        command([*compose, 'config', '--quiet'])
        ef, ee = (output/'container-events.jsonl').open('w'), (output/'container-events.stderr.log').open('w')
        handles.extend([ef, ee])
        events = subprocess.Popen(['docker', 'events', '--filter', 'type=container', '--filter',
            'label=com.docker.compose.project='+project, '--format', '{{json .}}'], stdout=ef, stderr=ee)
        ready = {**parent, 'required_running_containers': parent['required_running_containers']+['accounting', 'kafka'],
                 'mandatory_healthy_containers': parent['mandatory_healthy_containers']+['kafka']}
        start_stack(compose, ready, runtime['health_timeout_seconds'], state, condition, output/'initial-updates.jsonl')
        initial = quota_check(state, condition, require_running=True)
        save(output/'initial-quota-checks.json', initial)
        if not initial['valid']:
            raise RuntimeError('Initial limits mismatch: '+str(initial['reasons']))
        quota, period = limits(config()['background_cpu'], config()['other_period_us'])
        command(['docker', 'run', '-d', '--name', background, '--network', 'none',
                 '--label', 'com.docker.compose.project='+project,
                 '--cpu-period', str(period), '--cpu-quota', str(quota), '--memory', '32m', '--memory-swap', '32m',
                 '--entrypoint', '/bin/sh', parent['workload']['k6_image'], '-c',
                 'while :; do :; done' if condition['loaded'] else 'sleep 900'])
        save(output/'background-command.json', {'quota_us': quota, 'period_us': period,
             'busy': condition['loaded'], 'image': parent['workload']['k6_image']})
        save(output/'initial-background-inspect.json', background_check(background))
        save(output/'load-design.json', cfg)
        save(output/'observer-config.json', {'output': str(output/'resource-samples.jsonl'),
             'stop_file': str(output/'.observer-stop'), 'interval_seconds': config()['sample_seconds']})
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
        save(output/'final-background-inspect.json', background_check(background))
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
        inspected = command(['docker', 'inspect', *state['cpu'], background], check=False)
        save(output/'final-container-inspect.json', json.loads(inspected.stdout or '[]'))
        result['comparison_valid'] = result['infrastructure_valid'] and not result['reasons']
        save(output/'session.json', result)
        command(['docker', 'rm', '-f', gen, background], check=False)
        # Reset only the explicitly named experimental Compose project, never the host.
        command([*compose, 'down', '--volumes', '--remove-orphans'])
        compress_logs(output)
    print(json.dumps({'block': block_id, 'condition': name, 'valid': result['comparison_valid'],
                      'reasons': result['reasons'], 'checkout': [w for w in result['windows']
                        if w['stream'] == 'checkout' and w['measured']]}), flush=True)
    return result


def run_block(upstream, output, block_id):
    if os.getenv('GITHUB_ACTIONS') != 'true' or os.getenv('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('Runtime execution is restricted to disposable GitHub-hosted runners')
    block = next(b for b in matrix() if b['block_id'] == block_id)
    output.mkdir(parents=True, exist_ok=False)
    result = {**block, 'config': config(), 'design_sha256': hashlib.sha256(DESIGN.read_bytes()).hexdigest(),
              'execution_commit': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
              'run_attempt': int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')), 'sessions': [], 'reasons': []}
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
        for name in block['order']:
            condition = next(c for c in config()['conditions'] if c['id'] == name)
            session = run_session(upstream, output/name, block_id, condition)
            result['sessions'].append({'condition': name, 'infrastructure_valid': session['infrastructure_valid'],
                                       'comparison_valid': session['comparison_valid']})
            save(output/'block.json', result)
    except Exception as exc:
        result['reasons'].append(str(exc))
        (output/'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        print(traceback.format_exc(), flush=True)
    result['complete'] = len(result['sessions']) == 4 and all(s['comparison_valid'] for s in result['sessions']) and not result['reasons']
    save(output/'block.json', result)
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['matrix', 'config', 'check-compose', 'run'])
    parser.add_argument('--block-id')
    parser.add_argument('--upstream-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if args.command == 'matrix':
        print(json.dumps({'include': matrix()}))
    elif args.command == 'config':
        print(json.dumps(load_config(plan())))
    elif args.command == 'check-compose':
        check_compose(args.upstream_dir.resolve(), args.output_dir.resolve())
    else:
        raise SystemExit(run_block(args.upstream_dir.resolve(), args.output_dir.resolve(), args.block_id))
