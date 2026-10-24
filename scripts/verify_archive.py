"""Check the self-contained two-study artifact without starting workloads."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SUITES = ['evolving-state/tests', 'drift-monitor/tests', 'runtime/tests', 'tests']
IGNORED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'artifacts',
           'upstream', 'confirmation-artifacts', 'protocol'}


def archive_paths(root: Path) -> list[Path]:
    if (root / '.git').exists():
        output = subprocess.check_output(
            ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
            cwd=root, text=True)
        return sorted({root / p for p in output.split('\0') if p and (root / p).is_file()})
    return sorted(p for p in root.rglob('*') if p.is_file()
                  and not (set(p.relative_to(root).parts) & IGNORED)
                  and p.relative_to(root).parts[0] != 'results')


def sha256_lf(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha256(data if path.suffix in {'.gz', '.png'} else data.replace(b'\r\n', b'\n')).hexdigest()


def verify_checksums(root: Path) -> int:
    recorded = {}
    for line in (root / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        expected, relative = line.split('  ', 1)
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or relative in recorded:
            raise ValueError('Invalid or duplicate checksum path')
        if sha256_lf(path) != expected:
            raise ValueError(f'Checksum mismatch: {relative}')
        recorded[relative] = expected
    actual = {p.relative_to(root).as_posix() for p in archive_paths(root)
              if p.relative_to(root).as_posix() not in {'SHA256SUMS', 'LICENSE'}}
    if set(recorded) != actual:
        raise ValueError(f'Manifest coverage mismatch: {sorted(set(recorded) ^ actual)}')
    return len(recorded)


def verify_links(root: Path) -> int:
    count = 0
    for path in archive_paths(root):
        if path.suffix != '.md':
            continue
        for target in re.findall(r'\]\(([^\s)]+)\)', path.read_text(encoding='utf-8')):
            if target.startswith(('http:', 'https:', 'mailto:', '#')):
                continue
            destination = (path.parent / unquote(target.split('#', 1)[0])).resolve()
            if not destination.is_relative_to(root.resolve()) or not destination.exists():
                raise ValueError(f'Broken local link in {path.relative_to(root)}: {target}')
            count += 1
    return count


def verify_scope(root: Path) -> None:
    allowed = {'.gitattributes', '.gitignore', '.github', 'LICENSE', 'README.md',
               'REPRODUCING.md', 'RESULTS.md', 'SHA256SUMS', 'requirements.txt',
               'scripts', 'tests', 'runtime', 'evolving-state', 'drift-monitor'}
    forbidden_suffixes = {'.pdf', '.tex', '.bib', '.docx', '.pptx'}
    for path in archive_paths(root):
        relative = path.relative_to(root)
        if relative.parts[0] not in allowed or path.suffix.lower() in forbidden_suffixes:
            raise ValueError(f'Out-of-scope file: {relative}')
        data = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
        if path.suffix == '.png':
            continue
        text = data.decode('utf-8')
        if any(0x400 <= ord(c) <= 0x4ff for c in text) or re.search(r'\\u' + r'04[0-9a-f]{2}', text, re.I):
            raise ValueError(f'Non-English Cyrillic text: {relative}')
        if path.name != 'LICENSE' and (re.search(r'[A-Za-z]:\\Users\\', text)
                                        or '/home/runner/' + 'work/' in text
                                        or any(not address.endswith('@example.invalid') for address in
                                               re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', text))):
            raise ValueError(f'Personal path or email: {relative}')
        if re.search(r'github\.com/[^/\s]+/[^/\s]+/actions/(runs|artifacts)/', text):
            raise ValueError(f'Identity-bearing execution URL: {relative}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    files = verify_checksums(ROOT)
    links = verify_links(ROOT)
    verify_scope(ROOT)
    for suite in SUITES:
        subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', suite, '-v'],
                       cwd=ROOT, check=True)
    result = {'status': 'verified', 'checksummed_files': files, 'local_links': links,
              'test_suites': len(SUITES), 'saved_data_replay': 'verified',
              'runtime_started': False}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
