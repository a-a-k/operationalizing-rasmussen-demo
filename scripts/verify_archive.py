from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SUITES = [f"probe{i}/tests" for i in range(1, 8)] + ["geometry/tests", "tests"]
IGNORED = {".git", ".venv", "__pycache__", ".pytest_cache", "artifacts",
           "upstream", "confirmation-artifacts", "protocol"}


def archive_paths(root: Path) -> list[Path]:
    if (root / ".git").exists():
        output = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root, text=True)
        return sorted({root / p for p in output.split("\0") if p})
    return sorted(p for p in root.rglob("*") if p.is_file()
                  and not (set(p.relative_to(root).parts) & IGNORED)
                  and p.relative_to(root).parts[0] != "results")


def sha256_lf(path: Path) -> str:
    data=path.read_bytes()
    return hashlib.sha256(data if path.suffix==".gz" else data.replace(b"\r\n", b"\n")).hexdigest()


def verify_checksums(root: Path) -> int:
    recorded = {}
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or relative in recorded:
            raise ValueError("Invalid or duplicate checksum path")
        if sha256_lf(path) != expected:
            raise ValueError(f"Checksum mismatch: {relative}")
        recorded[relative] = expected
    actual = {p.relative_to(root).as_posix() for p in archive_paths(root)
              if p.relative_to(root).as_posix() not in {"SHA256SUMS", "LICENSE"}}
    if set(recorded) != actual:
        raise ValueError(f"Manifest coverage mismatch: {sorted(set(recorded) ^ actual)}")
    return len(recorded)


def verify_links(root: Path) -> int:
    count = 0
    for path in archive_paths(root):
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\]\(([^\s)]+)\)", path.read_text(encoding="utf-8")):
            if target.startswith(("http:", "https:", "mailto:", "#")):
                continue
            target = unquote(target.split("#", 1)[0])
            destination = (path.parent / target).resolve()
            if not destination.is_relative_to(root.resolve()) or not destination.exists():
                raise ValueError(f"Broken local link in {path.relative_to(root)}: {target}")
            count += 1
    return count


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def verify_observation_counts(root: Path) -> None:
    p3 = read_csv(root / "probe3/results/point-level.csv")
    summary = json.loads((root / "probe3/results/summary.json").read_text())
    if len(p3) != 104 or summary["received_blocks"] != 28:
        raise ValueError("Fixed follow-up completeness mismatch")
    for arm, data in summary["arms"].items():
        for name, aggregate in data["points"].items():
            valid = [r for r in p3 if r["arm"] == arm and r["point_id"] == name and r["valid"] == "True"]
            if len(valid) != aggregate["valid_points"] or sum(r["safe"] == "False" for r in valid) != aggregate["unsafe_valid"]["K"]:
                raise ValueError(f"Fixed-endpoint aggregate mismatch: {name}")
    p4 = read_csv(root / "probe4/results/point-level.csv")
    rules = read_csv(root / "probe4/results/thresholds.csv")
    aggregate = json.loads((root / "probe4/results/comparison.json").read_text())
    if len(p4) != 120 or sum(r["valid"] == "True" for r in p4) != 109:
        raise ValueError("Threshold series completeness mismatch")
    for rate, data in aggregate["rates"].items():
        valid = [r for r in p4 if float(r["rate"]) == float(rate) and r["valid"] == "True"]
        if len(valid) != data["valid"]["n"] or sum(r["unsafe"] == "True" for r in valid) != data["valid"]["unsafe"]:
            raise ValueError(f"Threshold outcome count mismatch: {rate}")
        for method, table in data["valid"]["all_thresholds"].items():
            archived = [r for r in rules if r["rate"] == rate and r["subset"] == "valid" and r["method"] == method]
            if len(table) != len(archived):
                raise ValueError(f"Threshold rule count mismatch: {rate}/{method}")
            for expected, row in zip(table, archived):
                if json.loads(row["rule"]) != expected["rule"] or any(int(row[k]) != expected[k] for k in ("tp", "fp", "fn", "tn")):
                    raise ValueError(f"Threshold rule mismatch: {rate}/{method}")


def verify_history(root: Path) -> None:
    sys.path.insert(0, str(root / "probe5/scripts"))
    from analyze_history import analyze
    summary, history, pairs, metadata = analyze(root)
    destination = root / "probe5/results/history-v0.1.0"
    for filename, value in (("summary.json", summary), ("measurement-metadata.json", metadata)):
        if json.loads((destination / filename).read_text()) != json.loads(json.dumps(value)):
            raise ValueError(f"Saved history analysis differs: {filename}")
    for filename, rows in (("ilr-history.csv", history), ("step6-pairs.csv", pairs)):
        saved = read_csv(destination / filename)
        if len(saved) != len(rows):
            raise ValueError(f"Saved history row count differs: {filename}")
        for a, b in zip(saved, rows):
            if a != {k: str(v) for k, v in b.items()}:
                raise ValueError(f"Saved history row differs: {filename}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the archive without runtime execution.")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    files = verify_checksums(ROOT)
    links = verify_links(ROOT)
    verify_observation_counts(ROOT)
    verify_history(ROOT)
    for suite in SUITES:
        subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", suite, "-v"],
                       cwd=ROOT, check=True)
    result = {"status": "verified", "checksummed_files": files, "local_links": links,
              "test_suites": len(SUITES), "saved_data_replay": "verified",
              "runtime_started": False}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
