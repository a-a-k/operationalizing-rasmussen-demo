"""Conditional policy-boundary rays on retained causal observation histories."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path

from analyze import lines, oracle, save
from observer import GROUPS, PARTS, inverse_ilr

MODULE = Path(__file__).resolve().parents[1]
DESIGN = MODULE / "directional-design-v0.1.0.json"
EPS = 1e-12
CHECK_TOL = 1e-9
SOURCES = ("increment", "smoothed_increment")


def dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def helmert(dimension):
    return [[math.sqrt(k / (k + 1)) / k if j < k
             else -math.sqrt(k / (k + 1)) if j == k else 0.
             for j in range(dimension)] for k in range(1, dimension)]


def closed(weights):
    total = math.fsum(weights)
    return [x / total for x in weights]


def multiplicative_point(counts, unit_velocity, distance):
    logs = [math.log(x) + distance * v for x, v in zip(counts, unit_velocity)]
    shift = max(logs)
    return closed([math.exp(x - shift) for x in logs])


def direct_ratio(counts, unit_velocity, distance, first, retry):
    # Pair normalization avoids underflow caused by unrelated dominating parts.
    a = math.log(counts[first]) + distance * unit_velocity[first]
    b = math.log(counts[retry]) + distance * unit_velocity[retry]
    shift = max(a, b)
    f, r = math.exp(a - shift), math.exp(b - shift)
    return r / (f + r)


def orientation(value):
    return "toward" if value > EPS else "away" if value < -EPS else "tangent"


def finish_ray(groups, speed):
    violated = [g for g, row in groups.items() if row["current_violation"]]
    contacts = {g: row["exit_distance"] for g, row in groups.items()
                if row["exit_distance"] is not None and not row["current_violation"]}
    if violated:
        status, distance, first = "already_violated", 0., []
    elif speed <= EPS:
        status, distance, first = "stationary", None, []
    elif not contacts:
        status, distance, first = "no_forward_crossing", None, []
    else:
        distance = min(contacts.values())
        first = [g for g, s in contacts.items()
                 if math.isclose(s, distance, rel_tol=CHECK_TOL, abs_tol=CHECK_TOL)]
        status = "immediate_exit" if distance <= EPS else "finite_exit"
    return {"status": status, "distance": distance, "first_constraints": first,
            "currently_violated": violated, "velocity_norm": speed, "groups": groups}


def ilr_ray(z, velocity, limits):
    """Analytic intersection of one unit ILR ray with fixed ratio policies."""
    if len(z) != 3 or len(velocity) != 3 or not all(math.isfinite(x) for x in z + velocity):
        raise ValueError("Expected finite complete three-coordinate state and direction")
    if set(limits) != set(GROUPS) or not all(0 < x < 1 for x in limits.values()):
        raise ValueError("Policies must be strictly between zero and one")
    speed = norm(velocity)
    direction = [v / speed for v in velocity] if speed > EPS else [0.] * len(z)
    basis = helmert(4)
    groups = {}
    for index, group in enumerate(GROUPS):
        first, retry = index * 2, index * 2 + 1
        normal = [row[retry] - row[first] for row in basis]
        log_odds, slope = dot(normal, z), dot(normal, direction)
        rho = limits[group]
        boundary = math.log(rho / (1 - rho))
        gap = boundary - log_odds
        ratio = 1 / (1 + math.exp(-log_odds)) if log_odds >= 0 else math.exp(log_odds) / (1 + math.exp(log_odds))
        violation = ratio > rho + EPS
        distance = max(0., gap) / slope if slope > EPS and not violation else None
        groups[group] = {"ratio": ratio, "rho": rho, "current_violation": violation,
                         "signed_perpendicular_distance": gap / math.sqrt(2),
                         "direction": orientation(slope), "log_odds_slope": slope,
                         "exit_distance": distance}
    result = finish_ray(groups, speed)
    result["unit_direction"] = direction
    result["intersection_composition"] = (inverse_ilr([a + result["distance"] * b
                                                       for a, b in zip(z, direction)])
                                         if result["status"] in ("finite_exit", "immediate_exit") else None)
    return result


def direct_ray(counts, velocity, limits):
    """Independent root search on original parts; no ILR or analytic root formula."""
    if len(counts) != 4 or len(velocity) != 4 or any(x <= 0 for x in counts):
        raise ValueError("Expected four positive parts and a four-part velocity")
    if not all(math.isfinite(x) for x in counts + velocity):
        raise ValueError("Nonfinite direct input")
    if set(limits) != set(GROUPS) or not all(0 < x < 1 for x in limits.values()):
        raise ValueError("Invalid direct policies")
    mean = math.fsum(velocity) / len(velocity)
    velocity = [v - mean for v in velocity]
    speed = norm(velocity)
    direction = [v / speed for v in velocity] if speed > EPS else [0.] * len(velocity)
    groups = {}
    for index, group in enumerate(GROUPS):
        f, r = index * 2, index * 2 + 1
        rho = limits[group]
        ratio = counts[r] / (counts[f] + counts[r])
        slope = direction[r] - direction[f]
        violation = ratio > rho + EPS
        distance = None
        if slope > EPS and not violation:
            if ratio >= rho:
                distance = 0.
            else:
                lower, upper = 0., 1.
                for _ in range(128):
                    if direct_ratio(counts, direction, upper, f, r) >= rho:
                        break
                    upper *= 2
                else:
                    raise ValueError("Could not bracket a finite direct crossing")
                for _ in range(100):
                    middle = (lower + upper) / 2
                    if direct_ratio(counts, direction, middle, f, r) < rho:
                        lower = middle
                    else:
                        upper = middle
                distance = (lower + upper) / 2
        groups[group] = {"ratio": ratio, "rho": rho, "current_violation": violation,
                         "direction": orientation(slope), "log_odds_slope": slope,
                         "exit_distance": distance}
    result = finish_ray(groups, speed)
    result["unit_direction"] = direction
    result["intersection_composition"] = (multiplicative_point(counts, direction, result["distance"])
                                         if result["status"] in ("finite_exit", "immediate_exit") else None)
    return result


class DirectHistory:
    """Causal centered-log readout from independently reconstructed event counts."""
    def __init__(self, alpha):
        self.alpha = alpha
        self.previous = None
        self.velocity = None

    def update(self, window, counts, available):
        current = None
        if available:
            logs = [math.log(x) for x in counts]
            mean = math.fsum(logs) / len(logs)
            current = {"logs": [x - mean for x in logs], "increment": None}
            old = self.previous
            if old and old["data"] and old["window"] == window:
                current["increment"] = old["data"]["increment"]
            elif old and old["data"] and old["window"] + 1 == window:
                step = [x - y for x, y in zip(current["logs"], old["data"]["logs"])]
                current["increment"] = step
                self.velocity = [self.alpha * a + (1 - self.alpha) * b
                                 for a, b in zip(step, self.velocity or [0.] * len(step))]
            else:
                self.velocity = None
            current["smoothed_increment"] = self.velocity
        else:
            self.velocity = None
        self.previous = {"window": window, "data": current}
        return current


def verify_ray(analytic, direct):
    errors = {}
    for key in ("status", "first_constraints", "currently_violated"):
        if analytic[key] != direct[key]:
            raise ValueError(f"Independent ray classification differs: {key}")
    for group in GROUPS:
        a, b = analytic["groups"][group], direct["groups"][group]
        for key in ("direction", "current_violation"):
            if a[key] != b[key]:
                raise ValueError(f"Independent direction differs: {group}/{key}")
        for key in ("ratio", "log_odds_slope", "exit_distance"):
            x, y = a[key], b[key]
            if (x is None) != (y is None):
                raise ValueError("Crossing availability differs")
            if x is not None:
                if not math.isclose(x, y, rel_tol=CHECK_TOL, abs_tol=CHECK_TOL):
                    raise ValueError(f"Independent ray value differs: {group}/{key}")
                errors[key] = max(errors.get(key, 0.), abs(x - y))
    a, b = analytic["intersection_composition"], direct["intersection_composition"]
    errors["intersection_composition"] = max((abs(x - y) for x, y in zip(a, b)), default=0.) if a else 0.
    if errors["intersection_composition"] > CHECK_TOL:
        raise ValueError("Independent intersection compositions differ")
    if not math.isclose(analytic["velocity_norm"], direct["velocity_norm"],
                        rel_tol=CHECK_TOL, abs_tol=CHECK_TOL):
        raise ValueError("Velocity norms differ")
    return errors


def history(directory):
    if not json.loads((directory / "status.json").read_text())["complete"]:
        raise ValueError("Cannot treat an incomplete runtime history as a complete replay")
    config = json.loads((directory / "load-config.json").read_text())
    events = lines(directory / "journals/client.jsonl")
    inputs, reports = lines(directory / "observer-inputs.jsonl"), lines(directory / "diagnoses.jsonl")
    if len(inputs) != len(reports):
        raise ValueError("Input/report count mismatch")
    state = DirectHistory(config["ewma_alpha"])
    records = []
    for index, (item, batch) in enumerate(zip(inputs, reports)):
        row = next(r for r in batch["rows"] if r["mode"] == "coda")
        snapshot = item["snapshot"]
        truth = oracle(events, snapshot, config["origin_ms"], config["window_seconds"] * 1000)
        counts = [truth["groups"][g][k] for g, k in PARTS]
        geometry = row["geometry"]
        raw = state.update(row["window"], counts, geometry is not None)
        if geometry:
            recovered = inverse_ilr(geometry["ilr"])
            if max(abs(x - y) for x, y in zip(recovered, closed(counts))) > CHECK_TOL:
                raise ValueError("Recorded geometry disagrees with individual events")
        limits = {g: truth["groups"][g]["rho"] for g in GROUPS}
        valid_policy = all(row["groups"][g]["status"] == "available" for g in GROUPS)
        if valid_policy and any(abs(row["groups"][g]["rho"] - limits[g]) > EPS for g in GROUPS):
            raise ValueError("Recorded policy disagrees with actual application")
        record = {"history": directory.name, "report_index": index, "window": row["window"],
                  "observed_ms": row["diagnosed_ms"], "policy_version": row["policy_used"],
                  "geometry_status": row["geometry_status"], "policy_status": row["policy_status"],
                  "event_counts": counts, "groups": truth["groups"], "directions": {}}
        for source in SOURCES:
            velocity = geometry[source] if geometry else None
            raw_velocity = raw[source] if raw else None
            if (velocity is None) != (raw_velocity is None):
                raise ValueError("Causal direction availability differs")
            if not geometry:
                result = {"availability": row["geometry_status"]}
            elif velocity is None:
                result = {"availability": "no_adjacent_direction"}
            elif not valid_policy:
                result = {"availability": "missing_policy"}
            else:
                analytic = ilr_ray(geometry["ilr"], velocity,
                                   {g: row["groups"][g]["rho"] for g in GROUPS})
                direct = direct_ray(counts, raw_velocity, limits)
                result = {"availability": "available", "ilr": analytic, "direct": direct,
                          "verification_errors": verify_ray(analytic, direct)}
            record["directions"][source] = result
        records.append(record)
    return records


def identifier(row):
    return {k: row[k] for k in ("history", "window", "report_index", "policy_version")}


def matched_states(records):
    # Equal local counts/policy, not equal complete compositions.
    buckets = defaultdict(list)
    seen = set()
    for row in records:
        result = row["directions"]["increment"]
        if result["availability"] != "available":
            continue
        for group in GROUPS:
            key = (row["history"], row["window"], row["policy_version"], group)
            if key in seen:
                continue
            seen.add(key)
            g = row["groups"][group]
            buckets[group, g["first"], g["retry"], g["rho"]].append(row)
    pairs = []
    for (group, first, retry, rho), rows in sorted(buckets.items()):
        for a, b in itertools.combinations(rows, 2):
            if (a["history"], a["window"]) == (b["history"], b["window"]):
                continue
            directions = [r["directions"]["increment"]["ilr"]["groups"][group]["direction"] for r in (a, b)]
            if set(directions) == {"toward", "away"}:
                pairs.append({"group": group, "first": first, "retry": retry, "rho": rho,
                              "a": identifier(a), "a_direction": directions[0],
                              "b": identifier(b), "b_direction": directions[1],
                              "local_policy_satisfied": not a["groups"][group]["violation"],
                              "all_policies_satisfied_in_both": all(
                                  not row["groups"][g]["violation"] for row in (a, b) for g in GROUPS)})
    return pairs


def policy_only(records):
    witnesses = []
    for a, b in zip(records, records[1:]):
        if (a["history"] != b["history"] or a["window"] != b["window"]
                or a["event_counts"] != b["event_counts"] or a["policy_version"] == b["policy_version"]):
            continue
        changes = {}
        for source in SOURCES:
            old, new = a["directions"][source], b["directions"][source]
            if old["availability"] != "available" or new["availability"] != "available":
                changes[source] = {"availability": "not_comparable"}
                continue
            old, new = old["ilr"], new["ilr"]
            if old["unit_direction"] != new["unit_direction"]:
                raise ValueError("Policy-only re-evaluation changed the measured direction")
            changes[source] = {
                "availability": "available", "direction_unchanged": True,
                "old_status": old["status"], "new_status": new["status"],
                "old_distance": old["distance"], "new_distance": new["distance"],
                "old_first_constraints": old["first_constraints"],
                "new_first_constraints": new["first_constraints"],
            }
        witnesses.append({"a": identifier(a), "b": identifier(b), "directions": changes,
                          "current_policy_status_changed": any(
                              a["groups"][g]["violation"] != b["groups"][g]["violation"] for g in GROUPS)})
    return witnesses


def summarize(records, pairs):
    summary = {"histories": len({r["history"] for r in records}), "report_batches": len(records),
               "geometry_available": sum(r["geometry_status"] == "available" for r in records),
               "sources": {}, "matched_local_state_opposite_direction_pairs": len(pairs),
               "matched_pairs_with_all_policies_satisfied": sum(p["all_policies_satisfied_in_both"] for p in pairs),
               "matched_pairs_are_independent_trials": False, "runtime_started": False}
    for source in SOURCES:
        results = [r["directions"][source] for r in records]
        available = [r for r in results if r["availability"] == "available"]
        errors = {key: max((r["verification_errors"].get(key, 0.) for r in available), default=0.)
                  for key in ("ratio", "log_odds_slope", "exit_distance", "intersection_composition")}
        summary["sources"][source] = {
            "availability": dict(Counter(r["availability"] for r in results)),
            "ray_status": dict(Counter(r["ilr"]["status"] for r in available)),
            "first_constraints": dict(Counter("+".join(r["ilr"]["first_constraints"]) for r in available
                                               if r["ilr"]["first_constraints"])),
            "maximum_absolute_verification_errors": errors,
            "independent_checks": len(available),
        }
    both = [r for r in records if all(r["directions"][s]["availability"] == "available" for s in SOURCES)]
    summary["instant_smoothed_direction_disagreements"] = sum(
        r["directions"][SOURCES[0]]["ilr"]["groups"][g]["direction"] !=
        r["directions"][SOURCES[1]]["ilr"]["groups"][g]["direction"]
        for r in both for g in GROUPS)
    summary["instant_smoothed_strict_opposites"] = sum(
        {r["directions"][s]["ilr"]["groups"][g]["direction"] for s in SOURCES} == {"toward", "away"}
        for r in both for g in GROUPS)
    safe = [r for r in both if not any(r["groups"][g]["violation"] for g in GROUPS)]
    summary["direction_available_and_all_policies_satisfied"] = len(safe)
    comparison = Counter()
    for row in safe:
        a, b = [row["directions"][s]["ilr"] for s in SOURCES]
        finite_a, finite_b = a["distance"] is not None, b["distance"] is not None
        label = ("both_finite_same_first" if a["first_constraints"] == b["first_constraints"]
                 else "both_finite_different_first") if finite_a and finite_b else (
            "only_last_increment_finite" if finite_a else "only_smoothed_finite" if finite_b else "neither_finite")
        comparison[label] += 1
    summary["safe_report_direction_comparison"] = dict(comparison)
    summary["same_window_policy_only"] = policy_only(records)
    summary["example_reports"] = [r for r in records
                                  if (r["history"], r["window"]) in (("history-01", 10), ("history-03", 14))
                                  and r["groups"]["catalog"]["rho"] == .5]
    summary["per_history"] = [{
        "history": name,
        "reports": sum(r["history"] == name for r in records),
        **{source: dict(Counter(r["directions"][source]["ilr"]["status"]
                               for r in records if r["history"] == name
                               and r["directions"][source]["availability"] == "available"))
           for source in SOURCES}
    } for name in sorted({r["history"] for r in records})]
    return summary


def analyze(bundle):
    records = [row for directory in sorted((bundle / "inputs").glob("history-*"))
               for row in history(directory)]
    if not records:
        raise ValueError("No histories found")
    pairs = matched_states(records)
    return summarize(records, pairs), records, pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=MODULE / "results/campaign-v0.1.1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary, records, pairs = analyze(args.bundle)
    save(args.output / "summary.json", summary)
    save(args.output / "reports.json", records)
    save(args.output / "matched-local-states.json", pairs)
    hashes = {p.relative_to(args.bundle).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((args.bundle / "inputs").rglob("*")) if p.is_file()}
    save(args.output / "provenance.json",
         {"analysis_design_sha256": hashlib.sha256(DESIGN.read_bytes()).hexdigest(),
          "source_files_sha256": hashes, "analysis_kind": "retrospective", "runtime_started": False})
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("example_reports", "per_history", "same_window_policy_only")}, indent=2))


if __name__ == "__main__":
    main()
