"""Compare a scratch numerical replay with the versioned CSV/JSON archive."""
import argparse
import csv
import json
import math
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[1]/"results/v0.1.0"


def equal(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if a == b:
        return True
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-11, abs_tol=1e-12)
    except (TypeError, ValueError):
        return False


def load(path):
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    checked = []
    for reference in sorted(ARCHIVE.iterdir()):
        if reference.suffix not in {".csv", ".json"}:
            continue
        replayed = args.output_dir/reference.name
        if not replayed.is_file() or not equal(load(reference), load(replayed)):
            raise ValueError("Replay mismatch: "+reference.name)
        checked.append(reference.name)
    if not checked:
        raise ValueError("No archived numerical files")
    print(json.dumps({"status": "matching", "numerical_files": len(checked),
                      "absolute_tolerance": 1e-12, "relative_tolerance": 1e-11}))


if __name__ == "__main__":
    main()
