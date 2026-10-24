"""Read-only checks of relocated runtime support and pinned upstream inputs."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def verify(upstream=None):
    provenance = json.loads((ROOT/'runtime/relocation-provenance.json').read_text(encoding='utf-8'))
    for relative, row in provenance['runtime_files'].items():
        if row['operation'] == 'exact LF copy' and digest(ROOT/relative) != row['source_sha256_lf']:
            raise ValueError('Relocated source differs: '+relative)
    for label, row in provenance['extracted_functions'].items():
        relative, name = label.split(':')
        tree = ast.parse((ROOT/relative).read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        actual = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        if actual != row['ast_sha256']:
            raise ValueError('Extracted runtime function differs: '+label)
    base = json.loads((ROOT/'runtime/base-lock.json').read_text(encoding='utf-8'))
    cpu = json.loads((ROOT/'runtime/cpu-lock.json').read_text(encoding='utf-8'))
    images = [*base['images'].values(), *cpu['additional_images'].values(), base['workload']['k6_image']]
    if not all(re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', value) for value in images):
        raise ValueError('Unpinned image')
    if not set(base['mandatory_healthy_containers']) <= set(base['required_running_containers']):
        raise ValueError('Inconsistent health inventory')
    if base['source']['commit'] != cpu['upstream_commit']:
        raise ValueError('Upstream source mismatch')
    if upstream is not None:
        upstream = upstream.resolve()
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=upstream, text=True).strip()
        if commit != base['source']['commit']:
            raise ValueError('Wrong upstream checkout')
        for relative, expected in base['source']['files'].items():
            if digest(upstream/relative) != expected:
                raise ValueError('Upstream file differs: '+relative)
    return {'status':'verified', 'exact_copies':4, 'extracted_functions':len(provenance['extracted_functions']),
            'pinned_images':len(images), 'upstream_checked':upstream is not None, 'runtime_started':False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream-dir', type=Path)
    print(json.dumps(verify(parser.parse_args().upstream_dir)))
