from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from pathlib import Path

from model import matrix, representation
from plot import figure

ROOT = Path(__file__).resolve().parents[2]
DESIGN = "probe7/design-v0.2.0.json"
ANALYSIS_VERSION = "guarded-retrieval-0.1.1"
METHODS = ("selected_log_ratios", "euclidean_share_change", "full_ilr_change")
PROCESSES = ("checkout", "advertising", "accounting")
RAW_METRICS = {"checkout_p95_ms":("checkout","p95_ms"),
               "checkout_error_fraction":("checkout","error_rate"),
               "ad_timely_fraction":("advertising","timely_fraction"),
               "accounting_timely_fraction":("accounting","timely_fraction"),
               "accounting_observed_p99_lag_ms":("accounting","p99_observed_lag_ms")}
TOLERANCE = 1e-10


def difference(a, b):
    return [x-y for x,y in zip(a,b)]


def distance(a, b):
    return math.sqrt(math.fsum((x-y)**2 for x,y in zip(a,b)))


def rank(vectors):
    basis=[]
    for vector in vectors:
        residual=list(vector)
        for b in basis:
            dot=math.fsum(x*y for x,y in zip(residual,b))
            residual=[x-dot*y for x,y in zip(residual,b)]
        length=math.sqrt(math.fsum(x*x for x in residual))
        if length>1e-9:
            basis.append([x/length for x in residual])
    return len(basis)


def descriptors(previous, current, design):
    a,b=representation(previous,design),representation(current,design)
    return {
        "selected_log_ratios": difference(b["local"],a["local"]),
        "euclidean_share_change": difference(b["shares"]["cpu"]+b["shares"]["memory"],
                                              a["shares"]["cpu"]+a["shares"]["memory"]),
        "full_ilr_change": difference(b["ilr"],a["ilr"]),
    }


def sections(blocks: dict, design: dict) -> tuple[list[dict], list[dict]]:
    samples, omitted=[],[]
    for bid,block in sorted(blocks.items()):
        for policy,history in block["histories"].items():
            observations=sorted(history["observations"],key=lambda w:w["epoch"])
            for previous,current in zip(observations,observations[1:]):
                if current["epoch"]!=previous["epoch"]+1:
                    omitted.append({"block_id":bid,"policy":policy,"epoch":current["epoch"],"reason":"nonconsecutive_windows"})
                    continue
                if not previous["valid"] or not current["valid"]:
                    omitted.append({"block_id":bid,"policy":policy,"epoch":current["epoch"],"reason":"technical_invalid_window"})
                    continue
                if any(previous["headroom"][p] is None or current["headroom"][p] is None for p in PROCESSES):
                    omitted.append({"block_id":bid,"policy":policy,"epoch":current["epoch"],"reason":"undefined_headroom"})
                    continue
                features=descriptors(previous["allocation"],current["allocation"],design)
                full_energy=math.fsum(v*v for v in features["full_ilr_change"])
                if full_energy<TOLERANCE**2:
                    continue
                local_energy=math.fsum(v*v for v in features["selected_log_ratios"])
                samples.append({"block_id":bid,"policy":policy,"epoch":current["epoch"],
                    "profile":block["profile"],"initial_state":block["initial_state"],
                    "window_lengths_ms":[round(previous["window_end_ms"]-previous["window_start_ms"]),
                                         round(current["window_end_ms"]-current["window_start_ms"])],
                    "features":features,
                    "outcome_change":[current["headroom"][p]-previous["headroom"][p] for p in PROCESSES],
                    "hidden_energy_fraction":max(0.,1-local_energy/full_energy),
                    "safe":current["safe"]})
    return samples,omitted


def analogs(samples: list[dict]) -> list[dict]:
    records=[]
    for query in samples:
        candidates=[s for s in samples if s["block_id"]!=query["block_id"] and s["profile"]==query["profile"]
                    and s.get("window_lengths_ms")==query.get("window_lengths_ms")]
        if not candidates:
            continue
        for method in METHODS:
            distances=[distance(query["features"][method],c["features"][method]) for c in candidates]
            smallest=min(distances)
            tied=[c for c,d in zip(candidates,distances) if d<=smallest+TOLERANCE]
            by_pair={}
            for c in tied:
                by_pair.setdefault(c["block_id"],[]).append(c["outcome_change"])
            pair_predictions=[[statistics.mean(v[i] for v in vectors) for i in range(len(PROCESSES))]
                              for vectors in by_pair.values()]
            prediction=[statistics.mean(v[i] for v in pair_predictions) for i in range(len(PROCESSES))]
            selected=min(tied,key=lambda c:(c["block_id"],c["policy"],c["epoch"]))
            errors=[abs(a-b) for a,b in zip(query["outcome_change"],prediction)]
            row={"query_block":query["block_id"],"query_policy":query["policy"],"query_epoch":query["epoch"],
                 "profile":query["profile"],"method":method,"neighbor_block":selected["block_id"],
                 "neighbor_policy":selected["policy"],"neighbor_epoch":selected["epoch"],
                 "feature_distance":smallest,"equidistant_sections":len(tied),
                 "equidistant_pairs":len(by_pair),
                 "neighbor_sections":json.dumps([(c["block_id"],c["policy"],c["epoch"]) for c in tied]),
                 "mean_absolute_headroom_error":statistics.mean(errors)}
            row.update({p+"_absolute_error":v for p,v in zip(PROCESSES,errors)})
            row.update({p+"_predicted_change":v for p,v in zip(PROCESSES,prediction)})
            records.append(row)
    return records


def bootstrap_mean(values, seed=20261013, repetitions=2000):
    if len(values)<2:
        return None
    rng=random.Random(seed)
    draws=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(repetitions))
    return [draws[int(.025*(repetitions-1))],draws[int(.975*(repetitions-1))]]


def pair_contrasts(blocks):
    rows=[]
    for bid,block in sorted(blocks.items()):
        hs=block["histories"]
        if not all(p in hs and hs[p]["observations"] for p in ("adaptive","control")):
            continue
        indexed={p:{w["epoch"]:w for w in hs[p]["observations"]} for p in hs}
        baseline={p:indexed[p].get(0) for p in ("adaptive","control")}
        if not all(baseline.values()):
            continue
        for epoch in sorted(set(indexed["adaptive"])&set(indexed["control"])):
            a,c=indexed["adaptive"][epoch],indexed["control"][epoch]
            row={"block_id":bid,"epoch":epoch,"profile":block["profile"],"initial_state":block["initial_state"],
                 "valid_pair":a["valid"] and c["valid"],"adaptive_safe":a["safe"],"control_safe":c["safe"],
                 "goodput_change_difference":(a["advertising"]["goodput"]-baseline["adaptive"]["advertising"]["goodput"])-
                    (c["advertising"]["goodput"]-baseline["control"]["advertising"]["goodput"])}
            for p in PROCESSES:
                values=[a["headroom"][p],baseline["adaptive"]["headroom"][p],
                        c["headroom"][p],baseline["control"]["headroom"][p]]
                row[p+"_headroom_change_difference"]=None if any(v is None for v in values) else values[0]-values[1]-values[2]+values[3]
            for name,(process,metric) in RAW_METRICS.items():
                values=[w[process].get(metric) for w in (a,baseline["adaptive"],c,baseline["control"])]
                row[name+"_change_difference"]=None if any(v is None for v in values) else values[0]-values[1]-values[2]+values[3]
            rows.append(row)
    return rows


def projection_witnesses(blocks):
    groups={}
    for bid,block in sorted(blocks.items()):
        for w in block["histories"].get("adaptive",{}).get("observations",[]):
            if not w["valid"]:
                continue
            key=(block["initial_state"],block["profile"],tuple(round(v,10) for v in w["representation"]["local"]))
            groups.setdefault(key,[]).append((bid,w))
    rows=[]
    for group in groups.values():
        for uid,u in group:
            if u["safe"] is not False:
                continue
            for sid,s in group:
                if s["safe"] is not True or uid==sid or u["allocation"]==s["allocation"]:
                    continue
                local=distance(u["representation"]["local"],s["representation"]["local"])
                if local>TOLERANCE:
                    continue
                rows.append({"unsafe_block":uid,"unsafe_epoch":u["epoch"],"safe_block":sid,"safe_epoch":s["epoch"],
                    "local_distance":local,"full_ilr_distance":distance(u["representation"]["ilr"],s["representation"]["ilr"]),
                    "unsafe_checkout_p95_ms":u["checkout"]["p95_ms"],"safe_checkout_p95_ms":s["checkout"]["p95_ms"],
                    "unsafe_accounting_timely_fraction":u["accounting"]["timely_fraction"],
                    "safe_accounting_timely_fraction":s["accounting"]["timely_fraction"]})
    return rows


def summarize(blocks, design):
    planned={r["block_id"] for r in matrix(design)}
    if set(blocks)-planned:
        raise ValueError("Unexpected block ID")
    if any(b.get("mode")!="main" for b in blocks.values()):
        raise ValueError("Engineering observations must not enter main aggregation")
    if any(b["design"]!=design for b in blocks.values()):
        raise ValueError("Recorded design differs from the analysis definition")
    samples,omitted=sections(blocks,design)
    neighbors=analogs(samples)
    pair_rows=pair_contrasts(blocks)
    pair_errors={}
    for row in neighbors:
        pair_errors.setdefault(row["query_block"],{}).setdefault(row["method"],[]).append(row["mean_absolute_headroom_error"])
    means={bid:{m:statistics.mean(values) for m,values in methods.items()} for bid,methods in pair_errors.items()}
    retrieval={}
    for method in METHODS:
        values=[m[method] for m in means.values() if method in m]
        retrieval[method]={"query_pairs":len(values),"macro_pair_mean_absolute_error":statistics.mean(values) if values else None,
                           "bootstrap_pair_mean_95":bootstrap_mean(values)}
        retrieval[method]["per_process_macro_pair_error"]={}
        for process in PROCESSES:
            by_pair={}
            for row in neighbors:
                if row["method"]==method:
                    by_pair.setdefault(row["query_block"],[]).append(row[process+"_absolute_error"])
            process_means=[statistics.mean(v) for v in by_pair.values()]
            retrieval[method]["per_process_macro_pair_error"][process]=statistics.mean(process_means) if process_means else None
    advantages=[m["euclidean_share_change"]-m["full_ilr_change"] for m in means.values()
                if "euclidean_share_change" in m and "full_ilr_change" in m]
    transfers=[t for b in blocks.values() for h in b["histories"].values() for t in h["transitions"]
               if t["action"] and not t["action"].get("restore")]
    endings=[r for r in pair_rows if r["epoch"]==design["cycles"] and r["valid_pair"]]
    initially_paired={bid:b for bid,b in blocks.items()
                      if all(b["histories"].get(p,{}).get("baseline_valid",False) for p in ("adaptive","control"))}
    all_windows=[w for b in blocks.values() for h in b["histories"].values() for w in h["observations"]]
    summary={
        "analysis_version":ANALYSIS_VERSION,
        "status":"complete" if set(blocks)==planned else "incomplete",
        "planned_pairs":len(planned),"received_pairs":len(blocks),"missing_pairs":sorted(planned-set(blocks)),
        "initially_valid_pairs":sum(all(b["histories"].get(p,{}).get("baseline_valid",False) for p in ("adaptive","control")) for b in blocks.values()),
        "complete_cycle_pairs":len(endings),
        "measured_windows":len(all_windows),
        "technically_invalid_windows":sum(not w["valid"] for w in all_windows),
        "per_process_unsafe_windows":{p:sum(w[p]["safe"] is False for w in all_windows) for p in PROCESSES},
        "matched_histories_with_unsafe_windows":{p:sum(any(w["safe"] is False for w in b["histories"][p]["observations"])
                                                       for b in initially_paired.values()) for p in ("adaptive","control")},
        "matched_final_unsafe":{p:sum(r[p+"_safe"] is False for r in endings) for p in ("adaptive","control")},
        "histories_with_unsafe_windows":{p:sum(any(w["safe"] is False for w in b["histories"].get(p,{}).get("observations",[]))
                                                   for b in blocks.values()) for p in ("adaptive","control")},
        "proposed_transfers":len(transfers),"rolled_back_transfers":sum(t["rolled_back"] for t in transfers),
        "resource_transfer_counts":{r:sum(t["action"]["resource"]==r for t in transfers) for r in ("cpu","memory")},
        "observed_donors":sorted({t["action"]["donor"] for t in transfers}),
        "retrieval_sections":len(samples),"omitted_sections":omitted,
        "observed_ilr_displacement_linear_span":rank([s["features"]["full_ilr_change"] for s in samples]),
        "median_hidden_energy_fraction":statistics.median(s["hidden_energy_fraction"] for s in samples) if samples else None,
        "posthoc_projection_witness_comparisons":len(projection_witnesses(blocks)),
        "retrieval":retrieval,
        "raw_minus_ilr_pair_error":{"mean":statistics.mean(advantages) if advantages else None,
                                    "bootstrap_pair_mean_95":bootstrap_mean(advantages),
                                    "positive_pairs":sum(v>0 for v in advantages),"negative_pairs":sum(v<0 for v in advantages)},
        "final_step_goodput_change_difference_median":statistics.median(r["goodput_change_difference"] for r in endings) if endings else None,
        "scope":"Descriptive guarded adaptation and leave-one-pair-out analog retrieval; neither boundary crossing nor CoDA advantage defines success.",
    }
    summary["final_step_contrasts"]={}
    for metric in ["goodput"]+list(RAW_METRICS):
        values=[r[metric+"_change_difference"] for r in endings if r[metric+"_change_difference"] is not None]
        summary["final_step_contrasts"][metric]={"pairs":len(values),"median":statistics.median(values) if values else None,
                 "minimum":min(values) if values else None,"maximum":max(values) if values else None,
                 "positive_pairs":sum(v>0 for v in values),"negative_pairs":sum(v<0 for v in values)}
    return summary,samples,neighbors,pair_rows,means


def csv_save(path, rows):
    if not rows:
        path.write_text("",encoding="utf-8")
        return
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def save(output,blocks,design):
    summary,samples,neighbors,pairs,means=summarize(blocks,design)
    output.mkdir(parents=True,exist_ok=False)
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    (output/"block-level.json").write_text(json.dumps(blocks,indent=2)+"\n",encoding="utf-8")
    windows=[]
    for bid,b in sorted(blocks.items()):
        for policy,h in b["histories"].items():
            baseline=next((w for w in h["observations"] if w["epoch"]==0),None)
            for w in h["observations"]:
                r={"block_id":bid,"policy":policy,"profile":b["profile"],"initial_state":b["initial_state"],
                   "epoch":w["epoch"],"valid":w["valid"],"safe":w["safe"],
                   "checkout_p95_ms":w["checkout"]["p95_ms"],"checkout_error_fraction":w["checkout"]["error_rate"],
                   "ad_goodput":w["advertising"]["goodput"],"ad_timely_fraction":w["advertising"]["timely_fraction"],
                   "accounting_timely_fraction":w["accounting"]["timely_fraction"],
                   "accounting_missing":w["accounting"]["missing"],
                   "window_start_ms":w["window_start_ms"],"window_end_ms":w["window_end_ms"]}
                r.update({p+"_headroom":w["headroom"][p] for p in PROCESSES})
                r.update({resource+"_"+part:w["allocation"][resource][part] for resource in ("cpu","memory") for part in design["parts"]})
                r.update({"ilr_"+str(i+1):v for i,v in enumerate(w["representation"]["ilr"])})
                if baseline:
                    accumulated=descriptors(baseline["allocation"],w["allocation"],design)
                    r.update({method+"_from_baseline_norm":distance(values,[0]*len(values))
                              for method,values in accumulated.items()})
                windows.append(r)
    csv_save(output/"windows.csv",windows)
    csv_save(output/"paired-epochs.csv",pairs)
    csv_save(output/"neighbors.csv",neighbors)
    csv_save(output/"pair-retrieval-errors.csv",[{"block_id":bid,**m} for bid,m in sorted(means.items())])
    csv_save(output/"sections.csv",[{k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in s.items()} for s in samples])
    csv_save(output/"projection-witnesses.csv",projection_witnesses(blocks))
    example=design.get("example_pair","balanced-busy-01")
    (output/"example.svg").write_text(figure(blocks.get(example),example),encoding="utf-8")
    lines=["# Guarded adaptation: recorded results","",
           "Main observations only. Technical pilot data are never pooled.","",
           "![Prespecified paired history](example.svg)","",
           f'Received {summary["received_pairs"]}/{summary["planned_pairs"]} pairs; complete fixed-endpoint pairs: {summary["complete_cycle_pairs"]}.',
           f'Missing pairs: {summary["missing_pairs"]}.',
           f'Proposed transfers: {summary["proposed_transfers"]}; rollbacks: {summary["rolled_back_transfers"]}.',
           f'Resource counts: {summary["resource_transfer_counts"]}.',
           f'Observed donors: {summary["observed_donors"]}.',"",
           "## Fixed-endpoint trade-offs", "",
           "Contrasts subtract each history's baseline and then its matched unchanged control at cycle 20.",
           "They retain failed endpoints and are not chosen at a favorable or first-crossing step.", "",
           "| Metric | Pairs | Median adjusted change | Range | Positive / negative pairs |",
           "| --- | ---: | ---: | --- | --- |"]
    for metric,r in summary["final_step_contrasts"].items():
        lines.append(f'| {metric} | {r["pairs"]} | {r["median"]} | {r["minimum"]} to {r["maximum"]} | {r["positive_pairs"]} / {r["negative_pairs"]} |')
    lines.extend(["", "Accounting p99 lag is conditional on observed commits; its timely-fraction outcome retains missing orders.", "",
           "## Representation comparison","",
           "Each query excludes its complete runner pair; workload profile and both endpoint-window lengths match.",
           "Targets are nonzero consecutive observed reallocations. All methods use identical targets and candidates.",
           "Equidistant nearest sections are averaged within each neighboring pair, then equally across pairs.",
           "Error is the mean absolute difference between observed changes in the three normalized controller headrooms.",
           "These headrooms are descriptive policy signals, not a learned safe-region metric.","",
           "| Representation | Query pairs | Macro pair mean absolute error | Pair-bootstrap 95% interval |",
           "| --- | ---: | ---: | --- |"])
    for method,r in summary["retrieval"].items():
        lines.append(f'| {method} | {r["query_pairs"]} | {r["macro_pair_mean_absolute_error"]} | {r["bootstrap_pair_mean_95"]} |')
    lines.extend(["", "Individual processes are not interchangeable:", "",
                  "| Representation | Checkout error | Advertising error | Accounting error |",
                  "| --- | ---: | ---: | ---: |"])
    for method,r in summary["retrieval"].items():
        v=r["per_process_macro_pair_error"]
        lines.append(f'| {method} | {v["checkout"]} | {v["advertising"]} | {v["accounting"]} |')
    lines.extend(["",f'Raw-minus-ILR mean error: {summary["raw_minus_ilr_pair_error"]}.',
                  "Positive means lower ILR error; negative means lower raw-share error. Neither is required.",
                  "",f'Observed ILR displacement linear span: {summary["observed_ilr_displacement_linear_span"]}/20.',
                  "Linear span is not intrinsic controller dimension or coverage of the full state space.",
                  f'Median displacement energy outside the three fixed local contrasts: {summary["median_hidden_energy_fraction"]}.',
                  "", "## Inference scope","",
                  "Closed configured ceilings are not reservations. Baseline-invalid and short histories remain visible.",
                  "All unsafe windows and rollbacks are retained. A successful guard may prevent every violation.",
                  "Full raw shares and full ILR retain the same allocation information; their similarity metrics differ.",
                  "Projection loss and downstream analog retrieval are separate questions.",
                  "Outcome similarity remains conditional on these loads, budgets, histories and controller.",
                  "Resampling uses runner pairs, never dependent windows as independent replications.",
                  "Intervals describe pair-resampling of the fixed retrieval results, conditional on this neighbor pool; they are not calibrated generalization guarantees.",
                  "Analysis 0.1.1 additionally matches the preceding-window duration: 60-to-30-second first transitions are not pooled with 30-to-30-second later transitions. This eligibility correction changes no runtime observations or controller decisions.",
                  "", "All windows: windows.csv. Every matched epoch: paired-epochs.csv.",
                  "All retrieved analogs and errors: neighbors.csv and pair-retrieval-errors.csv.",
                  "Complete readable block records and validity: block-level.json.", ""])
    (output/"RESULTS.md").write_text("\n".join(lines),encoding="utf-8")
    return summary


def main():
    parser=argparse.ArgumentParser()
    sources=parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--results-root",type=Path)
    sources.add_argument("--block-records",type=Path)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    blocks=json.loads(args.block_records.read_text()) if args.block_records else {}
    if args.results_root:
        for p in sorted(args.results_root.rglob("block.json")):
            block=json.loads(p.read_text())
            if block["block_id"] in blocks:
                raise ValueError("Duplicate block")
            blocks[block["block_id"]]=block
    summary=save(args.output_dir,blocks,json.loads((ROOT/DESIGN).read_text()))
    print(json.dumps({k:summary[k] for k in ("status","received_pairs","complete_cycle_pairs")}))


if __name__=="__main__":
    main()
