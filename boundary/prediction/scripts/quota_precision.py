"""Standalone actuator check on disposable hosted runners; no workload or model."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
POINTS = ['0.126', '0.144', '0.129', '0.086', '0.128']


def command(args, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=120)
    if check and result.returncode:
        raise RuntimeError(f'Command failed: {args}: {result.stderr[-2000:]}')
    return result


def save(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def hosted_only():
    if os.getenv('GITHUB_ACTIONS') != 'true' or os.getenv('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('This check is restricted to disposable GitHub-hosted runners')


def configure(output):
    hosted_only()
    if command(['docker', 'ps', '-aq']).stdout.strip():
        raise RuntimeError('Refusing to change driver while containers exist')
    target = Path('/etc/docker/daemon.json')
    original = target.read_bytes() if target.exists() else None
    before = json.loads(original) if original else {}
    after = dict(before)
    after['exec-opts'] = [v for v in before.get('exec-opts', []) if not v.startswith('native.cgroupdriver=')]
    after['exec-opts'].append('native.cgroupdriver=cgroupfs')
    output.mkdir(parents=True, exist_ok=True)
    save(output/'daemon-config-before.json', before)
    save(output/'daemon-config-after.json', after)
    try:
        save(target, after)
        command(['systemctl', 'restart', 'docker'])
        info = json.loads(command(['docker', 'info', '--format', '{{json .}}']).stdout)
        if info['CgroupDriver'] != 'cgroupfs':
            raise RuntimeError('Requested cgroup driver was not applied')
    except Exception:
        if original is not None:
            target.write_bytes(original)
        else:
            target.unlink(missing_ok=True)
        command(['systemctl', 'restart', 'docker'], check=False)
        raise


def probe(output, dense=False, require_match=False):
    hosted_only()
    output.mkdir(parents=True, exist_ok=True)
    info = json.loads(command(['docker', 'info', '--format', '{{json .}}']).stdout)
    if require_match and info['CgroupDriver'] != 'cgroupfs':
        raise RuntimeError('Exact-grid check requires cgroupfs')
    runtime = json.loads((ROOT/'probe1/runtime.json').read_text(encoding='utf-8'))
    image = runtime['workload']['k6_image']
    names = [f'quota-precision-{os.environ["GITHUB_RUN_ID"]}-{s}' for s in ['checkout', 'ad']]
    report = {'driver': info['CgroupDriver'], 'cgroup_version': info['CgroupVersion'],
              'docker_version': json.loads(command(['docker','version','--format','{{json .}}']).stdout),
              'period_us': 100000, 'quantum_cpu': .001, 'checks': [], 'all_match': False}
    save(output/'host-info.json', info)
    created = []
    try:
        for name, quota in zip(names, ['0.300', '0.400']):
            command(['docker','run','-d','--name',name,'--network','none','--cpus',quota,
                     '--memory','64m','--memory-swap','64m','--entrypoint','/bin/sh',image,'-c','sleep 900'])
            created.append(name)
        quotas = [format(Decimal(i)/1000, '.3f') for i in range(300,79,-1)] if dense else POINTS
        for index, q in enumerate(quotas):
            requested = [q, format(Decimal('.700')-Decimal(q), '.3f')]
            for name, value in zip(names, requested):
                command(['docker','update','--cpus',value,name])
                if q in POINTS:
                    command(['docker','update','--memory','64m','--memory-swap','64m',name])
            inspected = json.loads(command(['docker','inspect',*names]).stdout)
            rows=[]
            for item, value in zip(inspected,requested):
                cpu_max=command(['docker','exec',item['Name'].lstrip('/'),'cat','/sys/fs/cgroup/cpu.max']).stdout.strip()
                actual, period = cpu_max.split()
                expected = int(Decimal(value)*100000)
                configured = item['HostConfig']['NanoCpus']
                matched = actual != 'max' and int(period)==100000 and int(actual)==expected and configured==int(Decimal(value)*10**9)
                rows.append({'requested_cpu':value,'configured_nano_cpus':configured,'cpu_max':cpu_max,'matches':matched})
            report['checks'].append({'checkout_cpu':q,'rows':rows,'matches':all(r['matches'] for r in rows)})
            save(output/'quota-precision.json',report)
            if index%50==0:
                print(json.dumps({'driver':report['driver'],'pairs_checked':index+1,'latest_match':report['checks'][-1]['matches']}),flush=True)
            if require_match and not report['checks'][-1]['matches']:
                raise RuntimeError('Effective CPU limit differs from the requested thousandth')
        report['all_match']=all(r['matches'] for r in report['checks'])
    finally:
        for name in created:
            command(['docker','rm','-f',name],check=False)
        save(output/'quota-precision.json',report)
    print(json.dumps({'driver':report['driver'],'pairs':len(report['checks']),'all_match':report['all_match']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['configure','probe','describe'])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--dense',action='store_true')
    parser.add_argument('--require-match',action='store_true')
    args=parser.parse_args()
    if args.mode=='describe':
        assert len(range(300,79,-1))==221
        for i in range(80,301):
            q=Decimal(i)/1000
            assert q+Decimal('.700')-q==Decimal('.700')
            assert int(q*100000)==i*100
        print(json.dumps({'pairs':221,'checkout_range_cpu':[.08,.30],'step_cpu':.001,'period_us':100000}))
    elif args.mode=='configure':
        configure(args.output.resolve())
    else:
        probe(args.output.resolve(),args.dense,args.require_match)
