"""Select the original cgroupfs actuator on an empty disposable hosted runner."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    configure(parser.parse_args().output)
