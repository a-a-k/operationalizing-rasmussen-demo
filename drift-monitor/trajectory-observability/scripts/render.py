"""Figures for a fixed archived example; no outcome-based example selection."""
from pathlib import Path
import gzip
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from analyze import INPUTS, PARTS, GROUP_NAMES, coarse, clr, norm, structural_check
matplotlib.rcParams["svg.hashsalt"] = "trajectory-observability-v0.1.0"


def save(fig, name, output):
    for extension in ("png", "svg"):
        metadata = {"Date": None} if extension == "svg" else None
        destination = output/(name+"."+extension)
        fig.savefig(destination, dpi=180, bbox_inches="tight", metadata=metadata)
        if extension == "svg":
            destination.write_text("\n".join(line.rstrip() for line in
                                   destination.read_text(encoding="utf-8").splitlines())+"\n",
                                   encoding="utf-8", newline="\n")
    plt.close(fig)


def figures(examples, summary, output):
    d = examples["adaptive"]; c = examples["control"]
    obs = d["observations"]; t = np.array([w["epoch"] for w in obs])
    fig, axes = plt.subplots(3,2,figsize=(14,12),sharex=True)
    colors = ("#377eb8", "#4daf4a", "#e41a1c")
    names = ("Ordering", "Ledger", "Advertising")
    for ax,key,title in ((axes[0,0],"quota","Confirmed CPU ceilings: controller actions"),
                         (axes[0,1],"usage","Measured CPU consumption: system response")):
        x = coarse(d[key]["x"])
        for i in range(3): ax.plot(t,x[:,i],label=names[i],color=colors[i])
        ax.set_title(title); ax.set_ylabel("Share"); ax.legend(fontsize=8)
    data = d["usage"]
    ax=axes[1,0]
    for key,label in (("displacement","Accumulated displacement"),("steps","Actual increment"),
                       ("filtered","EWMA of increments, lambda=0.2")):
        ax.plot(t,np.linalg.norm(data[key],axis=1),label=label)
    ax.set_title("Consumption position and movement are distinct")
    ax.set_ylabel("Log-ratio norm"); ax.legend(fontsize=8)
    ax=axes[1,1]
    contrast=np.full(11,-1/np.sqrt(110));contrast[PARTS.index("ad")]=np.sqrt(10/11)
    for key,label in (("steps","Actual increment"),("filtered","EWMA of increments")):
        ax.plot(t,data[key]@contrast,label=label)
    ax.axhline(0,color="gray",lw=.7)
    ax.set_title("Movement component: advertising / other services")
    ax.set_ylabel("Balance increment");ax.legend(fontsize=8)
    ax=axes[2,0]
    ax.plot(t,[w["advertising"]["goodput"] for w in obs],label="Adaptive")
    ax.plot([w["epoch"] for w in c["observations"]], [w["advertising"]["goodput"] for w in c["observations"]],label="Unchanged ceilings",ls="--")
    ax.set_title("Measured advertising goodput");ax.set_ylabel("Successful responses/s");ax.legend(fontsize=8)
    ax=axes[2,1]
    ax.plot(t,[w["checkout"]["p95_ms"] for w in obs],color="#984ea3",label="Checkout p95")
    ax.axhline(500,color="#984ea3",ls="--",label="Checkout requirement: 500 ms")
    ax.set_ylabel("ms");ax.set_title("External outcomes: not inferred from CPU direction")
    twin=ax.twinx()
    twin.plot(t,[w["accounting"]["timely_fraction"] for w in obs],color="#4daf4a",label="Timely accounting")
    twin.axhline(.99,color="#4daf4a",ls=":");twin.set_ylabel("Timely accounting fraction")
    ax.legend(loc="upper left",fontsize=7);twin.legend(loc="upper right",fontsize=7)
    for ax in axes.flat:
        ax.axvline(17,color="gray",ls=":",alpha=.7)
        ax.axvline(20,color="black",ls=":",alpha=.7)
        ax.grid(alpha=.15);ax.set_xticks(np.arange(0,21,2))
    for ax in axes[-1]:ax.set_xlabel("Measurement window")
    fig.suptitle("Complete archived history balanced-busy-01: hold at 17, restoration at 20\n"
                 "Measured consumption means; ceilings and external outcomes shown separately", fontsize=12)
    fig.tight_layout(rect=(0,0,1,.95));save(fig,"full-history-v0.1.0",output)
    with gzip.open(INPUTS/"continuous-selected.jsonl.gz", "rt", encoding="utf-8") as stream:
        source = json.loads(next(stream))
    cpu = np.array([w["cpu"] for w in source["histories"]["drift"]["observations"]])
    r=structural_check(cpu);epochs=np.array([w["epoch"] for w in r])
    fig,axes=plt.subplots(1,2,figsize=(12,4))
    for key,label in (("pure_structure_detail_distance","Detailed state"),
                       ("pure_structure_canonical_distance","Canonical groups")):
        axes[0].plot(epochs,[w[key] for w in r],label=label)
    axes[0].set_title("Rename / split / merge: deviation from source path")
    for key,label in (("within_group_change_detail_distance","Detailed state"),
                       ("within_group_change_canonical_distance","Canonical groups")):
        axes[1].plot(epochs,[w[key] for w in r],label=label)
    axes[1].set_title("Cart to checkout transfer within one group")
    for ax in axes:
        ax.set_xlabel("Replay window");ax.set_ylabel("Distance from original state");ax.legend(fontsize=8);ax.grid(alpha=.15)
    fig.suptitle("Controlled replay on measured path "+source["block_id"]+"; not new runtime events",fontsize=11)
    fig.tight_layout();save(fig,"structure-replay-v0.1.0",output)
