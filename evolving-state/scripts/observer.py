"""Passive observation of versioned attempt measurements; no scenario access."""
from __future__ import annotations

import math
import time

GROUPS = ("catalog", "currency")
PARTS = tuple((g, k) for g in GROUPS for k in ("first", "retry"))
TOLERANCE = 1e-12


def ilr(values):
    """Orthonormal Helmert coordinates, in the published fixed part order."""
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("Log-ratio coordinates require strictly positive parts")
    logs = [math.log(v) for v in values]
    return [math.sqrt(k / (k + 1)) * (sum(logs[:k]) / k - logs[k])
            for k in range(1, len(logs))]


def inverse_ilr(z):
    logs = [0.] * (len(z) + 1)
    for k, value in enumerate(z, 1):
        scale = math.sqrt(k / (k + 1))
        for j in range(k):
            logs[j] += value * scale / k
        logs[k] -= value * scale
    weights = [math.exp(v - max(logs)) for v in logs]
    return [v / sum(weights) for v in weights]


def registry(available):
    """Resolve explicit predecessor links; reject unknown or conflicting lineage."""
    known, resolved = {}, {}
    for version, doc in sorted(available.get("deployments", {}).items(), key=lambda pair: int(pair[0])):
        for name, component in doc["components"].items():
            parents = component.get("predecessors", [])
            inherited = {known[p] for p in parents if p in known}
            declared = component.get("group")
            if parents:
                if len(inherited) != 1 or any(p not in known for p in parents):
                    continue
                group = next(iter(inherited))
                if declared is not None and declared != group:
                    continue
            else:
                group = declared
            if group not in GROUPS or (name in known and known[name] != group):
                continue
            known[name] = group
            resolved[version, name] = group
    return resolved


def extract(snapshot, available, fixed=False):
    """Only received, immutable deployment documents can resolve metric labels."""
    counts = {(g, k): 0 for g, k in PARTS}
    unresolved, detail = [], []
    resolved = registry(available)
    initial_version = min(available.get("deployments", {"0": {}}), key=int)
    seen = set()
    for row in snapshot["counts"]:
        version = initial_version if fixed else str(row["deployment"])
        group = resolved.get((version, row["component"]))
        if group not in GROUPS:
            unresolved.append([row["deployment"], row["component"]])
            continue
        identity = (row["deployment"], row["component"], row["kind"])
        if (row["kind"] not in ("first", "retry") or not isinstance(row["count"], int)
                or row["count"] < 0 or identity in seen):
            raise ValueError("Invalid attempt measurement")
        seen.add(identity)
        counts[group, row["kind"]] += row["count"]
        detail.append({**row, "group": group})
    return counts, unresolved, detail


class Observer:
    def __init__(self, mode, initial, alpha=0.2):
        if mode not in ("fixed", "direct", "coda"):
            raise ValueError("Unknown observer")
        self.mode, self.initial, self.alpha = mode, initial, alpha
        self.previous = None
        self.reference = None
        self.velocity = None

    def update(self, snapshot, available):
        started = time.perf_counter_ns()
        metadata = available if self.mode != "fixed" else self.initial
        counts, missing, detail = extract(snapshot, metadata, fixed=self.mode == "fixed")
        policy_id = snapshot["policy_version"] if self.mode != "fixed" else self.initial["initial_policy"]
        policy = metadata.get("policies", {}).get(str(policy_id))
        row = {"mode": self.mode, "window": snapshot["window"],
               "diagnosed_ms": snapshot["received_ms"],
               "window_end_ms": snapshot["window_end_ms"],
               "policy_used": policy_id, "policy_announced": snapshot["policy_version"],
               "state_status": "missing_lineage" if missing else "available",
               "policy_status": "available" if policy else "missing_policy",
               "missing_lineage": missing, "detail": detail, "groups": {},
               "geometry_status": "not_requested", "geometry": None}
        for group in GROUPS:
            first, retry = counts[group, "first"], counts[group, "retry"]
            ratio = retry / (first + retry) if first + retry and not missing else None
            rho = policy["limits"].get(group) if policy else None
            status = ("missing_lineage" if missing else "no_attempts" if ratio is None
                      else "missing_policy" if rho is None else "available")
            margin = rho - ratio if status == "available" else None
            crossed = ratio > rho + TOLERANCE if status == "available" else None
            if self.mode == "coda" and status == "available" and first and retry:
                # Same physical policy, tested independently in log-odds coordinates.
                limit = math.log(rho / (1 - rho))
                odds = math.log(retry / first)
                crossed = odds > limit and ratio > rho + TOLERANCE
            current = {"first": first if not missing else None, "retry": retry if not missing else None,
                       "ratio": ratio, "rho": rho, "margin": margin, "violation": crossed,
                       "status": status, "delta_ratio": None, "delta_policy": None,
                       "delta_margin": None}
            old = self.previous["groups"][group] if self.previous else None
            adjacent = self.previous and self.previous["window"] <= snapshot["window"] <= self.previous["window"] + 1
            if adjacent and old["status"] == status == "available":
                current.update(delta_ratio=ratio - old["ratio"], delta_policy=rho - old["rho"],
                               delta_margin=margin - old["margin"])
            row["groups"][group] = current
        if self.mode == "coda":
            values = [counts[key] for key in PARTS]
            row["geometry_status"] = ("missing_lineage" if missing else "zero_part"
                                      if any(v == 0 for v in values) else "available")
            if row["geometry_status"] == "available":
                z = ilr(values)
                if self.reference is None:
                    self.reference = z
                previous = self.previous.get("geometry") if self.previous else None
                same_window = self.previous and self.previous["window"] == snapshot["window"]
                adjacent = self.previous and self.previous["window"] + 1 == snapshot["window"]
                step = [a - b for a, b in zip(z, previous["ilr"])] if previous and adjacent else None
                if same_window and previous:
                    step = previous["increment"]
                elif step is None:
                    self.velocity = None
                else:
                    self.velocity = [self.alpha * a + (1 - self.alpha) * b
                                     for a, b in zip(step, self.velocity or [0.] * len(z))]
                row["geometry"] = {"ilr": z, "displacement": [a - b for a, b in zip(z, self.reference)],
                                   "increment": step, "smoothed_increment": self.velocity,
                                   "absolute_attempts": sum(values)}
            else:
                self.velocity = None
        self.previous = row
        row["compute_ns"] = time.perf_counter_ns() - started
        return row
