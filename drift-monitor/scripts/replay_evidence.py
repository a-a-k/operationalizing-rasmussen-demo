"""Reproduce both reported CPU threshold rows from original measured histories."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path
import numpy as np

from monitor_core import DESIGN, METHODS, Observer, digest, fit_background, load, save

MODULE=Path(__file__).resolve().parents[1]


def stream(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def score(history,frozen,factor=1.):
    observer=Observer(frozen,history['reference']['cpu'])
    first={m:None for m in METHODS}
    errors=[]
    for row in history['observations']:
        values=observer.update(row['cpu'])
        for method in METHODS:
            online=row['online'][method]
            value=values[method]['score']
            if not np.isclose(value,online['score'],rtol=1e-10,atol=1e-9):
                raise ValueError('Original online score failed independent prefix replay')
            if values[method]['signal'] != online['signal']:
                raise ValueError('Original online decision failed prefix replay')
            errors.append(abs(value-online['score']))
            threshold=frozen['methods'][method]['threshold']*(factor if method=='ilr_composition' else 1.)
            if first[method] is None and value>threshold:
                first[method]=row['epoch']
    return first,max(errors,default=0.)


def analyze(bundle):
    inputs=bundle/'inputs'
    attempts=stream(inputs/'attempts.jsonl.gz')
    backgrounds=stream(inputs/'backgrounds.jsonl.gz')
    frozen=load(inputs/'frozen-model.json')
    with (inputs/'selected-cases.csv').open(encoding='utf-8',newline='') as f:
        selected_rows=list(csv.DictReader(f))
    with (inputs/'attempt-ledger.csv').open(encoding='utf-8',newline='') as f:
        ledger=list(csv.DictReader(f))
    if len(attempts)!=273 or len(backgrounds)!=20 or len(ledger)!=273 or len(selected_rows)!=250:
        raise ValueError('Executed evidence count mismatch')
    if digest(inputs/'frozen-model.json') != '0ed95159ba12d706d8c55d33532426e5105fc8c00ba0f5dd1ecb5b766504c4a7':
        raise ValueError('Frozen model differs from the executed model')
    recalculated=fit_background(backgrounds)
    for method in METHODS:
        for key in ('mean','covariance','threshold','calibration_maxima'):
            if not np.allclose(recalculated['methods'][method][key],frozen['methods'][method][key],rtol=1e-8,atol=1e-10):
                raise ValueError('Background fitting/calibration differs: '+method+'/'+key)
    if any(recalculated[key]!=frozen[key] for key in ('fit_ids','calibration_ids')):
        raise ValueError('Background membership changed')
    source_order={run:index for index,run in enumerate(dict.fromkeys(r['source_run'] for r in ledger))}
    attempts.sort(key=lambda r:(source_order[str(r['run_id'])],int(r['run_attempt']),r['block_id']))
    first_qualified={}
    for row in attempts:
        if all(row.get('histories',{}).get(p,{}).get('qualified',False) for p in ('drift','control')):
            first_qualified.setdefault(row['block_id'],row)
    if len(first_qualified)!=250:
        raise ValueError('Not all originally planned blocks have a first qualified record')
    for row in selected_rows:
        actual=first_qualified[row['block_id']]
        if str(actual['run_id'])!=row['source_run'] or str(actual['run_attempt'])!=row['source_attempt']:
            raise ValueError('Selected record is not the first qualified attempt')
    rows=[]
    maximum_error=0.
    for factor in (1.,1.10):
        leads=[]
        control_counts=Counter()
        detected=Counter()
        for bid,job in sorted(first_qualified.items()):
            scored={}
            for policy in ('drift','control'):
                scored[policy],error=score(job['histories'][policy],frozen,factor)
                maximum_error=max(maximum_error,error)
            delays={}
            for method in METHODS:
                epoch=scored['drift'][method]
                found=epoch is not None and epoch>=5
                detected[method]+=found
                delays[method]=epoch-4 if found else 12
                control_counts[method]+=scored['control'][method] is not None
            lead=delays['raw_composition']-delays['ilr_composition']
            leads.append(lead)
        rows.append({'ilr_threshold_factor':factor,'pairs':len(leads),'earlier':sum(v>0 for v in leads),
                     'tied':sum(v==0 for v in leads),'later':sum(v<0 for v in leads),
                     'mean_advance_cycles':sum(leads)/len(leads),'mean_advance_seconds':40*sum(leads)/len(leads),
                     'control_signals':dict(control_counts),'detected_drift_histories':dict(detected),
                     'retrospective_threshold_change':factor!=1.})
    return {'attempts':273,'qualified_pairs':250,'background_histories':20,
            'fit_histories':len(frozen['fit_ids']),'calibration_histories':len(frozen['calibration_ids']),
            'background_model_reproduced':True,'maximum_online_score_replay_error':maximum_error,
            'cycle_seconds':40,'restricted_delay_cycles':12,'pre_intervention_cycles':4,
            'selection':'First qualified original block attempt; no selection by detector outcome',
            'attempt_qualification':dict(Counter(str(all(r.get('histories',{}).get(p,{}).get('qualified',False)
                                                        for p in ('drift','control'))) for r in attempts)),
            'recorded_test_measurement_windows':sum(len(h.get('observations',[])) for r in attempts for h in r.get('histories',{}).values()),
            'rows':rows,'runtime_started':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path,default=MODULE/'results/campaign-v0.1.1')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    result=analyze(a.bundle)
    save(a.output/'summary.json',result)
    print(json.dumps(result,indent=2))
