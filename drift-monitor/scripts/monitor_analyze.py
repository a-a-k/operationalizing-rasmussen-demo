"""Freeze background-only models, verify online replay and summarize paired timing."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from monitor_core import (DESIGN, METHODS, Observer, close, digest, feature, fit_background, load, matrix, save)


def csv_save(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)


def read_jobs(folder, phase):
    latest = {}
    for path in sorted(folder.rglob("job.json")):
        job = load(path)
        if job["phase"] != phase:
            continue
        if job["design_sha256_lf"] != digest(DESIGN) or job["execution_commit"] != os.environ["GITHUB_SHA"]:
            raise ValueError("Job provenance mismatch")
        bid = job["block_id"]
        if bid not in latest or int(job["run_attempt"]) > int(latest[bid]["run_attempt"]):
            latest[bid] = job
    planned = {r["block_id"]: r for r in matrix(phase)}
    if set(latest) - set(planned):
        raise ValueError("Unexpected matrix jobs")
    for bid, job in latest.items():
        if any(job[k] != planned[bid][k] for k in ("context", "repetition", "role", "order")):
            raise ValueError("Recorded matrix row differs")
    return latest


def freeze(inputs, output):
    jobs = read_jobs(inputs, "background")
    status = [{"block_id": bid, "role": j["role"], "qualified": j["histories"].get("background", {}).get("qualified", False),
               "settling": j["histories"].get("background", {}).get("settling"),
               "reasons": j["histories"].get("background", {}).get("reasons", ["missing_history"])} for bid, j in jobs.items()]
    save(output / "background-status.json", {"received": len(jobs), "planned": len(matrix("background")), "histories": status})
    frozen = fit_background(list(jobs.values()))
    frozen.update(execution_commit=os.environ["GITHUB_SHA"], run_id=os.environ["GITHUB_RUN_ID"],
                  run_attempt=os.getenv("GITHUB_RUN_ATTEMPT", "1"), frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    save(output / "frozen-model.json", frozen)
    print(json.dumps({"status": "frozen", "fit_histories": len(frozen["fit_ids"]), "calibration_histories": len(frozen["calibration_ids"])}))


def score_history(history, frozen, policy):
    cfg = load(DESIGN)
    observer = Observer(frozen, history["reference"]["cpu"])
    first = {m: None for m in METHODS}
    for w in history["observations"]:
        replay = observer.update(w["cpu"])
        for method in METHODS:
            actual = w["online"][method]
            if not np.isclose(replay[method]["score"], actual["score"], rtol=1e-10, atol=1e-9):
                raise ValueError("Online score differs from prefix replay")
            if replay[method]["signal"] != actual["signal"]:
                raise ValueError("Online signal differs from prefix replay")
            if first[method] is None and actual["signal"]:
                first[method] = w["epoch"]
    output = {}
    onset = cfg["pre_intervention_windows"] + 1
    for method, epoch in first.items():
        detected = policy == "drift" and epoch is not None and epoch >= onset
        premature = policy == "drift" and epoch is not None and epoch < onset
        output[method] = {"first_epoch": epoch, "detected": detected, "premature": premature,
                          "control_signal": policy == "control" and epoch is not None,
                          "restricted_delay_windows": epoch - onset + 1 if detected else cfg["monitor_windows"] - cfg["pre_intervention_windows"]}
    return output


def figure(jobs, pair_rows, output):
    cfg = load(DESIGN)
    job = jobs.get(cfg["example_block"])
    if not job or not all(p in job["histories"] for p in ("drift", "control")):
        return
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "svg.fonttype": "none", "pdf.fonttype": 42})
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.3))
    colors = {"raw_composition": "#778795", "ilr_composition": "#176b9e"}
    history = job["histories"]["drift"]
    if len(history.get("observations", [])) != cfg["monitor_windows"] or not all(w["valid"] for w in history["observations"]):
        plt.close(fig)
        return
    cpu = np.array([w["cpu"] for w in history["observations"]])
    base = np.array(history["reference"]["cpu"])
    x, base_x = close(cpu), close(base)
    logs = np.log(x) - np.log(base_x)
    clr_change = logs - logs.mean(axis=1, keepdims=True)
    epochs = np.arange(1, len(cpu) + 1)
    axes[0, 0].imshow((cpu / base).T, aspect="auto", cmap="viridis", extent=(.5, len(cpu)+.5, -.5, len(base)-.5))
    axes[0, 0].set(yticks=range(len(base)), yticklabels=cfg["parts"], xlabel="Цикл")
    axes[0, 0].set_title("A  Потребление / исходное потребление")
    picture = axes[0, 1].imshow(clr_change.T, aspect="auto", cmap="RdBu_r", vmin=-.3, vmax=.3,
                                      extent=(.5, len(cpu)+.5, -.5, len(base)-.5))
    axes[0, 1].set(yticks=range(len(base)), yticklabels=cfg["parts"], xlabel="Цикл")
    axes[0, 1].set_title("B  Полный относительный сдвиг: CLR")
    fig.colorbar(picture, ax=axes[0, 1], fraction=.045)
    for policy, style in (("drift", "-"), ("control", "--")):
        h = job["histories"][policy]
        good = [w for w in h.get("observations", []) if w["valid"]]
        axes[0, 2].plot([w["epoch"] for w in good], [w["aitchison_displacement"] for w in good], style,
                         color="#176b9e" if policy == "drift" else "#778795", label=policy)
        for method in METHODS:
            scored = [w for w in good if w.get("online")]
            axes[1, 1].plot([w["epoch"] for w in scored], [w["online"][method]["score"] / w["online"][method]["threshold"] for w in scored],
                             style, color=colors[method], label=method + ":" + policy)
    axes[0, 2].set(xlabel="Цикл", ylabel="Расстояние Айтчисона от опорного состояния")
    axes[0, 2].set_title("C  Движение видно и без сигнала")
    axes[0, 2].legend(frameon=False)
    if pair_rows:
        raw = [r["raw_first_drift_epoch"] or cfg["monitor_windows"] + 1 for r in pair_rows]
        ilr = [r["ilr_first_drift_epoch"] or cfg["monitor_windows"] + 1 for r in pair_rows]
        axes[1, 0].scatter(raw, ilr, alpha=.65, color="#176b9e")
        axes[1, 0].plot([1, 17], [1, 17], ":", color="#777")
    axes[1, 0].set(xlabel="Первый сигнал: MEWMA напрямую", ylabel="Первый сигнал: MEWMA в ILR", xlim=(.5, 17.5), ylim=(.5, 17.5))
    axes[1, 0].set_title("D  Все общие проверочные пары; 17 = нет сигнала")
    axes[1, 1].axhline(1, color="#a94b4b", ls=":")
    axes[1, 1].set(xlabel="Цикл", ylabel="Статистика / порог")
    axes[1, 1].set_title("E  Зафиксированные наблюдатели")
    axes[1, 1].legend(fontsize=6, frameon=False)
    for policy, style in (("drift", "-"), ("control", "--")):
        windows = job["histories"][policy].get("load", {}).get("windows", [])
        axes[1, 2].plot([w["epoch"] for w in windows], [w["ad_goodput"] for w in windows], style,
                         label=policy, color="#176b9e" if policy == "drift" else "#778795")
    axes[1, 2].set(xlabel="Цикл", ylabel="Успешные ответы рекламы внутри окна / с")
    axes[1, 2].set_title("F  Выход получателя измеряется отдельно")
    for ax in axes.ravel():
        if ax not in (axes[0, 0], axes[0, 1], axes[1, 0]):
            ax.axvline(cfg["pre_intervention_windows"] + .5, color="#a77e44", ls=":", lw=1)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Непрерывная runtime-история: полное состояние, относительное движение и MEWMA", fontsize=15, y=.99)
    fig.text(.025, .025, "Пример balanced-r1 задан до выполнения. Вертикальная отметка — начало вмешательства.\n"
             "Квоты определяют вмешательство, но не входят в наблюдатели; относительное движение не является само по себе сигналом опасности.", fontsize=9)
    fig.tight_layout(rect=(.01, .1, .99, .96), w_pad=2.5, h_pad=2.3)
    for ext in ("png", "svg", "pdf"):
        fig.savefig(output / ("trajectory." + ext), dpi=170, metadata={"Creator": "Continuous runtime observation"})
    plt.close(fig)


def compare(inputs, model_folder, output):
    cfg = load(DESIGN)
    jobs = read_jobs(inputs, "test")
    candidates = [load(p) for p in model_folder.rglob("frozen-model.json")]
    frozen = max(candidates, key=lambda r: int(r["run_attempt"]))
    statuses, decisions, pairs, trajectories = [], [], [], []
    for bid, job in sorted(jobs.items()):
        if job["frozen_model"] != frozen:
            raise ValueError("Test job used a different frozen model")
        qualified = all(job["histories"].get(p, {}).get("qualified", False) for p in ("drift", "control"))
        statuses.append({"block_id": bid, "qualified_pair": qualified,
                         "histories": {p: {k: h.get(k) for k in ("technical_complete", "qualified", "settling", "reasons")}
                                       for p, h in job["histories"].items()}})
        result = {}
        for policy, history in job["histories"].items():
            previous = np.zeros(len(cfg["parts"]) - 1)
            for w in history.get("observations", []):
                if not w["valid"]:
                    continue
                z = feature(w["cpu"], history["reference"]["cpu"], "ilr_composition")
                trajectories.append({"block_id": bid, "policy": policy, "epoch": w["epoch"], "qualified_pair": qualified,
                                     "total_cpu": sum(w["cpu"]), "aitchison_displacement": float(np.linalg.norm(z)),
                                     "step_norm": float(np.linalg.norm(z - previous)),
                                     **{"ilr_displacement_" + str(i+1): float(v) for i, v in enumerate(z)},
                                     **{"ilr_step_" + str(i+1): float(v) for i, v in enumerate(z - previous)}})
                previous = z
            if qualified:
                result[policy] = score_history(history, frozen, policy)
                for method, record in result[policy].items():
                    decisions.append({"block_id": bid, "policy": policy, "method": method, **record})
        if qualified:
            raw, ilr = (result["drift"][m] for m in METHODS)
            pairs.append({"block_id": bid, "raw_first_drift_epoch": raw["first_epoch"], "ilr_first_drift_epoch": ilr["first_epoch"],
                          "raw_detected": raw["detected"], "ilr_detected": ilr["detected"],
                          "raw_control_signal": result["control"]["raw_composition"]["control_signal"],
                          "ilr_control_signal": result["control"]["ilr_composition"]["control_signal"],
                          "ilr_minus_raw_restricted_delay": ilr["restricted_delay_windows"] - raw["restricted_delay_windows"]})
    methods = {}
    for method in METHODS:
        a = [r for r in decisions if r["method"] == method and r["policy"] == "drift"]
        c = [r for r in decisions if r["method"] == method and r["policy"] == "control"]
        methods[method] = {"detected": sum(r["detected"] for r in a), "premature": sum(r["premature"] for r in a),
                           "no_intervention_signals": sum(r["control_signal"] for r in c),
                           "restricted_mean_delay_windows": float(np.mean([r["restricted_delay_windows"] for r in a])) if a else None}
    summary = {"version": cfg["version"], "planned_test_pairs": len(matrix("test")), "received_test_pairs": len(jobs),
               "missing_pairs": sorted({r["block_id"] for r in matrix("test")} - set(jobs)), "qualified_pairs": len(pairs),
               "methods": methods, "fit_histories": len(frozen["fit_ids"]), "calibration_histories": len(frozen["calibration_ids"]),
               "interpretation": "Known-intervention detection and timing. Control signals are not automatically false positives. Settling is an engineering gate, not proof of stationarity.",
               "frozen_model_replayed": True}
    if pairs:
        differences = np.array([r["ilr_minus_raw_restricted_delay"] for r in pairs])
        rng = np.random.default_rng(cfg["bootstrap_seed"])
        sample = differences[rng.integers(0, len(pairs), size=(cfg["bootstrap_replicates"], len(pairs)))].mean(axis=1)
        summary["paired_delay_difference"] = {"ilr_minus_raw": float(differences.mean()),
                                               "descriptive_bootstrap_95": np.quantile(sample, [.025, .975]).tolist() if np.ptp(differences) else None}
    save(output / "summary.json", summary)
    save(output / "history-status.json", statuses)
    csv_save(output / "decisions.csv", decisions)
    csv_save(output / "pairs.csv", pairs)
    csv_save(output / "trajectories.csv", trajectories)
    figure(jobs, pairs, output)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze", "compare"])
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-folder", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.command == "freeze":
        freeze(args.inputs, args.output_dir)
    else:
        compare(args.inputs, args.model_folder, args.output_dir)
