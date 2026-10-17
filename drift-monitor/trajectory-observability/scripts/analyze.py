"""Retrospective trajectory readout; never changes a controller or MEWMA rule."""
from __future__ import annotations

from collections import Counter
import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
REPO = MODULE.parents[1]
INPUTS = MODULE / "inputs"
OUT = MODULE / "results/v0.1.0"
sys.path.insert(0, str(REPO / "drift-monitor/scripts"))
from monitor_core import integrate

PARTS = tuple(json.loads((REPO / "drift-monitor/design-v0.1.0.json").read_text())["parts"])
GROUPS = (tuple(range(7)), (8, 9, 10), (7,))
GROUP_NAMES = ("ordering", "ledger", "advertising")
LAM = .2
TOL = 1e-12


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")


def table(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, list(dict.fromkeys(k for row in rows for k in row)))
        writer.writeheader(); writer.writerows(rows)


def close(x):
    x = np.asarray(x, dtype=float)
    if np.any(x <= 0) or not np.isfinite(x).all():
        raise ValueError("Strictly positive finite parts required; no replacement or clipping")
    return x / x.sum(axis=-1, keepdims=True)


def clr(x):
    z = np.log(close(x))
    return z - z.mean(axis=-1, keepdims=True)


def coarse(x):
    x = np.asarray(x)
    return np.stack([x[..., list(g)].sum(axis=-1) for g in GROUPS], axis=-1)


def norm(x):
    return float(np.linalg.norm(x))


def cosine(a, b):
    na, nb = norm(a), norm(b)
    return float(np.clip(a @ b / (na*nb), -1, 1)) if min(na, nb) > TOL else None


def angle(a, b):
    c = cosine(a, b)
    return None if c is None else float(np.degrees(np.arccos(c)))


def smooth_steps(steps, lam=LAM):
    state = np.zeros(np.asarray(steps).shape[-1]); output = []
    for step in steps:
        state = lam * step + (1-lam) * state
        output.append(state.copy())
    return np.asarray(output)


def trajectory(values, reference, times, *, first_is_reference=False):
    """All vectors use only the prefix. Increments are per observation, not /s."""
    x, x0 = close(values), close(reference)
    displacement = clr(x) - clr(x0)
    previous = np.vstack([np.zeros(len(PARTS)), displacement[:-1]])
    steps = displacement - previous
    raw_displacement = x-x0
    raw_steps = raw_displacement - np.vstack([np.zeros(len(PARTS)), raw_displacement[:-1]])
    if first_is_reference:
        np.testing.assert_allclose(displacement[0], 0, atol=TOL)
    filtered = smooth_steps(steps)
    raw_filtered = smooth_steps(raw_steps)
    # Finite additive-step readout, not a change to an existing MEWMA observer.
    raw_relative = []
    for current, v in zip(x, raw_filtered):
        implied = current + v
        raw_relative.append(clr(implied)-clr(current) if np.all(implied > 0) else None)
    rows = []
    for t in range(len(x)):
        row = {"displacement_norm": norm(displacement[t]), "increment_norm": norm(steps[t]),
               "ewma_increment_norm": norm(filtered[t]), "raw_increment_norm": norm(raw_steps[t]),
               "raw_ewma_increment_norm": norm(raw_filtered[t]),
               "increment_ewma_angle_degrees": angle(steps[t], filtered[t]),
               "increment_toward_reference_cosine": cosine(steps[t], -previous[t]),
               "ewma_toward_reference_cosine": cosine(filtered[t], -previous[t]),
               "relative_readout_angle_degrees": angle(raw_relative[t], filtered[t]) if raw_relative[t] is not None else None,
               "displacement_change": norm(displacement[t])-norm(previous[t]),
               "interval_between_window_centers_s": (times[t]-times[t-1])/1000 if t else None}
        for i, p in enumerate(PARTS):
            for prefix, array in (("share_", x), ("displacement_clr_", displacement),
                                  ("increment_clr_", steps), ("ewma_increment_clr_", filtered),
                                  ("raw_increment_", raw_steps), ("raw_ewma_increment_", raw_filtered)):
                row[prefix+p] = float(array[t, i])
        rows.append(row)
    return rows, {"x": x, "displacement": displacement, "steps": steps,
                  "filtered": filtered, "raw_steps": raw_steps, "raw_filtered": raw_filtered}


def describe(values):
    a = np.array([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if not len(a):
        return {"n": 0}
    return {"n": len(a), "median": float(np.median(a)), "mean": float(a.mean()),
            "min": float(a.min()), "max": float(a.max())}


def action(current, previous, declared=None):
    if previous is None:
        return "reference"
    if np.allclose(current, previous, atol=TOL, rtol=0):
        return "hold"
    return "restore" if (declared or {}).get("restore") else "transfer"


def replay_native(path, observations):
    """Verify archived rate means; also audit integral coverage without exclusions."""
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        frames = [json.loads(line) for line in stream]
    for f in frames:
        f["wall_seconds"] = dt.datetime.fromisoformat(f["timestamp"]).timestamp()
    checks = []
    for w in observations:
        left, right = w["window_start_ms"]/1000, w["window_end_ms"]/1000
        selected = [f for f in frames if left <= f["wall_seconds"] <= right]
        deltas = [[f["containers"][p]["delta"]["cpu_cores"] for f in selected
                   if f["containers"].get(p, {}).get("delta") and
                   "memory_current_bytes" in f["containers"].get(p, {})] for p in PARTS]
        means = np.array([np.mean(a) if a else np.nan for a in deltas])
        recorded = np.array([w["resources"][p]["cpu_cores"] for p in PARTS])
        np.testing.assert_allclose(means, recorded, atol=1e-12, rtol=1e-12)
        integral = integrate(frames, PARTS, left, right)
        checks.append({"epoch": w["epoch"], "maximum_mean_replay_error": float(np.abs(means-recorded).max()),
                       "minimum_counter_coverage": min(integral["coverage"]),
                       "integral_valid_at_existing_95pct_gate": integral["valid"],
                       "max_integral_vs_archived_mean_difference_cpu": float(np.max(np.abs(np.array(integral["cpu"])-recorded))),
                       **{"integrated_cpu_"+p: float(v) for p,v in zip(PARTS, integral["cpu"])}})
    return checks


def archived_adaptation():
    path = REPO / "probe7/results/main-v0.2.0/block-level.json"
    blocks = read(path); all_rows = []; events = []; quality = []; histories = []; examples = {}; provenance = []
    for bid, job in sorted(blocks.items()):
        for policy, history in job["histories"].items():
            obs = history["observations"]
            assert all(w["valid"] for w in obs)
            assert [w["epoch"] for w in obs] == list(range(len(obs)))
            q = np.array([[w["allocation"]["cpu"][p] for p in PARTS] for w in obs])
            u = np.array([[w["resources"][p]["cpu_cores"] for p in PARTS] for w in obs])
            times = [(w["window_start_ms"]+w["window_end_ms"])/2 for w in obs]
            np.testing.assert_allclose(q.sum(axis=1), 3.4, atol=TOL)
            qr, qd = trajectory(q, q[0], times, first_is_reference=True)
            ur, ud = trajectory(u, u[0], times, first_is_reference=True)
            native = INPUTS / "native" / bid / policy / "resource-samples.jsonl.gz"
            checks = replay_native(native, obs)
            integrated_u = np.array([[c["integrated_cpu_"+p] for p in PARTS] for c in checks])
            integral_rows, _ = trajectory(integrated_u, integrated_u[0], times, first_is_reference=True)
            provenance.append({"block_id": bid, "policy": policy,
                               "native_source": native.relative_to(MODULE).as_posix(),
                               "native_sha256": hashlib.sha256(native.read_bytes()).hexdigest()})
            quality.extend({"block_id": bid, "policy": policy, **r} for r in checks)
            actions = []
            for i, w in enumerate(obs):
                label = action(q[i], q[i-1] if i else None, w.get("action"))
                actions.append(label)
                row = {"campaign": "guarded_adaptation", "block_id": bid, "policy": policy,
                       "context": job["initial_state"], "profile": job["profile"],
                       "epoch": w["epoch"], "action": label, "donor": (w.get("action") or {}).get("donor"),
                       "valid": w["valid"], "safe": w["safe"],
                       "checkout_p95_ms": w["checkout"]["p95_ms"],
                       "checkout_error_fraction": w["checkout"]["error_rate"],
                       "ad_goodput": w["advertising"]["goodput"],
                       "ad_timely_fraction": w["advertising"]["timely_fraction"],
                       "accounting_timely_fraction": w["accounting"]["timely_fraction"],
                       "total_cpu_consumption": float(u[i].sum()),
                       **{"quota_"+k: v for k,v in qr[i].items()},
                       **{"usage_"+k: v for k,v in ur[i].items()},
                       **{"native_"+k: v for k,v in checks[i].items() if k != "epoch"},
                       **{"integrated_usage_"+k: integral_rows[i][k] for k in
                          ("displacement_norm", "increment_norm", "ewma_increment_norm", "displacement_change",
                           "increment_toward_reference_cosine", "ewma_toward_reference_cosine")}}
                all_rows.append(row)
                if policy == "adaptive" and label in {"hold", "restore"}:
                    events.append({k: v for k,v in row.items() if not any(k.startswith(p) for p in
                        ("quota_share_", "quota_displacement_clr_", "quota_increment_clr_", "quota_ewma_increment_clr_",
                         "quota_raw_increment_", "quota_raw_ewma_increment_", "usage_share_", "usage_displacement_clr_",
                         "usage_increment_clr_", "usage_ewma_increment_clr_", "usage_raw_increment_", "usage_raw_ewma_increment_"))})
            histories.append({"block_id": bid, "policy": policy, "windows": len(obs),
                              "stop_reason": history.get("stop_reason"),
                              "unsafe_windows": sum(not w["safe"] for w in obs),
                              "actions": dict(Counter(actions)),
                              "minimum_native_coverage": min(c["minimum_counter_coverage"] for c in checks)})
            if bid == blocks["balanced-busy-01"]["design"]["example_pair"]:
                examples[policy] = {"observations": obs, "quota": qd, "usage": ud}
        print(json.dumps({"adaptation_block_replayed": bid}), flush=True)
    write_csv(OUT/"adaptation-windows.csv", all_rows)
    write_csv(OUT/"adaptation-events.csv", events)
    write_csv(OUT/"native-replay.csv", quality)
    dump(OUT/"adaptation-histories.json", histories)
    dump(OUT/"adaptation-native-provenance.json", provenance)
    summary = {"blocks": len(blocks), "histories": len(histories), "windows": len(all_rows),
               "quantity": "Archived mean of native per-interval CPU rates; quota state kept separately",
               "all_archived_cpu_rate_means_reproduced_from_native_samples": True,
               "maximum_native_mean_replay_error": max(r["maximum_mean_replay_error"] for r in quality),
               "native_counter_coverage": describe([r["minimum_counter_coverage"] for r in quality]),
               "windows_below_existing_95pct_counter_gate": sum(not r["integral_valid_at_existing_95pct_gate"] for r in quality),
               "adaptive_holds": sum(r["action"] == "hold" for r in events),
               "adaptive_restorations": sum(r["action"] == "restore" for r in events),
               "hold_usage_increment_norm": describe([r["usage_increment_norm"] for r in events if r["action"] == "hold"]),
               "restore_usage_distance_reduced": sum(r["usage_displacement_change"] < 0 for r in events if r["action"] == "restore"),
               "restore_integrated_usage_distance_reduced": sum(r["integrated_usage_displacement_change"] < 0 for r in events if r["action"] == "restore"),
               "short_histories_retained": [r for r in histories if r["windows"] != 21],
               "restorations": [r for r in events if r["action"] == "restore"],
               "holds": [r for r in events if r["action"] == "hold"]}
    return summary, examples, path


def coherence(steps):
    length = float(np.linalg.norm(steps, axis=1).sum())
    return norm(steps.sum(axis=0))/length if length else None


def resolve(fragments, lineage):
    """Lineage is supplied for this replay, never inferred from future samples."""
    if set(fragments)-set(lineage):
        return None
    result = np.zeros(len(PARTS))
    for name, amount in fragments.items():
        if lineage[name] not in PARTS or not np.isfinite(amount) or amount <= 0:
            return None
        result[PARTS.index(lineage[name])] += amount
    return result if np.all(result > 0) else None


def fragments_at(x, epoch):
    fragments, lineage = {}, {}
    for part, amount in zip(PARTS, x):
        if part == "accounting" and 8 <= epoch < 12:
            for suffix, fraction in (("-a", .4), ("-b", .6)):
                fragments[part+suffix] = amount*fraction; lineage[part+suffix] = part
        else:
            name = "payment-renamed" if part == "payment" and epoch >= 5 else part
            fragments[name] = amount; lineage[name] = part
    return fragments, lineage


def structural_check(cpu):
    reference = close(cpu)
    rows = []
    for epoch, value in enumerate(reference, 1):
        fragments, lineage = fragments_at(value, epoch)
        restored = resolve(fragments, lineage)
        assert restored is not None
        np.testing.assert_allclose(restored, value, atol=TOL)
        changed = value.copy()
        if epoch >= 10:
            amount = .2*changed[PARTS.index("cart")]
            changed[PARTS.index("cart")] -= amount
            changed[PARTS.index("checkout")] += amount
        np.testing.assert_allclose(coarse(changed), coarse(value), atol=TOL)
        bad_lineage = dict(lineage)
        if epoch == 8:
            del bad_lineage["accounting-b"]
        gated = resolve(fragments, bad_lineage) is None
        rows.append({"epoch": epoch,
            "pure_structure_detail_distance": norm(clr(restored)-clr(value)),
            "pure_structure_canonical_distance": norm(clr(coarse(restored))-clr(coarse(value))),
            "within_group_change_detail_distance": norm(clr(changed)-clr(value)),
            "within_group_change_canonical_distance": norm(clr(coarse(changed))-clr(coarse(value))),
            "within_ordering_subcomposition_distance": norm(clr(changed[list(GROUPS[0])])-clr(value[list(GROUPS[0])])),
            "unknown_lineage_gated": gated})
    return rows


def continuous():
    selected = table(INPUTS/"selected-cases.csv")
    histories, windows, structure, transport, provenance = [], [], [], [], []
    starts = None
    with gzip.open(INPUTS/"continuous-selected.jsonl.gz", "rt", encoding="utf-8") as stream:
        jobs = [json.loads(line) for line in stream]
    provenance = read(INPUTS/"continuous-provenance.json")
    assert len(jobs) == len(selected) == len(provenance) == 250
    for index, (r, job, source) in enumerate(zip(selected, jobs, provenance)):
        assert job["block_id"] == r["block_id"] == source["block_id"]
        assert str(job["run_id"]) == r["source_run"] == source["run_id"]
        assert str(job["run_attempt"]) == r["source_attempt"] == source["run_attempt"]
        assert source["compact_record_index"] == index
    starts = np.array([next(j for j in jobs if j["context"] == c)["histories"]["drift"]["reference"]["cpu"]
                       for c in sorted({j["context"] for j in jobs})])
    for job in jobs:
        for policy in ("drift", "control"):
            h = job["histories"][policy]; obs = h["observations"]
            assert h["qualified"] and len(obs) == 16 and all(w["valid"] for w in obs)
            u = np.array([w["cpu"] for w in obs]); ref = np.array(h["reference"]["cpu"])
            q = np.array([[w["allocation"]["cpu"][p] for p in PARTS] for w in obs])
            times = [(w["start_ms"]+w["end_ms"])/2 for w in obs]
            rr, data = trajectory(u, ref, times)
            for t, (row, original, load) in enumerate(zip(rr, obs, h["load"]["windows"])):
                previous_q = q[t-1] if t else q[t]
                windows.append({"campaign": "continuous", "block_id": job["block_id"], "policy": policy,
                    "epoch": original["epoch"], "action": action(q[t], previous_q),
                    "total_cpu_consumption": float(u[t].sum()),
                    "checkout_p95_ms": load["checkout_p95_ms"], "checkout_error_fraction": load["checkout_error_fraction"],
                    "ad_goodput": load["ad_goodput"], "ad_timely_fraction": load["ad_timely_fraction"], **row})
            histories.append({"block_id": job["block_id"], "policy": policy,
                "post4_relative_path_coherence": coherence(data["steps"][4:]),
                "post4_raw_share_path_coherence": coherence(data["raw_steps"][4:]),
                "post4_path_length": float(np.linalg.norm(data["steps"][4:],axis=1).sum()),
                "post4_net_displacement_norm": norm(data["steps"][4:].sum(axis=0)),
                "final_displacement_norm": norm(data["displacement"][-1]),
                "final_ewma_increment_norm": norm(data["filtered"][-1])})
            if policy == "drift":
                structure.extend({"block_id": job["block_id"], **r} for r in structural_check(u))
                factors = close(u)/close(ref)
                ilr_vectors, raw_vectors = [], []
                for start in starts:
                    path = close(start*factors)
                    delta = np.diff(np.vstack([clr(start), clr(path)]), axis=0)
                    delta_raw = np.diff(np.vstack([close(start), path]), axis=0)
                    ilr_vectors.append(smooth_steps(delta))
                    raw_vectors.append(smooth_steps(delta_raw))
                transport.append({"block_id": job["block_id"],
                    "ilr_filtered_increment_maximum_coordinate_range": float(np.ptp(ilr_vectors, axis=0).max()),
                    "raw_filtered_increment_maximum_coordinate_range": float(np.ptp(raw_vectors, axis=0).max()),
                    "raw_final_filtered_increment_max_pair_angle": max(angle(a[-1],b[-1]) or 0 for i,a in enumerate(raw_vectors) for b in raw_vectors[i+1:])})
    assert len(histories) == 500 and len(windows) == 8000
    write_csv(OUT/"continuous-windows.csv", windows)
    write_csv(OUT/"continuous-histories.csv", histories)
    write_csv(OUT/"structure-replay.csv", structure)
    write_csv(OUT/"relative-transport-not-runtime.csv", transport)
    dump(OUT/"source-provenance.json", provenance)
    pairs = []
    for bid in sorted({r["block_id"] for r in histories}):
        d, c = [next(r for r in histories if r["block_id"] == bid and r["policy"] == p) for p in ("drift", "control")]
        pairs.append(d["post4_relative_path_coherence"]-c["post4_relative_path_coherence"])
    rng = np.random.default_rng(2026101705)
    boot = np.mean(rng.choice(np.array(pairs), size=(5000, len(pairs))), axis=1)
    summary = {"pairs": 250, "histories": 500, "windows": 8000,
        "relative_path_coherence": {p: describe([r["post4_relative_path_coherence"] for r in histories if r["policy"] == p]) for p in ("drift", "control")},
        "paired_coherence_difference": describe(pairs),
        "paired_mean_coherence_difference_descriptive_bootstrap95": np.quantile(boot, [.025, .975]).tolist(),
        "pairs_with_higher_coherence_during_reallocation": sum(v>0 for v in pairs),
        "structure_replay": {"histories": 250, "windows": len(structure),
            "maximum_pure_structure_detail_error": max(r["pure_structure_detail_distance"] for r in structure),
            "maximum_pure_structure_canonical_error": max(r["pure_structure_canonical_distance"] for r in structure),
            "maximum_within_group_canonical_change": max(r["within_group_change_canonical_distance"] for r in structure),
            "within_group_detail_change_after_epoch10": describe([r["within_group_change_detail_distance"] for r in structure if r["epoch"]>=10]),
            "unknown_lineage_gated_cases": sum(r["unknown_lineage_gated"] for r in structure)},
        "mathematical_transport_not_runtime": {
            "maximum_ilr_filtered_increment_coordinate_range": max(r["ilr_filtered_increment_maximum_coordinate_range"] for r in transport),
            "raw_final_filtered_increment_cross_start_angle": describe([r["raw_final_filtered_increment_max_pair_angle"] for r in transport])}}
    return summary


def run():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Scratch output directory; committed inputs and results are never overwritten")
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()
    OUT = args.output_dir.resolve()
    if OUT == REPO.resolve() or REPO.resolve().is_relative_to(OUT):
        parser.error("Output must not be the repository or an ancestor")
    if OUT.is_relative_to(REPO.resolve()) and not OUT.is_relative_to((REPO/"artifacts").resolve()):
        parser.error("Use the ignored artifacts directory for an in-repository replay")
    OUT.mkdir(parents=True, exist_ok=True)
    adaptation, examples, source = archived_adaptation()
    population = continuous()
    summary = {"version": "trajectory-observability-0.1.0", "lambda": LAM,
               "scope": "Retrospective descriptive readout, no controller changes, no fitted forecast or new alert threshold",
               "adaptation": adaptation, "continuous": population,
               "adaptation_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "distinctions": ["Quota actions are not measured consumption.",
                  "Per-window increments and their EWMA are not the original MEWMA states or alarms.",
                  "No automatic attribution of a CPU direction to danger.",
                  "Coarse group sums do not retain all fine-grained relative information.",
                  "Structure changes and transported starts are controlled replays, not newly observed runtime events.",
                  "The old adaptation campaign has intermittent generators; the continuous campaign does not. Do not pool their outcomes."]}
    dump(OUT/"summary.json", summary)
    if not args.no_figures:
        from render import figures
        figures(examples, summary, OUT)
    print(json.dumps({"adaptation_blocks": adaptation["blocks"], "continuous_pairs": population["pairs"],
                      "output": str(OUT)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    run()
