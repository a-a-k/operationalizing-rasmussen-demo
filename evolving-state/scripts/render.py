"""Render one preselected history without selecting for effect size."""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analyze import lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    directories = sorted(p.parent for p in (args.bundle / "inputs").rglob("status.json"))
    source = directories[0]
    cfg = json.loads((source / "load-config.json").read_text())
    block = json.loads((source / "status.json").read_text())["block"]
    reports = lines(source / "diagnoses.jsonl")
    rows = [r["rows"][2] for r in reports]
    events = [e for e in lines(source / "journals/client.jsonl") if e["type"] == "configuration_applied"]
    elapsed = [(r["diagnosed_ms"] - cfg["origin_ms"]) / 1000 for r in rows]
    plt.rcParams.update({"svg.hashsalt": "evolving-state-v0.1.1", "font.size": 10})
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
    palette = {"catalog": "#1676a1", "currency": "#cc6b23"}
    ax = axes[0, 0]
    for group in ("catalog", "currency"):
        ax.step(elapsed, [r["groups"][group]["ratio"] for r in rows], where="post",
                label=group, color=palette[group])
    times = [max(0, (e["applied_ms"] - cfg["origin_ms"]) / 1000) for e in events]
    limits = [e["config"]["policy_limits"]["catalog"] for e in events]
    ax.step(times + [cfg["windows"] * cfg["window_seconds"]], limits + [limits[-1]],
            where="post", color="#333333", linestyle="--", label="Current policy limit")
    ax.set(title="A  Measured retry fractions and the changing limit",
           xlabel="Seconds since load origin", ylabel="Retries / all attempt starts", ylim=(-.02, .57))
    ax.legend(fontsize=8)
    ax = axes[0, 1]
    table = list(csv.DictReader((args.bundle / "analysis/execution-windows.csv").open()))
    table = [r for r in table if r["block"] == block]
    xs, successes, work = [], [], []
    for window in range(1, cfg["windows"] + 1):
        selected = [r for r in table if int(r["window"]) == window]
        n = sum(int(r["external_client_completed"]) for r in selected)
        good = sum(int(r["external_client_success"]) for r in selected)
        first = sum(int(r["first_attempt_starts"]) for r in selected)
        retry = sum(int(r["retry_attempt_starts"]) for r in selected)
        xs.append(window * cfg["window_seconds"])
        successes.append(good / n if n else math.nan)
        work.append((first + retry) / first if first else math.nan)
    ax.plot(xs, successes, color="#268151", marker=".", label="Client success fraction")
    other = ax.twinx()
    other.plot(xs, work, color="#9467bd", linestyle="--", label="Attempt starts / first attempts")
    ax.set(title="B  Successful reads and repeated work",
           xlabel="Completed window end (seconds)", ylabel="Client HTTP-200 fraction", ylim=(.65, 1.03))
    other.set_ylabel("Attempt starts / first attempts")
    ax.legend(loc="lower left", fontsize=8)
    other.legend(loc="lower right", fontsize=8)
    ax = axes[1, 0]
    prior, annotated = None, set()
    for row in rows:
        if row["geometry_status"] != "available":
            prior = None
            continue
        values = [math.log(row["groups"][g]["retry"] / row["groups"][g]["first"]) / math.sqrt(2)
                  for g in ("catalog", "currency")]
        ax.scatter(*values, color="#1676a1", s=24, zorder=3)
        if prior and row["window"] == prior[0] + 1:
            ax.annotate("", xy=values, xytext=prior[1],
                        arrowprops={"arrowstyle": "->", "color": "#777777", "linewidth": .8})
        if row["window"] not in annotated:
            ax.annotate(str(row["window"]), values, xytext=(4, 5 if row["window"] % 2 else -12),
                        textcoords="offset points", fontsize=8)
            annotated.add(row["window"])
        prior = row["window"], values
    ax.set(title="C  Relative direction in two policy-normal coordinates",
           xlabel="Catalog log(R/F) / sqrt(2)", ylabel="Currency log(R/F) / sqrt(2)")
    ax.text(.02, .02, "Numbers: windows. Third ILR coordinate omitted.\n"
            "Policy status is separate from position; see A.",
            transform=ax.transAxes, fontsize=8, va="bottom",
            bbox={"facecolor": "white", "alpha": .9, "edgecolor": "none"})
    ax = axes[1, 1]
    colors = {"Correct": "#268151", "Outdated": "#bf3b3b",
              "Metadata unavailable": "#d79b35", "No attempts": "#999999"}
    for report, x in zip(reports, elapsed):
        for index, row in enumerate(report["rows"]):
            gs = list(row["groups"].values())
            if any(g["status"].startswith("missing") for g in gs):
                category = "Metadata unavailable"
            elif any(g["status"] == "no_attempts" for g in gs):
                category = "No attempts"
            elif row["policy_used"] != row["policy_announced"]:
                category = "Outdated"
            else:
                category = "Correct"
            ax.scatter(x, index, marker="s", color=colors[category], s=35)
    for label, color in colors.items():
        ax.scatter([], [], marker="s", color=color, label=label)
    ax.set(title="D  Emitted reports (not continuous coverage)",
           xlabel="Seconds since load origin", yticks=[0, 1, 2],
           yticklabels=["Fixed schema", "Updated direct", "Updated CoDA"], ylim=(-.6, 3.3))
    ax.legend(fontsize=8, loc="upper center", ncol=2)
    for ax in axes.flat:
        ax.grid(alpha=.18)
    fig.suptitle(f"One complete history: {block} (smallest block ID, not selected by outcome)\n"
                 "Known lineage updates; controlled delivery faults; policy violation is not application failure",
                 fontsize=12)
    for suffix in ("png", "svg"):
        path = args.bundle / ("full-history." + suffix)
        fig.savefig(path, dpi=170, metadata={"Date": None} if suffix == "svg" else {})
        if suffix == "svg":
            path.write_text("\n".join(line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()) + "\n",
                            encoding="utf-8", newline="\n")
    plt.close(fig)


if __name__ == "__main__":
    main()
