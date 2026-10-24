"""Two log-odds histories reproduce policy directions and first constraints."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path

from analyze import lines, oracle, save
from observer import GROUPS

MODULE = Path(__file__).resolve().parents[1]
EPS = 1e-12


class ReducedHistory:
    def __init__(self, alpha=.2):
        self.alpha, self.previous, self.smoothed = alpha, None, None

    def update(self, window, odds):
        result = None
        if odds is not None:
            step = None
            old = self.previous
            if old and old['odds'] is not None and old['window'] == window:
                step = old['result']['increment']
            elif old and old['odds'] is not None and old['window'] + 1 == window:
                step = [a-b for a,b in zip(odds,old['odds'])]
                self.smoothed = [self.alpha*a + (1-self.alpha)*b
                                 for a,b in zip(step,self.smoothed or [0.,0.])]
            else:
                self.smoothed = None
            result = {'increment': step, 'smoothed_increment': self.smoothed}
        else:
            self.smoothed = None
        self.previous = {'window': window, 'odds': odds, 'result': result}
        return result


def diagnose(odds, velocity, limits):
    directions, contacts, violated = {}, {}, []
    for group,q,v in zip(GROUPS,odds,velocity):
        gap = math.log(limits[group]/(1-limits[group])) - q
        directions[group] = 'toward' if v > EPS else 'away' if v < -EPS else 'tangent'
        if gap < -EPS:
            violated.append(group)
        elif v > EPS:
            contacts[group] = max(0.,gap)/v
    first = []
    if contacts and not violated:
        contact = min(contacts.values())
        first = [g for g,s in contacts.items() if math.isclose(s,contact,abs_tol=1e-9,rel_tol=1e-9)]
    return {'directions': directions, 'first_constraints': first, 'currently_violated': violated}


def analyze(bundle):
    expected = json.loads((bundle/'directional-v0.1.0/reports.json').read_text())
    lookup = {(r['history'],r['report_index']):r for r in expected}
    checks = []
    unavailable = Counter()
    for directory in sorted((bundle/'inputs').glob('history-*')):
        cfg = json.loads((directory/'load-config.json').read_text())
        state = ReducedHistory(cfg['ewma_alpha'])
        events = lines(directory/'journals/client.jsonl')
        for index,item in enumerate(lines(directory/'observer-inputs.jsonl')):
            target = lookup[directory.name,index]
            truth = oracle(events,item['snapshot'],cfg['origin_ms'],cfg['window_seconds']*1000)
            available = target['geometry_status'] == 'available'
            odds = [math.log(truth['groups'][g]['retry']/truth['groups'][g]['first'])
                    for g in GROUPS] if available else None
            history = state.update(target['window'],odds)
            for source in ('increment','smoothed_increment'):
                reference = target['directions'][source]
                if reference['availability'] != 'available':
                    unavailable[reference['availability']] += 1
                    continue
                if history is None or history[source] is None:
                    raise ValueError('Reduced baseline lost a common-mask direction')
                actual = diagnose(odds,history[source],{g:truth['groups'][g]['rho'] for g in GROUPS})
                original = reference['ilr']
                if (actual['directions'] != {g:original['groups'][g]['direction'] for g in GROUPS}
                        or actual['first_constraints'] != original['first_constraints']
                        or actual['currently_violated'] != original['currently_violated']):
                    raise ValueError('Reduced log-odds and full-state policy diagnoses disagree')
                checks.append({'history':directory.name,'report_index':index,'window':target['window'],
                               'policy_version':target['policy_version'],'source':source,**actual})
    return {'histories':len({r['history'] for r in checks}),'comparisons':len(checks),
            'orientation_disagreements':0,'first_constraint_disagreements':0,
            'unavailable_direction_reports':dict(unavailable),
            'common_availability_mask':True,'dimensions':2,
            'distance_comparison':'Not claimed: the two coordinates omit the full-state Aitchison norm',
            'runtime_started':False}, checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,default=MODULE/'results/campaign-v0.1.1')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    summary,checks=analyze(args.bundle)
    save(args.output/'summary.json',summary)
    save(args.output/'comparisons.json',checks)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
