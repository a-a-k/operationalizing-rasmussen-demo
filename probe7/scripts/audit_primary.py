from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

from measurements import accounting, advertising, parse_ack_lines, quantile

ROOT = Path(__file__).resolve().parents[2]


def compare(actual, expected, keys):
    for key in keys:
        a, b = actual[key], expected[key]
        if isinstance(a, (float, int)) and not isinstance(a, bool):
            if b is None or not math.isclose(a, b, abs_tol=1e-9, rel_tol=1e-12):
                raise ValueError(f"Primary replay differs: {key}: {a} vs {b}")
        elif a != b:
            raise ValueError(f"Primary replay differs: {key}: {a} vs {b}")


def checkout(primary, scenario, policy):
    counts = {k:int(v) for k,v in primary["counters"].items()}
    if any(v != counts[k] for k,v in primary["counters"].items()):
        raise ValueError("Noninteger primary counter")
    n = scenario["rate"] * scenario["duration_seconds"]
    started, finished, successful = [counts[k] for k in
        ("protocol_iterations_started", "protocol_iterations_finished", "successful_iterations")]
    if not 0 <= successful <= finished <= started <= n:
        raise ValueError("Primary iteration invariant failed")
    if len(primary["operation_durations_ms"]) != finished:
        raise ValueError("Primary operation duration count differs")
    if not 0 <= len(primary["checkout_durations_ms"]) <= counts["checkout_requests_started"] <= started:
        raise ValueError("Primary checkout duration count differs")
    p95 = quantile(primary["checkout_durations_ms"], .95)
    failed, dropped, unfinished = finished-successful, n-started, started-finished
    errors = failed+dropped+unfinished
    return {"p95_ms":p95,"error_rate":errors/n,"error_count":errors,"scheduled_iterations":n,
            "started_iterations":started,"finished_iterations":finished,"successful_iterations":successful,
            "failed_iterations":failed,"dropped_iterations":dropped,"unfinished_iterations":unfinished,
            "safe":p95 is not None and p95 <= policy["p95_ms"] and errors/n < policy["error_fraction"]}


def audit(pack):
    runtime = pack["runtime"]
    totals = {"block_id":pack["block_id"],"windows":0,"checkout_requests":0,"confirmed_orders":0,"ad_attempts":0}
    for w in pack["windows"]:
        c = checkout(w["checkout_primary"], w["scenario"], runtime["checkout"])
        compare(c, w["expected"]["checkout"], c)
        rows = w["order_commits"]
        if len(rows) != w["confirmed_order_counter"]:
            raise ValueError("Acknowledgment bridge differs from native confirmed-order counter")
        a = advertising(w["ad_summary"], w["scenario"]["duration_seconds"], runtime["advertising"])
        compare(a, w["expected"]["advertising"], a)
        l = accounting([{"order_id":r[0],"confirmed_ms":r[1]} for r in rows],
                       {r[0]:r[2] for r in rows if r[2] is not None},runtime["accounting"])
        compare(l, w["expected"]["accounting"], [k for k in l if k != "orders"])
        totals["windows"] += 1
        totals["checkout_requests"] += len(w["checkout_primary"]["checkout_durations_ms"])
        totals["confirmed_orders"] += len(rows)
        totals["ad_attempts"] += a["attempts"]
    return totals


def assemble(block_file, runtime):
    block = json.loads(block_file.read_text())
    pack = {"schema":1,"block_id":block["block_id"],"execution_commit":block["execution_commit"],
            "run_id":block["run_id"],"runtime":runtime,"windows":[]}
    for policy, history in block["histories"].items():
        for w in history["observations"]:
            phase = block_file.parent / policy / f'{w["epoch"]:03d}'
            compact = phase/"checkout/compact-primary.json"
            scenario = phase/"checkout/scenario-config.json"
            native = phase/"checkout/summary.json"
            ad = phase/"advertising/summary.json"
            commits = phase/"database-commits.json.gz"
            stdout, stderr = phase/"checkout/stdout.log",phase/"checkout/stderr.log"
            acks = parse_ack_lines(stdout.read_text()+"\n"+stderr.read_text())
            with gzip.open(commits, "rt",encoding="utf-8") as f:
                ledger = {r["order_id"]:r["commit_ms"] for r in json.load(f)}
            pack["windows"].append({"policy":policy,"epoch":w["epoch"],
                "checkout_primary":json.loads(compact.read_text()),"scenario":json.loads(scenario.read_text()),
                "confirmed_order_counter":json.loads(native.read_text())["metrics"]["protocol_orders_confirmed"]["values"]["count"],
                "ad_summary":json.loads(ad.read_text()),
                "order_commits":[[r["order_id"],r["confirmed_ms"],ledger.get(r["order_id"])] for r in acks],
                "expected":{p:w[p] for p in ("checkout","advertising","accounting")},
                "source_sha256":{str(p.relative_to(phase)):hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (compact,scenario,native,ad,commits,stdout,stderr)}})
    return pack


def main():
    p = argparse.ArgumentParser(description="Rescore external outcomes from preserved primary inputs; no workload execution.")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--results-root",type=Path)
    source.add_argument("--inputs",type=Path)
    p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    rows=[]
    if args.results_root:
        runtime=json.loads((ROOT/"probe7/runtime-v0.2.0.json").read_text())
        files=sorted(args.results_root.rglob("block.json"))
        for file in files:
            pack=assemble(file,runtime)
            rows.append(audit(pack))
            data=json.dumps(pack,separators=(",",":"),sort_keys=True).encode()
            (args.output_dir/(pack["block_id"]+".json.gz")).write_bytes(gzip.compress(data,mtime=0))
    else:
        for file in sorted(args.inputs.glob("*.json.gz")):
            with gzip.open(file,"rt",encoding="utf-8") as f:
                rows.append(audit(json.load(f)))
    report={"status":"verified","blocks":len(rows),"per_block":rows,
            **{key:sum(r[key] for r in rows) for key in ("windows","checkout_requests","confirmed_orders","ad_attempts")},
            "scope":"Main evaluation windows only; warmup excluded. Native counters/durations, client acknowledgments and corresponding database commit timestamps, not inferred SLO labels."}
    (args.output_dir/"summary.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "per_block"}))


if __name__ == "__main__":
    main()
