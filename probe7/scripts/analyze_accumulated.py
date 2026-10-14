from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import random
import statistics
from pathlib import Path

from model import initial_state, matrix, representation
from accumulation_plot import history_figure, witness_figure

ROOT = Path(__file__).resolve().parents[2]
DEFINITION = "probe7/accumulated-analysis-v0.1.0.json"
POLICIES = ("adaptive", "control")
MARGINS = ("checkout_latency_margin_ms", "checkout_error_margin_pp", "advertising_timely_margin_pp",
           "accounting_timely_margin_pp", "accounting_observed_p99_margin_ms")


def norm(v):
    return math.sqrt(math.fsum(x*x for x in v))


def delta(a, b):
    if len(a) != len(b):
        raise ValueError("Coordinate dimensions differ")
    return [x-y for x,y in zip(a,b)]


def inverse(y):
    n=len(y)+1
    logs=[math.fsum((1 if i<k else -k if i==k else 0)*y[k-1]/math.sqrt(k*(k+1))
                    for k in range(1,n)) for i in range(n)]
    top=max(logs)
    values=[math.exp(v-top) for v in logs]
    return [v/math.fsum(values) for v in values]


def margins(w):
    c,a,l=w["checkout"],w["advertising"],w["accounting"]
    return {"checkout_latency_margin_ms":None if c["p95_ms"] is None else 500-c["p95_ms"],
            "checkout_error_margin_pp":100*(.01-c["error_rate"]),
            "advertising_timely_margin_pp":None if a["timely_fraction"] is None else 100*(a["timely_fraction"]-.99),
            "accounting_timely_margin_pp":None if l["timely_fraction"] is None else 100*(l["timely_fraction"]-.99),
            "accounting_observed_p99_margin_ms":None if l["p99_observed_lag_ms"] is None else 5000-l["p99_observed_lag_ms"]}


def read_csv(path):
    with path.open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f))


def load_inputs(root=ROOT):
    definition=json.loads((root/DEFINITION).read_text())
    for name,expected in definition["source_sha256_lf"].items():
        actual=hashlib.sha256((root/name).read_bytes().replace(b"\r\n",b"\n")).hexdigest()
        if actual!=expected:
            raise ValueError(f"Source hash differs: {name}")
    blocks=json.loads((root/definition["source_records"]).read_text())
    design=json.loads((root/definition["source_design"]).read_text())
    return blocks,design,definition


def analyze_histories(blocks, design, definition):
    planned={r["block_id"]:r for r in matrix(design)}
    if set(blocks)-set(planned):
        raise ValueError("Unexpected runner pair")
    tol=definition["numerical_tolerance"]
    parts=design["parts"]
    totals={"cpu":math.fsum(design["reference_cpu"]),"memory":sum(design["reference_memory_mib"])*2**20}
    rows,trajectories=[],[]
    errors={"inverse_shares_max":0.,"relative_identity_max":0.,"telescoping_max":0.}
    for bid,b in sorted(blocks.items()):
        if b["mode"]!="main" or b["design"]!=design:
            raise ValueError("Wrong source design or evidence class")
        for key in ("profile","initial_state","order","repetition"):
            if b[key]!=planned[bid][key]:
                raise ValueError(f"Recorded matrix differs: {bid}/{key}")
        for policy in POLICIES:
            h=b["histories"].get(policy)
            if not h or not h["observations"]:
                continue
            observations=sorted(h["observations"],key=lambda w:w["epoch"])
            if observations[0]["epoch"]!=0 or len({w["epoch"] for w in observations})!=len(observations):
                raise ValueError("Missing or duplicated baseline/epoch")
            base=observations[0]
            if base["allocation"]!=initial_state(design,b["initial_state"]):
                raise ValueError("Initial allocation differs")
            z0=representation(base["allocation"],design)
            transitions={t["epoch"]:t for t in h["transitions"]}
            previous=base
            applied=base["allocation"]
            observed_path=command_path=0.
            summed=[0.]*20
            consecutive=True
            history_rows=[]
            for w in observations:
                if not 0<=w["epoch"]<=definition["fixed_endpoint"]:
                    raise ValueError("Unexpected measurement epoch")
                for resource,total in totals.items():
                    if set(w["allocation"][resource])!=set(parts) or abs(math.fsum(w["allocation"][resource].values())-total)>1e-8:
                        raise ValueError("Positive closed budget differs")
                z=representation(w["allocation"],design)
                if norm(delta(z["ilr"],w["representation"]["ilr"]))>tol:
                    raise ValueError("Saved coordinates differ from allocations")
                for resource,offset in (("cpu",0),("memory",10)):
                    recovered=inverse(z["ilr"][offset:offset+10])
                    errors["inverse_shares_max"]=max(errors["inverse_shares_max"],
                                                     max(abs(x-y) for x,y in zip(recovered,z["shares"][resource])))
                cumulative=delta(z["ilr"],z0["ilr"])
                local=delta(z["local"],z0["local"])
                relative=representation({r:{p:w["allocation"][r][p]/base["allocation"][r][p] for p in parts}
                                         for r in ("cpu","memory")},design)["ilr"]
                errors["relative_identity_max"]=max(errors["relative_identity_max"],norm(delta(cumulative,relative)))
                if w["epoch"]:
                    consecutive=consecutive and w["epoch"]==previous["epoch"]+1
                    step=delta(z["ilr"],representation(previous["allocation"],design)["ilr"])
                    observed_path+=norm(step)
                    summed=[a+c for a,c in zip(summed,step)]
                    t=transitions.get(w["epoch"])
                    if not t or t["before"]!=applied or t["trial"]!=w["allocation"]:
                        raise ValueError("Command vertices differ from observed allocations")
                    before=representation(t["before"],design)["ilr"]
                    after=representation(t["next_allocation"],design)["ilr"]
                    command_path+=norm(delta(z["ilr"],before))
                    command_path_before_rollback=command_path
                    command_path+=norm(delta(after,z["ilr"]))
                    applied=t["next_allocation"]
                else:
                    command_path_before_rollback=0.
                if consecutive:
                    errors["telescoping_max"]=max(errors["telescoping_max"],norm(delta(summed,cumulative)))
                full_energy=math.fsum(v*v for v in cumulative)
                local_energy=math.fsum(v*v for v in local)
                if local_energy>full_energy+tol:
                    raise ValueError("Selected projection exceeds full displacement energy")
                hidden=max(0.,full_energy-local_energy)
                row={"block_id":bid,"policy":policy,"initial_state":b["initial_state"],"profile":b["profile"],
                     "epoch":w["epoch"],"valid":w["valid"],"safe":w["safe"],"baseline_safe":base["safe"],
                     "cpu_budget":totals["cpu"],"memory_budget_mib":totals["memory"]/2**20,
                     "window_start_ms":w["window_start_ms"],"window_end_ms":w["window_end_ms"],
                     "relative_net_norm":norm(cumulative),"local_projected_net_norm":norm(local),
                     "hidden_relative_norm":math.sqrt(hidden),
                     "hidden_energy_fraction":hidden/full_energy if full_energy>tol**2 else None,
                     "raw_share_net_norm":norm(delta(z["shares"]["cpu"]+z["shares"]["memory"],
                                                      z0["shares"]["cpu"]+z0["shares"]["memory"])),
                     "observed_vertex_path_length":observed_path if consecutive else None,
                     "command_vertex_path_before_rollback":command_path_before_rollback if consecutive else None,
                     "command_vertex_path_after_rollback":command_path if consecutive else None,
                     "checkout_p95_ms":w["checkout"]["p95_ms"],"checkout_error_fraction":w["checkout"]["error_rate"],
                     "advertising_goodput":w["advertising"]["goodput"],
                     "advertising_timely_fraction":w["advertising"]["timely_fraction"],
                     "accounting_timely_fraction":w["accounting"]["timely_fraction"],
                     "accounting_observed_p99_lag_ms":w["accounting"]["p99_observed_lag_ms"],**margins(w)}
                row.update({f"relative_delta_{i+1}":v for i,v in enumerate(cumulative)})
                row.update({f"local_delta_{i+1}":v for i,v in enumerate(local)})
                row.update({f"{r}_quota_factor_{p}":w["allocation"][r][p]/base["allocation"][r][p]
                            for r in ("cpu","memory") for p in parts})
                rows.append(row);history_rows.append(row);previous=w
            hidden_values=[r["hidden_energy_fraction"] for r in history_rows if r["hidden_energy_fraction"] is not None]
            last=history_rows[-1]
            trajectories.append({"block_id":bid,"policy":policy,"profile":b["profile"],"initial_state":b["initial_state"],
                "baseline_valid_and_safe":h["baseline_valid"],"windows":len(history_rows),"last_epoch":last["epoch"],
                "complete":last["epoch"]==definition["fixed_endpoint"] and consecutive,
                "unsafe_windows":sum(w["safe"] is False for w in observations),
                "median_cumulative_hidden_fraction":statistics.median(hidden_values) if hidden_values else None,
                "last_observed_relative_net_norm":last["relative_net_norm"],
                "last_applied_relative_net_norm":norm(delta(representation(applied,design)["ilr"],z0["ilr"])),
                "observed_vertex_path_length":last["observed_vertex_path_length"],
                "command_vertex_path_length":last["command_vertex_path_after_rollback"],
                "last_observed_safe":observations[-1]["safe"],
                "last_commanded_state_has_matching_slo_measurement":applied==observations[-1]["allocation"],
                "stop_reason":h["stop_reason"]})
    if any(value>tol for value in errors.values()):
        raise ValueError("Known geometry identity verification failed")
    return rows,trajectories,errors


def contrasts(rows, definition):
    by_pair={}
    for r in rows:
        by_pair.setdefault(r["block_id"],{}).setdefault(r["policy"],{})[r["epoch"]]=r
    result=[]
    for bid,policies in sorted(by_pair.items()):
        if not all(p in policies and 0 in policies[p] for p in POLICIES):
            continue
        bases={p:policies[p][0] for p in POLICIES}
        for epoch in sorted(set(policies["adaptive"])&set(policies["control"])):
            a,c=policies["adaptive"][epoch],policies["control"][epoch]
            row={"block_id":bid,"epoch":epoch,"initial_state":a["initial_state"],"profile":a["profile"],
                 "baseline_safe_pair":all(bases[p]["valid"] and bases[p]["safe"] for p in POLICIES),
                 "valid_pair":a["valid"] and c["valid"],"adaptive_safe":a["safe"],"control_safe":c["safe"],
                 "adaptive_relative_net_norm":a["relative_net_norm"],"control_relative_net_norm":c["relative_net_norm"],
                 "adaptive_local_projected_net_norm":a["local_projected_net_norm"]}
            for metric in ("advertising_goodput",)+MARGINS:
                values=[a[metric],bases["adaptive"][metric],c[metric],bases["control"][metric]]
                row[metric+"_adjusted_change"]=None if any(v is None for v in values) else values[0]-values[1]-values[2]+values[3]
            result.append(row)
    return result


def bootstrap_median(values, definition):
    if len(values)<2:
        return None
    rng=random.Random(definition["bootstrap_seed"])
    samples=sorted(statistics.median(rng.choices(values,k=len(values)))
                   for _ in range(definition["bootstrap_repetitions"]))
    return [samples[int(.025*(len(samples)-1))],samples[int(.975*(len(samples)-1))]]


def witnesses(blocks, design, definition):
    endpoints,prefixes=[],[]
    tol=definition["numerical_tolerance"]
    for (aid,a),(bid,b) in itertools.combinations(sorted(blocks.items()),2):
        if (a["initial_state"],a["profile"])!=(b["initial_state"],b["profile"]):
            continue
        ah=a["histories"].get("adaptive",{}).get("observations",[])
        bh=b["histories"].get("adaptive",{}).get("observations",[])
        if not ah or not bh or ah[0]["allocation"]!=bh[0]["allocation"]:
            continue
        def match(x,y,kind,maximum):
            if not x["valid"] or not y["valid"] or x["safe"]==y["safe"]:
                return None
            full=norm(delta(x["representation"]["ilr"],y["representation"]["ilr"]))
            local=norm(delta(x["representation"]["local"],y["representation"]["local"]))
            if full<=tol or local>tol:
                return None
            u,s=(x,y) if x["safe"] is False else (y,x)
            uid,sid=(aid,bid) if x["safe"] is False else (bid,aid)
            row={"comparison_class":kind,"initial_state":a["initial_state"],"profile":a["profile"],
                    "unsafe_block":uid,"unsafe_epoch":u["epoch"],"safe_block":sid,"safe_epoch":s["epoch"],
                    "local_distance":local,"full_relative_distance":full,"prefix_max_local_distance":maximum,
                    "unsafe_checkout_p95_ms":u["checkout"]["p95_ms"],"safe_checkout_p95_ms":s["checkout"]["p95_ms"],
                    "unsafe_accounting_timely_fraction":u["accounting"]["timely_fraction"],
                    "safe_accounting_timely_fraction":s["accounting"]["timely_fraction"]}
            for label,w in (("unsafe",u),("safe",s)):
                for part in ("checkout","frontend","ad","accounting","kafka","astronomy-db"):
                    row[label+"_cpu_"+part]=w["allocation"]["cpu"][part]
            return row
        for x in ah:
            for y in bh:
                item=match(x,y,"equal_local_endpoint",None)
                if item:endpoints.append(item)
        same=True; maximum=0.
        for epoch,(x,y) in enumerate(zip(ah,bh)):
            maximum=max(maximum,norm(delta(x["representation"]["local"],y["representation"]["local"])))
            same=same and x["epoch"]==y["epoch"]==epoch and x["valid"] and y["valid"] and maximum<=tol
            if same:
                item=match(x,y,"equal_entire_selected_prefix",maximum)
                if item:prefixes.append(item)
    return endpoints,prefixes


def transfer_examples(blocks, design, definition):
    real,checks=[],[]
    reference=blocks[definition["relative_check_reference"]]["histories"]["adaptive"]["observations"]
    factors={r:{p:reference[1]["allocation"][r][p]/reference[0]["allocation"][r][p] for p in design["parts"]}
             for r in ("cpu","memory")}
    expected_relative=representation(factors,design)["ilr"]
    for bid in definition["actual_transfer_examples"]:
        a,c=blocks[bid]["histories"]["adaptive"]["observations"][:2]
        action=c.get("action",{})
        if (action.get("resource"),action.get("donor"),action.get("receiver"),action.get("amount"))!=("cpu","accounting","ad",.04):
            raise ValueError("Fixed illustrative example is no longer the specified transfer")
        ra,rc=representation(a["allocation"],design),representation(c["allocation"],design)
        real.append({"block_id":bid,"epoch":c["epoch"],"evidence_class":"observed_runtime_transfer",
                     "accounting_cpu_before":a["allocation"]["cpu"]["accounting"],"accounting_cpu_after":c["allocation"]["cpu"]["accounting"],
                     "accounting_relative_change_percent":100*(c["allocation"]["cpu"]["accounting"]/a["allocation"]["cpu"]["accounting"]-1),
                     "ad_cpu_before":a["allocation"]["cpu"]["ad"],"ad_cpu_after":c["allocation"]["cpu"]["ad"],
                     "raw_share_displacement_norm":norm(delta(rc["shares"]["cpu"]+rc["shares"]["memory"],ra["shares"]["cpu"]+ra["shares"]["memory"])),
                     "relative_displacement_norm":norm(delta(rc["ilr"],ra["ilr"])),"observed_safe":c["safe"]})
        changed={}
        for r in ("cpu","memory"):
            weighted={p:a["allocation"][r][p]*factors[r][p] for p in design["parts"]}
            total=math.fsum(a["allocation"][r].values())
            changed[r]={p:v*total/math.fsum(weighted.values()) for p,v in weighted.items()}
        transformed=representation(changed,design)
        shift=delta(transformed["ilr"],ra["ilr"])
        checks.append({"initial_context":blocks[bid]["initial_state"],"source_block":bid,
                       "evidence_class":"unexecuted_geometry_check","slo_label":None,
                       "relative_displacement_norm":norm(shift),
                       "raw_share_displacement_norm":norm(delta(transformed["shares"]["cpu"]+transformed["shares"]["memory"],ra["shares"]["cpu"]+ra["shares"]["memory"])),
                       "relative_vector_error":norm(delta(shift,expected_relative)),
                       "cpu_relative_factors":json.dumps(factors["cpu"],sort_keys=True)})
    return real,checks


def secondary_diagnostics(root):
    folder=root/"probe7/results/main-v0.2.0"
    original=json.loads((folder/"summary.json").read_text())
    neighbors=read_csv(folder/"neighbors.csv")
    zeros={}
    for r in read_csv(folder/"sections.csv"):
        zeros.setdefault(r["block_id"],[]).append([abs(v) for v in json.loads(r["outcome_change"])])
    per=[statistics.mean(statistics.mean(v[i] for v in values) for values in zeros.values()) for i in range(3)]
    result=[{"method":"posthoc_no_headroom_change","macro_pair_mean_absolute_error":statistics.mean(per),
             "checkout_error":per[0],"advertising_error":per[1],"accounting_error":per[2],
             "median_nearest_pairs":None,"origin":"New diagnostic, not an executed detector"}]
    for method,data in original["retrieval"].items():
        matches=[r for r in neighbors if r["method"]==method]
        result.append({"method":method,"macro_pair_mean_absolute_error":data["macro_pair_mean_absolute_error"],
                       "checkout_error":data["per_process_macro_pair_error"]["checkout"],
                       "advertising_error":data["per_process_macro_pair_error"]["advertising"],
                       "accounting_error":data["per_process_macro_pair_error"]["accounting"],
                       "median_nearest_pairs":statistics.median(int(r["equidistant_pairs"]) for r in matches),
                       "origin":"Unchanged executed-series saved-data comparison"})
    return result


def analyze(root=ROOT):
    blocks,design,definition=load_inputs(root)
    rows,trajectories,errors=analyze_histories(blocks,design,definition)
    paired=contrasts(rows,definition)
    endings=[r for r in paired if r["epoch"]==definition["fixed_endpoint"] and r["baseline_safe_pair"] and r["valid_pair"]]
    endpoint_witnesses,prefix_witnesses=witnesses(blocks,design,definition)
    real,checks=transfer_examples(blocks,design,definition)
    diagnostics=secondary_diagnostics(root)
    adaptive=[r for r in trajectories if r["policy"]=="adaptive"]
    fractions=[r["median_cumulative_hidden_fraction"] for r in adaptive if r["median_cumulative_hidden_fraction"] is not None]
    summary={"version":definition["version"],"evidence_class":definition["evidence_class"],
             "source_sha256_lf":definition["source_sha256_lf"],"planned_pairs":len(matrix(design)),
             "received_pairs":len(blocks),"missing_pairs":sorted(set(r["block_id"] for r in matrix(design))-set(blocks)),
             "histories":len(trajectories),"windows":len(rows),"complete_paired_endpoints":len(endings),
             "geometry_verification":errors,"median_history_median_cumulative_hidden_fraction":statistics.median(fractions) if fractions else None,
             "endpoint_witness_comparisons":len(endpoint_witnesses),"entire_prefix_witness_comparisons":len(prefix_witnesses),
             "prefix_witness_unsafe_histories":sorted({r["unsafe_block"] for r in prefix_witnesses}),
             "ram_moving_histories":len({r["block_id"] for r in rows if r["policy"]=="adaptive"
                                         and any(r["memory_quota_factor_"+p]!=1 for p in design["parts"])}),
             "unknown_post_rollback_endpoint_slo":sum(not r["last_commanded_state_has_matching_slo_measurement"] for r in adaptive),
             "fixed_endpoint_contrasts":{},"secondary_diagnostics":diagnostics,
             "scope":definition["scope"]}
    for metric in ("advertising_goodput",)+MARGINS:
        values=[r[metric+"_adjusted_change"] for r in endings if r[metric+"_adjusted_change"] is not None]
        summary["fixed_endpoint_contrasts"][metric]={"pairs":len(values),"median":statistics.median(values) if values else None,
             "minimum":min(values) if values else None,"maximum":max(values) if values else None,
             "positive_pairs":sum(v>0 for v in values),"negative_pairs":sum(v<0 for v in values),
             "pair_bootstrap_median_95":bootstrap_median(values,definition)}
    return summary,rows,trajectories,paired,endpoint_witnesses,prefix_witnesses,real,checks,blocks,definition


def csv_save(path,rows):
    if not rows:
        path.write_text("",encoding="utf-8")
        return
    with path.open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)),lineterminator="\n")
        writer.writeheader();writer.writerows(rows)


def save(output,root=ROOT,commit="0000000000000000000000000000000000000000",run_id="0"):
    summary,rows,trajectories,paired,endpoints,prefixes,real,checks,blocks,definition=analyze(root)
    summary["analysis_execution"]={"commit":commit,"run_id":str(run_id),"runtime_started":False}
    output.mkdir(parents=True,exist_ok=False)
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    for name,data in (("history-windows.csv",rows),("trajectory-level.csv",trajectories),("paired-epochs.csv",paired),
                      ("endpoint-witnesses.csv",endpoints),("prefix-witnesses.csv",prefixes),
                      ("actual-transfer-examples.csv",real),("relative-update-checks.csv",checks),
                      ("secondary-diagnostics.csv",summary["secondary_diagnostics"])):
        csv_save(output/name,data)
    prefix_limits={}
    for r in prefixes:
        for kind in ("unsafe","safe"):
            bid=r[kind+"_block"]
            prefix_limits[bid]=max(prefix_limits.get(bid,0),r[kind+"_epoch"])
    witness_rows=[r for r in rows if r["policy"]=="adaptive" and r["block_id"] in prefix_limits and r["epoch"]<=prefix_limits[r["block_id"]]]
    csv_save(output/"prefix-witness-history.csv",witness_rows)
    (output/"history.svg").write_text(history_figure(rows,definition["example_pair"]),encoding="utf-8")
    (output/"prefix-witness.svg").write_text(witness_figure(blocks,prefixes),encoding="utf-8")
    lines=["# Accumulated relative adaptation: saved-data results","",
        "Retrospective analysis of the existing campaign; no new workloads or altered SLO labels.","",
        f'All {summary["received_pairs"]}/{summary["planned_pairs"]} runner pairs, {summary["histories"]} attempted histories and {summary["windows"]} windows are retained.',
        f'Complete baseline-safe fixed-endpoint pairs: {summary["complete_paired_endpoints"]}.',"",
        "## 1. Full accumulated history and external requirements","",
        "![Original fixed example, with accumulated drift](history.svg)","",
        "Every measured state is referenced to its own baseline; all twenty displacement coordinates are preserved.",
        "The full norm and its three-coordinate projection share relative-geometric units. Raw-share distances use different scales and are not overlaid.",
        "Positive margin means measured slack before the stated requirement, not reserved resource capacity; error-rate membership is strictly below 1%.",
        "Accounting observed-p99 margin is diagnostic and conditional on observed commits, not a replacement for the timely fraction.","",
        "| Fixed cycle-20 control-adjusted quantity | Pairs | Median change | Pair-bootstrap median interval |",
        "| --- | ---: | ---: | --- |"]
    for metric,r in summary["fixed_endpoint_contrasts"].items():
        lines.append(f'| {metric} | {r["pairs"]} | {r["median"]:.4f} | {r["pair_bootstrap_median_95"]} |')
    lines += ["", "Metrics retain their own physical units; a recipient gain never compensates for another violated requirement.",
        "Intervals resample complete runner pairs, not windows. They describe these designed contexts, not production reliability.",
        "The controller command path also records rollbacks between measured windows. An applied state without a subsequent window receives no inferred SLO.",
        f'Unmeasured post-rollback adaptive endpoints: {summary["unknown_post_rollback_endpoint_slo"]}.',"",
        "## 2. What entire selected local traces hide","",
        "![Post-hoc selected-history collision](prefix-witness.svg)","",
        f'Equal selected endpoint coordinates produced {len(endpoints)} overlapping safe/unsafe comparisons.',
        f'Equality at every epoch from baseline through a common prefix produced {len(prefixes)} overlapping comparisons, involving unsafe histories {summary["prefix_witness_unsafe_histories"]}.',
        "These are descriptive witnesses of projection loss, not independent replications or causal effects.",
        "Full raw shares and full ILR both retain the differing allocation paths. Neither alone determines the SLO outcome.",
        f'Median of per-adaptive-history median cumulative displacement energy outside the selected projection: {summary["median_history_median_cumulative_hidden_fraction"]:.4f}.',
        "This is geometric information loss, not a missed-alarm percentage.","",
        "| Unsafe runner / epoch | Safe runner / epoch | Checkout p95 unsafe / safe (ms) | DB CPU unsafe / safe | Kafka CPU unsafe / safe |",
        "| --- | --- | --- | --- | --- |"]
    for r in prefixes:
        lines.append(f'| {r["unsafe_block"]} / {r["unsafe_epoch"]} | {r["safe_block"]} / {r["safe_epoch"]} | {r["unsafe_checkout_p95_ms"]:.2f} / {r["safe_checkout_p95_ms"]:.2f} | {r["unsafe_cpu_astronomy-db"]} / {r["safe_cpu_astronomy-db"]} | {r["unsafe_cpu_kafka"]} / {r["safe_cpu_kafka"]} |')
    lines += ["", "All three selected coordinate traces coincide over each entire prefix, not merely at the displayed endpoint.",
        "Runner noise, differing hidden state and different preceding full allocations are not eliminated by this retrospective comparison.","",
        "## 3. Actual equal additive transfers, different relative movement","",
        "All examples are first transfers at moderate load in repetition 1; they were selected retrospectively for illustration.","",
        "| Initial context | Accounting CPU before/after | Accounting relative loss | Raw-share norm | Aitchison/ILR norm | Measured safe |",
        "| --- | --- | ---: | ---: | ---: | --- |"]
    for r in real:
        lines.append(f'| {r["block_id"]} | {r["accounting_cpu_before"]} / {r["accounting_cpu_after"]} | {-r["accounting_relative_change_percent"]:.2f}% | {r["raw_share_displacement_norm"]:.5f} | {r["relative_displacement_norm"]:.5f} | {r["observed_safe"]} |')
    lines += ["", "Each transfers 0.04 CPU from accounting to advertising (0.25 to 0.29), under the same 3.4-CPU budget.",
        "The complete additive displacement vector is identical; relative losses and complete ILR vectors differ.",
        "The starting composition plus the raw change also permits recovering this difference. CoDA supplies a systematic relative representation, not new data.",
        "A larger relative displacement is not asserted to cause a larger SLO risk. These three examples were all safe.","",
        "## 4. Known geometric property, explicitly separate from runtime evidence","",
        "The multiplier from the balanced example is applied and closed at every example's initial composition.",
        "These transformed endpoints were not executed and have no SLO labels.",
        "For the same positive relative perturbation, full ILR displacement is invariant to the starting composition; raw-share displacement need not be.",
        "This verifies an established identity in this implementation, not a new theorem or a prediction guarantee.",
        f'Inverse, relative-identity and accumulated-vector checks: {summary["geometry_verification"]}.',"",
        "## 5. Consequence analogy remains an additional, non-superior result","",
        "The original analogy errors are retained unchanged. A newly added no-headroom-change diagnostic is reported separately.","",
        "| Method | Macro pair mean absolute error | Median nearest runner pairs |",
        "| --- | ---: | ---: |"]
    for r in summary["secondary_diagnostics"]:
        lines.append(f'| {r["method"]} | {r["macro_pair_mean_absolute_error"]:.4f} | {r["median_nearest_pairs"]} |')
    lines += ["", "Lower is better in this particular headroom-change task. These are not alerting error rates.",
        "The constant no-change diagnostic performs better than all three analogy procedures in this aggregate error.",
        "Tie-induced averaging uses many more neighboring runner pairs for raw shares than for ILR; the comparison does not isolate geometry from smoothing.",
        "Similarity uses one-step displacements without the full starting allocation or internal queue state. It is not a test of complete-history prediction.",
        "No ILR predictive superiority is inferred or substituted for the accumulated-history results.","",
        "## Scope and reproducibility","",
        "Only CPU moves within these histories. RAM remains a differing initial context; twenty state coordinates do not imply twenty exercised directions.",
        "Closed configured ceilings are not reserved or consumed resources. Loads, absolute budgets and runtime history remain context.",
        "Vector accumulation and inversion are mathematical/implementation checks. Runtime trade-offs and hidden selected traces are separate empirical observations.",
        "Observed-vertex and command-vertex path lengths refer to discrete settled allocation vertices, not unobserved continuous kernel-update trajectories.","",
        "[All cumulative windows](history-windows.csv), [every trajectory](trajectory-level.csv), [paired epochs](paired-epochs.csv).",
        "[All prefix witnesses](prefix-witnesses.csv), [their complete prefixes](prefix-witness-history.csv), [endpoint witnesses](endpoint-witnesses.csv).",
        "[Actual transfers](actual-transfer-examples.csv), [unexecuted property checks](relative-update-checks.csv), [secondary diagnostics](secondary-diagnostics.csv).",
        "[Machine-readable summary](summary.json). All original primary observations remain in the separate main archive.", ""]
    (output/"RESULTS.md").write_text("\n".join(lines),encoding="utf-8")
    return summary


def main():
    parser=argparse.ArgumentParser(description="Analyze accumulated saved allocation histories; starts no runtime.")
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--commit",default="0000000000000000000000000000000000000000")
    parser.add_argument("--run-id",default="0")
    args=parser.parse_args()
    summary=save(args.output_dir,commit=args.commit,run_id=args.run_id)
    print(json.dumps({k:summary[k] for k in ("version","received_pairs","windows","entire_prefix_witness_comparisons")}))


if __name__=="__main__":
    main()
