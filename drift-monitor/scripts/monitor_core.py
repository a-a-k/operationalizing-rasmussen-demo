"""Complete relative CPU state, native counter integration and matched MEWMA."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "drift-monitor/design-v0.1.0.json"
METHODS = ("raw_composition", "ilr_composition")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def matrix(phase):
    cfg = load(DESIGN)
    rows = []
    for context_index, context in enumerate(cfg["initial_states"]):
        cell = []
        for rep in range(1, 6):
            bid = context + "-r" + str(rep)
            cell.append({"block_id": bid, "context": context, "repetition": rep,
                         "role": "test" if phase == "test" else "fit" if rep in cfg["fit_repetitions"] else "calibration",
                         "order": ["background"]})
        ranked = sorted(cell, key=lambda r: hashlib.sha256((cfg["randomization_salt"] + ":" + r["block_id"]).encode()).digest())
        if phase == "test":
            for i, row in enumerate(ranked):
                row["order"] = ["drift", "control"] if (i + context_index) % 2 == 0 else ["control", "drift"]
        rows.extend(cell)
    return rows


def helmert(parts):
    result = np.zeros((parts - 1, parts))
    for k in range(1, parts):
        result[k - 1, :k] = 1 / math.sqrt(k * (k + 1))
        result[k - 1, k] = -k / math.sqrt(k * (k + 1))
    return result


def close(cpu):
    cpu = np.asarray(cpu, dtype=float)
    if not np.isfinite(cpu).all() or np.any(cpu <= 0):
        raise ValueError("CPU observations must be finite and positive")
    return cpu / cpu.sum(axis=-1, keepdims=True)


def coordinates(cpu, method):
    x = close(cpu)
    return (x if method == "raw_composition" else np.log(x)) @ helmert(x.shape[-1]).T


def feature(cpu, reference, method):
    return coordinates(cpu, method) - coordinates(reference, method)


def allocation(context, step=0):
    cfg = load(DESIGN)
    changes = cfg["initial_states"][context]
    cpu = {p: Decimal(str(q)) + Decimal(str(changes.get(p, 0))) for p, q in zip(cfg["parts"], cfg["reference_cpu"])}
    amount = Decimal(str(cfg["cpu_step_per_donor"])) * step
    for donor in cfg["donors"]:
        cpu[donor] -= amount
    cpu[cfg["receiver"]] += amount * len(cfg["donors"])
    assert sum(cpu.values()) == Decimal("3.4") and min(cpu.values()) >= Decimal("0.08")
    return {"cpu": {p: float(q) for p, q in cpu.items()},
            "memory": {p: mib * 2**20 for p, mib in zip(cfg["parts"], cfg["reference_memory_mib"])}}


def timing(cfg):
    start = cfg["warmup_seconds"] + cfg["reference_seconds"]
    cycle = cfg["guard_seconds"] + cfg["window_seconds"]
    return [{"epoch": i + 1, "slot_start": start + i * cycle,
             "measurement_start": start + i * cycle + cfg["guard_seconds"],
             "measurement_end": start + (i + 1) * cycle} for i in range(cfg["monitor_windows"])]


class SampleReader:
    def __init__(self, path):
        self.path, self.offset, self.frames = Path(path), 0, []

    def refresh(self):
        with self.path.open(encoding="utf-8") as stream:
            stream.seek(self.offset)
            while True:
                before = stream.tell()
                line = stream.readline()
                if not line.endswith("\n"):
                    self.offset = before
                    break
                row = json.loads(line)
                row["wall_seconds"] = dt.datetime.fromisoformat(row["timestamp"]).timestamp()
                self.frames.append(row)
                self.offset = stream.tell()


def integrate(frames, parts, left, right, minimum_coverage=.95):
    """Integrate native CPU-second increments; prorate only boundary intervals."""
    seconds, covered = np.zeros(len(parts)), np.zeros(len(parts))
    for before, after in zip(frames, frames[1:]):
        a, b = before["wall_seconds"], after["wall_seconds"]
        overlap = max(0., min(right, b) - max(left, a))
        if overlap == 0 or b <= a:
            continue
        for j, part in enumerate(parts):
            old = before["containers"].get(part, {})
            new = after["containers"].get(part, {})
            delta = new.get("delta")
            if not delta or old.get("identity") != new.get("identity"):
                continue
            used = delta.get("cpu_seconds")
            if not isinstance(used, (int, float)) or not math.isfinite(used) or used < 0:
                continue
            seconds[j] += used * overlap / (b - a)
            covered[j] += overlap
    cpu = seconds / (right - left)
    coverage = covered / (right - left)
    valid = bool(np.all(coverage >= minimum_coverage) and np.all(cpu > 0) and np.isfinite(cpu).all())
    return {"cpu": cpu.tolist(), "coverage": coverage.tolist(), "valid": valid,
            "start_ms": left * 1000, "end_ms": right * 1000}


def settling(a, b, cfg):
    valid = a["valid"] and b["valid"]
    distance = float(np.linalg.norm(feature(b["cpu"], a["cpu"], "ilr_composition"))) if valid else None
    ratio = sum(b["cpu"]) / sum(a["cpu"]) if valid else None
    limit = cfg["settling"]["maximum_total_cpu_ratio"]
    return {"passed": bool(valid and distance <= cfg["settling"]["maximum_aitchison_distance"] and 1 / limit <= ratio <= limit),
            "aitchison_distance": distance, "total_cpu_ratio": ratio, "blocks": [a, b],
            "meaning": "Engineering settling check, not proof of stationarity"}


class Observer:
    def __init__(self, frozen, reference):
        self.frozen, self.reference, self.t = frozen, reference, 0
        self.state = {m: np.zeros(len(reference) - 1) for m in METHODS}

    def update(self, cpu):
        self.t += 1
        lam = self.frozen["lambda"]
        factor = lam / (2 - lam) * (1 - (1 - lam) ** (2 * self.t))
        output = {}
        for method in METHODS:
            spec = self.frozen["methods"][method]
            y = feature(cpu, self.reference, method)
            self.state[method] = lam * (y - np.array(spec["mean"])) + (1 - lam) * self.state[method]
            z = self.state[method]
            score = float(z @ np.linalg.solve(np.array(spec["covariance"]), z) / factor)
            output[method] = {"score": score, "threshold": spec["threshold"], "signal": score > spec["threshold"]}
        return output


def fit_background(jobs):
    cfg = load(DESIGN)
    fit = [j for j in jobs if j["role"] == "fit" and j["histories"]["background"]["qualified"]]
    cal = [j for j in jobs if j["role"] == "calibration" and j["histories"]["background"]["qualified"]]
    if len(fit) < cfg["minimum_fit_histories"] or len(cal) < cfg["minimum_calibration_histories"]:
        raise ValueError("Insufficient qualified background histories; test must not start")
    if any({j["context"] for j in group} != set(cfg["initial_states"]) for group in (fit, cal)):
        raise ValueError("Each background partition must retain every initial context")
    frozen = {"version": cfg["version"], "design_sha256_lf": digest(DESIGN), "lambda": cfg["ewma_lambda"], "methods": {},
              "fit_ids": [j["block_id"] for j in fit], "calibration_ids": [j["block_id"] for j in cal]}
    for method in METHODS:
        y = np.array([feature(w["cpu"], j["histories"]["background"]["reference"]["cpu"], method)
                      for j in fit for w in j["histories"]["background"]["observations"]])
        covariance = np.cov(y, rowvar=False)
        eig = np.linalg.eigvalsh(covariance)
        if eig.min() <= 0:
            raise ValueError("Full covariance is not positive definite")
        frozen["methods"][method] = {"mean": y.mean(axis=0).tolist(), "covariance": covariance.tolist(),
                                     "threshold": 1., "condition_number": float(eig.max() / eig.min())}
    for method in METHODS:
        maxima = []
        for job in cal:
            history = job["histories"]["background"]
            observer = Observer(frozen, history["reference"]["cpu"])
            maxima.append(max(observer.update(w["cpu"])[method]["score"] for w in history["observations"]))
        frozen["methods"][method]["threshold"] = float(np.quantile(maxima, 1 - cfg["nominal_calibration_history_signal_budget"], method="higher"))
        frozen["methods"][method]["calibration_maxima"] = maxima
    return frozen
