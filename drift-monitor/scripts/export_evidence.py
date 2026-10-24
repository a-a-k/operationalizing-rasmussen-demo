"""Package original CPU records with their frozen model and selection ledger."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re


def export(attempt_sources, background_source, frozen_model, selection, ledger, output):
    output.mkdir(parents=True, exist_ok=False)
    inputs=output/'inputs'
    inputs.mkdir()
    provenance=[]
    frozen=json.loads(frozen_model.read_text(encoding='utf-8'))
    def clean(value):
        if isinstance(value,dict): return {k:clean(v) for k,v in value.items()}
        if isinstance(value,list): return [clean(v) for v in value]
        if isinstance(value,str):
            return re.sub(r'/home/runner/' + r'work/[^/\s]+/[^/\s]+/', '<workspace>/', value)
        return value
    def stream(paths,target,has_model):
        data=[]
        for path in paths:
            raw=path.read_bytes()
            row=json.loads(raw)
            if has_model and row.pop('frozen_model',None) != frozen:
                raise ValueError('A recorded test used a different frozen model')
            provenance.append({'file':path.name,'source_sha256':hashlib.sha256(raw).hexdigest()})
            data.append(json.dumps(clean(row),separators=(',',':'),allow_nan=False)+'\n')
        (inputs/target).write_bytes(gzip.compress(''.join(data).encode(),mtime=0))
        return len(data)
    attempts=[p for source in attempt_sources for p in sorted(source.glob('*.json'))]
    count=stream(attempts,'attempts.jsonl.gz',True)
    backgrounds=stream(sorted(background_source.glob('*.json')),'backgrounds.jsonl.gz',False)
    if count != 273 or backgrounds != 20:
        raise ValueError('Incomplete executed campaign')
    (inputs/'frozen-model.json').write_bytes(frozen_model.read_bytes())
    (inputs/'selected-cases.csv').write_bytes(selection.read_bytes())
    (inputs/'attempt-ledger.csv').write_bytes(ledger.read_bytes())
    (output/'provenance.json').write_text(json.dumps({
        'source_records':provenance,'attempt_records':count,'background_records':backgrounds,
        'frozen_model_sha256_lf':hashlib.sha256(frozen_model.read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
        'export':'Repeated frozen model omitted from each test record; original model retained once. Host workspace prefixes redacted in textual errors only. Measurements, configurations, online scores, qualification and attempt identity retained.',
        'runtime_started':False},indent=2)+'\n',encoding='utf-8',newline='\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--attempt-source',type=Path,action='append',required=True)
    p.add_argument('--background-source',type=Path,required=True)
    p.add_argument('--frozen-model',type=Path,required=True)
    p.add_argument('--selection',type=Path,required=True)
    p.add_argument('--ledger',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    export(a.attempt_source,a.background_source,a.frozen_model,a.selection,a.ledger,a.output)
    print(json.dumps({'attempts':273,'backgrounds':20,'runtime_started':False}))
