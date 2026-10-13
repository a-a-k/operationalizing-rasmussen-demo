from __future__ import annotations

import hashlib
import math
from decimal import Decimal


def initial_state(design: dict, name: str) -> dict:
    selected = next(r for r in design["initial_states"] if r["id"] == name)
    result = {}
    for resource, values, changes in (
        ("cpu", design["reference_cpu"], selected["cpu_changes"]),
        ("memory", [v * 2**20 for v in design["reference_memory_mib"]], selected["memory_changes_mib"]),
    ):
        multiplier = 2**20 if resource == "memory" else 1
        result[resource] = {p: float(Decimal(str(v)) + Decimal(str(changes.get(p, 0))) * multiplier)
                            for p, v in zip(design["parts"], values)}
        if resource == "memory":
            result[resource] = {p: int(v) for p, v in result[resource].items()}
    return result


def matrix(design: dict) -> list[dict]:
    rows = []
    for state in design["initial_states"]:
        for profile in design["profiles"]:
            for repetition in range(1, design["repetitions"] + 1):
                bid = f'{state["id"]}-{profile["id"]}-{repetition:02d}'
                rows.append({"block_id": bid, "initial_state": state["id"],
                             "profile": profile["id"], "repetition": repetition})
    ranked = sorted(r["block_id"] for r in rows)
    ranked.sort(key=lambda b: hashlib.sha256((design["randomization_salt"] + ":" + b).encode()).digest())
    for row in rows:
        row["order"] = ["adaptive", "control"] if ranked.index(row["block_id"]) % 2 == 0 else ["control", "adaptive"]
    return rows


def close(q: dict, parts: list[str]) -> list[float]:
    values = [float(q[p]) for p in parts]
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("Allocations must be positive and finite")
    total = math.fsum(values)
    return [v / total for v in values]


def helmert(values: list[float]) -> list[float]:
    logs = [math.log(v) for v in values]
    return [(math.fsum(logs[:k]) - k * logs[k]) / math.sqrt(k * (k + 1))
            for k in range(1, len(values))]


def representation(state: dict, design: dict) -> dict:
    shares = {r: close(state[r], design["parts"]) for r in ("cpu", "memory")}
    return {"shares": shares, "ilr": helmert(shares["cpu"]) + helmert(shares["memory"]),
            "local": [math.log(state[r][a] / state[r][b]) / math.sqrt(2) for r, a, b in design["local_ratios"]]}


def proposal(state: dict, resource: str, donor: str, receiver: str, amount: float) -> dict:
    result = {r: dict(q) for r, q in state.items()}
    changed = {p: Decimal(str(v)) for p, v in result[resource].items()}
    changed[donor] -= Decimal(str(amount))
    changed[receiver] += Decimal(str(amount))
    if min(changed.values()) <= 0 or sum(changed.values()) != sum(Decimal(str(v)) for v in state[resource].values()):
        raise ValueError("Transfer violates a positive closed budget")
    result[resource] = {p: int(v) if resource == "memory" else float(v) for p, v in changed.items()}
    return result


def choose(state: dict, previous: dict, design: dict, blocked: set[tuple[str, str]]) -> dict | None:
    c = design["controller"]
    if not previous["valid"] or not previous["safe"]:
        return None
    candidates = []
    receiver = c["receiver"]
    resource_data = previous.get("resources", {})
    for resource in c["active_resources"]:
        demand = resource_data.get(receiver, {})
        if resource == "cpu" and (demand.get("throttling") or 0) <= 0:
            continue
        if resource == "memory" and demand.get("memory_fraction", 0) < 0.80:
            continue
        amount = c["cpu_step"] if resource == "cpu" else c["memory_step_mib"] * 2**20
        for donor, processes in c["dependencies"].items():
            if (resource, donor) in blocked:
                continue
            margin = min(previous["headroom"][p] for p in processes)
            if margin < c["donor_headroom"]:
                continue
            floor = c["minimum_cpu"] if resource == "cpu" else c["minimum_memory_mib"] * 2**20
            if state[resource][donor] - amount < floor:
                continue
            measured = resource_data.get(donor, {})
            if resource == "cpu" and measured.get("cpu_cores") is None:
                continue
            if resource == "memory":
                used = measured.get("memory_peak_bytes")
                if used is None or state[resource][donor] - amount < used * c["memory_reserve_factor"]:
                    continue
            spare = 1 - measured.get("cpu_cores", 0) / state["cpu"][donor] if resource == "cpu" else 1 - measured["memory_peak_bytes"] / state["memory"][donor]
            candidates.append((margin, spare, donor, resource, amount))
    if not candidates:
        return None
    _, _, donor, resource, amount = max(candidates)
    return {"resource": resource, "donor": donor, "receiver": receiver, "amount": amount}
