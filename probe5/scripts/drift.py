from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'probe3/scripts'))
import run_block as engine
from study import features, generator_valid, load, project_name, sha256_file, verify as verify_parent, write_json

VERSION = 'adaptive-migration-0.1.0'
DESIGN = 'probe5/design-v0.1.0.json'
RUNTIME = 'probe5/runtime-v0.1.0.json'
OVERLAY = 'probe5/memory-v0.1.0.yaml'


def matrix(design: dict) -> list[dict]:
    ids = [f'migration-{i:03d}' for i in range(1, design['replications'] + 1)]
    ordered = sorted(ids, key=lambda s: hashlib.sha256(f"{design['randomization_salt']}:{s}".encode()).digest())
    return [{'block_id': bid, 'order': ['drift', 'control'] if ordered.index(bid) % 2 == 0
             else ['control', 'drift']} for bid in ids]


def proposal(q: dict, index: int, design: dict) -> tuple[dict, str]:
    donor = design['donor_cycle'][(index - 1) % len(design['donor_cycle'])]
    amount = Decimal(str(design['transfer_cpu']))
    changed = {k: Decimal(str(v)) for k, v in q.items()}
    changed[donor] -= amount
    changed['ad'] += amount
    if min(changed.values()) < Decimal('0.05') or sum(changed.values()) != Decimal('1'):
        raise ValueError('proposal violates the positive closed budget')
    return {k: float(v) for k, v in changed.items()}, donor


def decision(previous: dict) -> str:
    if not previous['valid']:
        return 'technical_measurement_failure'
    if not previous['checkout']['safe']:
        return 'observed_slo_boundary'
    throttling = previous['advertising'].get('throttled_period_fraction_mean')
    if throttling is None:
        return 'recipient_pressure_unobserved'
    if throttling <= 0:
        return 'recipient_pressure_not_binding'
    return 'transfer'


def compose_prefix(upstream: Path, project: str) -> list[str]:
    return [*engine.compose_prefix(ROOT, upstream, project), '-f', str(ROOT / OVERLAY)]


def verify(upstream: Path | None = None, check_runner: bool = False) -> dict:
    design, runtime = load(ROOT / DESIGN), load(ROOT / RUNTIME)
    if design['study_version'] != VERSION or runtime['study_version'] != VERSION:
        raise ValueError('version mismatch')
    if design['replications'] != 20 or design['maximum_moves'] != 18 or design['transfer_cpu'] != 0.04:
        raise ValueError('unexpected controller design')
    if design['checkout_rate'] != 40 or design['donor_cycle'] != ['checkout', 'payment', 'shipping']:
        raise ValueError('unexpected workload or donor order')
    if design['advertising']['vus'] != 8 or design['advertising']['rpc_timeout_seconds'] != 2 or design['advertising']['context_keys'] != ['clothing']:
        raise ValueError('unexpected competing workload')
    if runtime['workload'] != {'pre_allocated_vus': 800, 'max_vus': 800, 'minimum_started_fraction': 0.99}:
        raise ValueError('unexpected static generator capacity')
    q = design['reference']
    for index in range(1, design['maximum_moves'] + 1):
        q, _ = proposal(q, index, design)
    if design['analysis']['binary_success_criterion'] is not None:
        raise ValueError('no binary scientific success criterion')
    if sha256_file(ROOT / runtime['parent_runtime']) != runtime['parent_runtime_sha256']:
        raise ValueError('parent runtime mismatch')
    parent = verify_parent(ROOT, upstream, check_runner)
    report = {'valid': True, 'study_version': VERSION, 'blocks': len(matrix(design)),
              'parent_verification': parent, 'design_sha256': sha256_file(ROOT / DESIGN),
              'runtime_sha256': sha256_file(ROOT / RUNTIME), 'overlay_sha256': sha256_file(ROOT / OVERLAY)}
    if upstream:
        rendered = json.loads(engine.run([*compose_prefix(upstream, 'migration-render'), 'config',
                                          '--no-path-resolution', '--format', 'json']).stdout)
        for service, memory in runtime['memory_reserves'].items():
            if int(rendered['services'][service]['deploy']['resources']['limits']['memory']) != memory:
                raise ValueError(f'rendered memory differs: {service}')
        for service, value in runtime['gomemlimit'].items():
            if rendered['services'][service]['environment']['GOMEMLIMIT'] != value:
                raise ValueError(f'rendered Go reserve differs: {service}')
        if not (upstream / runtime['advertising_proto']).is_file():
            raise ValueError('pinned RPC definition missing')
        if str(rendered['services']['ad']['environment']['AD_PORT']) != '9555':
            raise ValueError('advertising endpoint port differs')
    return report


def summarize_ads(summary: dict, seconds: int) -> dict:
    def count(name):
        value = summary['metrics'][name]['values']['count']
        if not math.isfinite(value) or value < 0 or value != int(value):
            raise ValueError('invalid advertising counter')
        return int(value)
    attempts, completions, successes = (count('ad_window_' + n) for n in ('attempts', 'completions', 'successes'))
    if not 0 <= successes <= completions <= attempts:
        raise ValueError('advertising counter invariant failed')
    start = summary['metrics']['ad_window_start_ms']['values']['min']
    return {'attempts': attempts, 'completions_inside_window': completions,
            'successful_inside_window': successes, 'goodput_per_second': successes / seconds,
            'connection_failures': count('ad_connection_failures'),
            'window_started_ms': start, 'window_ended_ms': start + seconds * 1000}


def advertising_phase(upstream: Path, parent: dict, design: dict, runtime: dict,
                      seconds: int, folder: Path, generator: str) -> dict:
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / 'scenario-config.json', {'executor': 'constant-vus',
               'vus': design['advertising']['vus'], 'duration_seconds': seconds,
               'rpc_timeout_seconds': design['advertising']['rpc_timeout_seconds'],
               'endpoint': runtime['advertising_endpoint'], 'gracefulStop_seconds': 30})
    command = ['docker', 'run', '--name', generator, '--user', f'{os.getuid()}:{os.getgid()}',
               '--network', 'opentelemetry-demo', '-v', f'{folder.resolve()}:/artifacts',
               '-v', f"{ROOT / 'probe5/k6/advertising.js'}:/scripts/advertising.js:ro",
               '-v', f"{(upstream / runtime['advertising_proto']).parent}:/proto:ro"]
    for key, value in {'DURATION_SECONDS': seconds, 'AD_VUS': design['advertising']['vus'],
                       'AD_TIMEOUT_SECONDS': design['advertising']['rpc_timeout_seconds'],
                       'AD_ENDPOINT': runtime['advertising_endpoint']}.items():
        command.extend(['-e', f'{key}={value}'])
    command.extend([parent['workload']['k6_image'], 'run', '/scripts/advertising.js'])
    started = engine.utc()
    done = engine.run(command, check=False)
    write_json(folder / 'run-status.json', {'started_at': started, 'ended_at': engine.utc(),
               'exit_code': done.returncode})
    (folder / 'stdout.log').write_text(done.stdout, encoding='utf-8')
    (folder / 'stderr.log').write_text(done.stderr, encoding='utf-8')
    engine.run(['docker', 'rm', '--force', generator], check=False)
    measured = summarize_ads(load(folder / 'summary.json'), seconds)
    measured['k6_exit_code'] = done.returncode
    return measured


def ad_resource_samples(path: Path, started: str, ended: str) -> dict:
    samples = []
    text = path.read_text(encoding='utf-8')
    lines = text.splitlines()
    if text and not text.endswith('\n'):
        lines = lines[:-1]
    for line in lines:
        row = json.loads(line)
        if started <= row['timestamp'] <= ended:
            delta = row['containers'].get('ad', {}).get('delta')
            if delta:
                samples.append(delta)
    throttling = [r['throttled_period_fraction'] for r in samples if r['throttled_period_fraction'] is not None]
    return {'resource_intervals': len(samples),
            'throttled_period_fraction_mean': sum(throttling) / len(throttling) if throttling else None,
            'cpu_cores_mean': sum(r['cpu_cores'] for r in samples) / len(samples) if samples else None}


def concurrent_phase(upstream: Path, parent: dict, inherited: dict, design: dict, runtime: dict,
                     bid: str, hid: str, name: str, seconds: int, folder: Path,
                     checkout_generator: str, ad_generator: str, samples: Path) -> dict:
    spec = {**design, 'rate': design['checkout_rate']}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        checkout = pool.submit(engine.phase, ROOT, parent, inherited, spec, bid, hid,
                               name, seconds, folder / 'checkout', checkout_generator, primary=True)
        advertising = pool.submit(advertising_phase, upstream, parent, design, runtime,
                                  seconds, folder / 'advertising', ad_generator)
        checkout_result, ad_result = checkout.result(), advertising.result()
    status = load(folder / 'checkout/run-status.json')
    ad_result.update(ad_resource_samples(samples, status['started_at'], status['ended_at']))
    checkout_start = None
    with gzip.open(folder / 'checkout/raw-metrics.jsonl.gz', 'rt', encoding='utf-8') as stream:
        for line in stream:
            point = json.loads(line)
            if point.get('type') == 'Point' and point.get('metric') == 'protocol_iterations_started':
                checkout_start = dt.datetime.fromisoformat(point['data']['time'].replace('Z', '+00:00')).timestamp() * 1000
                break
    overlap = max(0, min(checkout_start + seconds * 1000, ad_result['window_ended_ms']) -
                  max(checkout_start, ad_result['window_started_ms'])) / (seconds * 1000) if checkout_start is not None else 0
    reasons = []
    if not generator_valid(checkout_result):
        reasons.append('checkout_started_below_99_percent')
    if checkout_result['k6_exit_code'] != 0 or ad_result['k6_exit_code'] != 0:
        reasons.append('load_generator_failed')
    if ad_result['attempts'] <= 0 or ad_result['resource_intervals'] <= 0:
        reasons.append('advertising_measurement_missing')
    if overlap <= 0:
        reasons.append('concurrent_workload_window_missing')
    return {'valid': not reasons, 'reason_codes': reasons, 'checkout': checkout_result,
            'advertising': ad_result, 'started_at': status['started_at'], 'ended_at': status['ended_at'],
            'checkout_window_started_ms': checkout_start, 'workload_overlap_fraction': overlap}


def history(upstream: Path, parent: dict, inherited: dict, design: dict, runtime: dict,
            bid: str, policy: str, folder: Path, smoke: bool = False) -> dict:
    folder.mkdir(parents=True, exist_ok=False)
    prefix = compose_prefix(upstream, project_name(os.environ['GITHUB_RUN_ID'], bid, policy))
    checkout_generator, ad_generator = f'{bid}-{policy}-checkout-k6', f'{bid}-{policy}-ad-k6'
    result = {'policy': policy, 'baseline_valid': False, 'baseline': None, 'epochs': [],
              'stop_reason': 'not_started', 'diagnostic_errors': []}
    events_file = (folder / 'docker-events.jsonl').open('w', encoding='utf-8')
    events_error = (folder / 'docker-events.stderr.log').open('w', encoding='utf-8')
    events = subprocess.Popen(['docker', 'events', '--since', engine.utc(), '--filter', 'type=container',
                              '--filter', f"label=com.docker.compose.project={prefix[3]}", '--format', '{{json .}}'],
                             stdout=events_file, stderr=events_error)
    sampler = None
    try:
        engine.run([*prefix, 'up', '--detach', '--no-build', '--pull', 'never'])
        engine.wait_for_stack(parent, runtime['health_check_timeout_seconds'])
        initial = engine.inspect_all(parent['required_running_containers'])
        write_json(folder / 'initial-container-inspect.json', initial)
        write_json(folder / 'observer-config.json', {
            'containers': [*design['reference'], 'astronomy-db', 'frontend', 'cart', 'product-catalog',
                           checkout_generator, ad_generator],
            'output': str((folder / 'resource-samples.jsonl').resolve()),
            'stop_file': str((folder / '.observer-stop').resolve()),
            'interval_seconds': 2, 'refresh_seconds': 6})
        sampler = subprocess.Popen(['sudo', '--non-interactive', sys.executable,
                                    str(ROOT / 'probe3/scripts/observe.py'), '--config', str(folder / 'observer-config.json')])
        q = dict(design['reference'])
        engine.apply(q)
        quota = engine.quota_check(q)
        concurrent_phase(upstream, parent, inherited, design, runtime, bid, policy, 'warmup',
                         design['warmup_seconds'], folder / 'warmup', checkout_generator, ad_generator,
                         folder / 'resource-samples.jsonl')
        previous = concurrent_phase(upstream, parent, inherited, design, runtime, bid, policy, 'baseline',
                                    design['baseline_seconds'], folder / 'baseline', checkout_generator,
                                    ad_generator, folder / 'resource-samples.jsonl')
        result['baseline'] = previous
        before = engine.inspect_all(parent['required_running_containers'])
        result['pre_adaptation_failures'] = engine.failures(initial, before, parent['system_under_test_containers'])
        result['baseline_quota'] = quota
        result['baseline_reason_codes'] = list(previous['reason_codes'])
        if not previous['checkout']['safe']:
            result['baseline_reason_codes'].append('baseline_slo_unsafe')
        if not quota['valid']:
            result['baseline_reason_codes'].append('baseline_quota_invalid')
        if result['pre_adaptation_failures']:
            result['baseline_reason_codes'].append('pre_adaptation_system_failure')
        result['baseline_valid'] = previous['valid'] and previous['checkout']['safe'] and quota['valid'] and not result['pre_adaptation_failures']
        if not result['baseline_valid']:
            result['stop_reason'] = 'baseline_invalid'
            return result
        result['adaptation_started_at'] = engine.utc()
        maximum = 1 if smoke else design['maximum_moves']
        for index in range(1, maximum + 1):
            if policy == 'drift':
                action = decision(previous)
                if action != 'transfer':
                    result['stop_reason'] = action
                    break
                changed, donor = proposal(q, index, design)
            else:
                changed, donor = q, None
            input_state = {'checkout_safe': previous['checkout']['safe'],
                           'ad_throttling': previous['advertising']['throttled_period_fraction_mean'],
                           'ad_goodput': previous['advertising']['goodput_per_second']}
            engine.apply(changed)
            observed = engine.quota_check(changed)
            concurrent_phase(upstream, parent, inherited, design, runtime, bid, policy, f'stabilize-{index:02d}',
                             design['stabilization_seconds'], folder / f'epochs/{index:02d}/stabilization',
                             checkout_generator, ad_generator, folder / 'resource-samples.jsonl')
            measured = concurrent_phase(upstream, parent, inherited, design, runtime, bid, policy,
                                        f'epoch-{index:02d}', design['measurement_seconds'],
                                        folder / f'epochs/{index:02d}/measurement', checkout_generator,
                                        ad_generator, folder / 'resource-samples.jsonl')
            if not observed['valid']:
                measured['valid'] = False
                measured['reason_codes'].append('effective_quota_invalid')
            after = engine.inspect_all(parent['required_running_containers'], tolerate_missing=True)
            measured.update(epoch=index, donor=donor, quotas=changed, manipulation=observed,
                            decision_input=input_state, coordinates=features(design, changed),
                            goodput_change=measured['advertising']['goodput_per_second'] - input_state['ad_goodput'],
                            system_failures=engine.failures(before, after, parent['system_under_test_containers']))
            result['epochs'].append(measured)
            write_json(folder / f'epochs/{index:02d}/epoch-result.json', measured)
            print(json.dumps({'policy': policy, 'epoch': index, 'valid': measured['valid'],
                              'checkout_safe': measured['checkout']['safe'], 'p95_ms': measured['checkout']['p95_ms'],
                              'ad_goodput': measured['advertising']['goodput_per_second'], 'quotas': changed}), flush=True)
            q, previous, before = changed, measured, after
            if not measured['valid']:
                result['stop_reason'] = 'technical_measurement_failure'
                break
        else:
            result['stop_reason'] = 'move_limit_reached'
        if policy == 'drift' and result['epochs'] and result['epochs'][-1]['valid'] and not result['epochs'][-1]['checkout']['safe']:
            result['stop_reason'] = 'observed_slo_boundary'
        result['measurement_ended_at'] = engine.utc()
    except Exception as exc:
        result['stop_reason'] = 'infrastructure_exception'
        result['exception'] = repr(exc)
    finally:
        if sampler is not None:
            try:
                (folder / '.observer-stop').touch()
                sampler.wait(timeout=15)
            except subprocess.TimeoutExpired:
                engine.run(['sudo', '--non-interactive', 'kill', '-TERM', str(sampler.pid)], check=False)
                try:
                    sampler.wait(timeout=10)
                except Exception as exc:
                    result['diagnostic_errors'].append(repr(exc))
            except Exception as exc:
                result['diagnostic_errors'].append(repr(exc))
        try:
            logs = engine.run([*prefix, 'logs', '--no-color', '--timestamps', '--tail', '200'], check=False)
            (folder / 'compose.log').write_text(logs.stdout + logs.stderr, encoding='utf-8')
        except Exception as exc:
            result['diagnostic_errors'].append(repr(exc))
        for command in [['docker', 'rm', '--force', checkout_generator, ad_generator],
                        [*prefix, 'down', '--volumes', '--remove-orphans']]:
            try:
                engine.run(command, check=False)
            except Exception as exc:
                result['diagnostic_errors'].append(repr(exc))
        events.terminate()
        try:
            events.wait(timeout=5)
        except subprocess.TimeoutExpired:
            events.kill(); events.wait(timeout=5)
        events_file.close(); events_error.close()
        write_json(folder / 'history-result.json', result)
        for name in ['resource-samples.jsonl', 'docker-events.jsonl']:
            path = folder / name
            if path.exists():
                with path.open('rb') as source, gzip.open(folder / (name + '.gz'), 'wb') as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
                path.unlink()
    return result


def execute(upstream: Path, bid: str, output: Path, smoke: bool = False) -> int:
    verification = verify(upstream, check_runner=True)
    design, runtime = load(ROOT / DESIGN), load(ROOT / RUNTIME)
    inherited = load(ROOT / runtime['parent_runtime'])
    inherited['workload'].update(runtime['workload'])
    parent = load(ROOT / inherited['parent_runtime'])
    output.mkdir(parents=True, exist_ok=False)
    images = sorted({*parent['images'].values(), parent['workload']['k6_image']})
    for image in images:
        engine.run(['docker', 'pull', image])
    write_json(output / 'image-inspect.json', json.loads(engine.run(['docker', 'image', 'inspect', *images]).stdout))
    write_json(output / 'rendered-compose.json', json.loads(engine.run([
        *compose_prefix(upstream, 'migration-render'), 'config', '--no-path-resolution', '--format', 'json']).stdout))
    row = {'block_id': 'smoke', 'order': ['control']} if smoke else next(r for r in matrix(design) if r['block_id'] == bid)
    histories = {policy: history(upstream, parent, inherited, design, runtime, row['block_id'], policy,
                                 output / policy, smoke) for policy in row['order']}
    write_json(output / 'block-result.json', {'study_version': VERSION, **row, 'histories': histories,
               'repository_commit': os.environ['GITHUB_SHA'], 'workflow_run_id': os.environ['GITHUB_RUN_ID'],
               'verification': verification, 'runner_image': os.getenv('ImageOS'),
               'runner_image_version': os.getenv('ImageVersion')})
    if smoke:
        h = histories['control']
        return 0 if (h['baseline_valid'] and len(h['epochs']) == 1 and h['epochs'][0]['valid']
                     and h['epochs'][0]['checkout']['safe']
                     and h['epochs'][0]['advertising']['goodput_per_second'] > 0
                     and (h['epochs'][0]['advertising']['throttled_period_fraction_mean'] or 0) > 0
                     and not h['epochs'][0]['system_failures']) else 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['verify', 'matrix', 'run'])
    parser.add_argument('--upstream-dir', type=Path)
    parser.add_argument('--block-id')
    parser.add_argument('--artifact-dir', type=Path)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    if args.command == 'run':
        return execute(args.upstream_dir.resolve(), args.block_id, args.artifact_dir.resolve(), args.smoke)
    report = verify(args.upstream_dir.resolve() if args.upstream_dir else None)
    print(json.dumps({'include': matrix(load(ROOT / DESIGN))} if args.command == 'matrix' else report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
