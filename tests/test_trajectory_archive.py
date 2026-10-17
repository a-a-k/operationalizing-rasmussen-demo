"""Standard-library integrity checks for the descriptive trajectory archive."""
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT/"drift-monitor/trajectory-observability"
RESULTS = MODULE/"results/v0.1.0"


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TrajectoryArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = read(RESULTS/"summary.json")
        cls.adaptation = rows(RESULTS/"adaptation-windows.csv")

    def test_complete_source_membership_and_previous_attempts_retained(self):
        selected = rows(MODULE/"inputs/selected-cases.csv")
        attempts = rows(MODULE/"inputs/attempt-ledger.csv")
        self.assertEqual(len(selected), 250)
        self.assertEqual(len(attempts), 273)
        self.assertEqual(sum(r["selected_first_qualified"] == "True" for r in attempts), 250)
        self.assertEqual(Counter(r["source_run"] for r in selected),
                         {"38996401485": 230, "39018127810": 17, "39037712685": 3})
        with gzip.open(MODULE/"inputs/continuous-selected.jsonl.gz", "rt", encoding="utf-8") as stream:
            jobs = [json.loads(line) for line in stream]
        provenance = read(MODULE/"inputs/continuous-provenance.json")
        self.assertEqual(len(jobs), 250)
        self.assertEqual(len(provenance), 250)
        self.assertEqual([r["block_id"] for r in selected], [j["block_id"] for j in jobs])
        for r, j, source in zip(selected, jobs, provenance):
            self.assertEqual(str(j["run_id"]), r["source_run"])
            self.assertEqual(str(j["run_attempt"]), r["source_attempt"])
            self.assertEqual(source["block_id"], j["block_id"])
            for h in j["histories"].values():
                self.assertTrue(h["qualified"])
                self.assertEqual(len(h["observations"]), 16)
                self.assertTrue(all(w["valid"] and w["quota_valid"] for w in h["observations"]))

    def test_native_sources_and_all_windows_remain(self):
        self.assertEqual(len(self.adaptation), 988)
        histories = read(RESULTS/"adaptation-histories.json")
        self.assertEqual(len(histories), 48)
        short = [h for h in histories if h["windows"] != 21]
        self.assertEqual(len(short), 1)
        self.assertEqual((short[0]["block_id"], short[0]["policy"], short[0]["windows"]),
                         ("ledger-busy-01", "control", 1))
        self.assertEqual(short[0]["stop_reason"], "baseline_not_valid_and_safe")
        sources = read(RESULTS/"adaptation-native-provenance.json")
        self.assertEqual(len(sources), 48)
        for source in sources:
            path = (MODULE/source["native_source"]).resolve()
            self.assertTrue(path.is_relative_to((MODULE/"inputs/native").resolve()))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source["native_sha256"])
        native = rows(RESULTS/"native-replay.csv")
        self.assertEqual(len(native), 988)
        self.assertLess(max(float(r["maximum_mean_replay_error"]) for r in native), 1e-12)
        self.assertTrue(all(float(r["minimum_counter_coverage"]) == 1 for r in native))

    def test_displacement_increment_and_smoothing_are_separate(self):
        parts = read(ROOT/"drift-monitor/design-v0.1.0.json")["parts"]
        groups = defaultdict(list)
        for row in self.adaptation:
            groups[row["block_id"], row["policy"]].append(row)
        for group in groups.values():
            group.sort(key=lambda r: int(r["epoch"]))
            for quantity in ("quota", "usage"):
                previous = [0.0]*len(parts)
                smooth = [0.0]*len(parts)
                for row in group:
                    for i, part in enumerate(parts):
                        current = float(row[quantity+"_displacement_clr_"+part])
                        step = float(row[quantity+"_increment_clr_"+part])
                        self.assertAlmostEqual(step, current-previous[i], places=11)
                        smooth[i] = .2*step+.8*smooth[i]
                        self.assertAlmostEqual(float(row[quantity+"_ewma_increment_clr_"+part]), smooth[i], places=11)
                        previous[i] = current
        events = rows(RESULTS/"adaptation-events.csv")
        self.assertEqual(Counter(r["action"] for r in events), {"hold": 4, "restore": 5})
        for row in events:
            if row["action"] == "hold":
                self.assertAlmostEqual(float(row["quota_increment_norm"]), 0)
                self.assertGreater(float(row["quota_displacement_norm"]), 0)
                self.assertGreater(float(row["usage_increment_norm"]), 0)
            else:
                self.assertAlmostEqual(float(row["quota_displacement_norm"]), 0)
                self.assertGreater(float(row["usage_displacement_norm"]), 0)
                self.assertLess(float(row["usage_displacement_change"]), 0)
                self.assertEqual(row["safe"], "True")

    def test_paired_descriptive_summary_matches_each_history(self):
        histories = rows(RESULTS/"continuous-histories.csv")
        self.assertEqual(len(histories), 500)
        grouped = defaultdict(dict)
        for h in histories:
            grouped[h["block_id"]][h["policy"]] = float(h["post4_relative_path_coherence"])
        differences = [h["drift"]-h["control"] for h in grouped.values()]
        self.assertEqual(len(differences), 250)
        self.assertEqual(sum(v > 0 for v in differences), 224)
        summary = self.summary["continuous"]
        self.assertEqual(summary["pairs_with_higher_coherence_during_reallocation"], 224)
        self.assertAlmostEqual(sum(differences)/250, summary["paired_coherence_difference"]["mean"], places=12)
        with (RESULTS/"continuous-windows.csv").open(encoding="utf-8", newline="") as stream:
            self.assertEqual(sum(1 for _ in csv.DictReader(stream)), 8000)

    def test_structural_replay_keeps_detail_not_only_group_sums(self):
        replay = rows(RESULTS/"structure-replay.csv")
        self.assertEqual(len(replay), 4000)
        self.assertLess(max(float(r["pure_structure_detail_distance"]) for r in replay), 1e-12)
        self.assertLess(max(float(r["within_group_change_canonical_distance"]) for r in replay), 1e-12)
        self.assertTrue(all(float(r["within_group_change_detail_distance"]) > .3
                            for r in replay if int(r["epoch"]) >= 10))
        self.assertEqual(sum(r["unknown_lineage_gated"] == "True" for r in replay), 250)

    def test_bundled_inputs_and_sources_contain_no_personal_paths(self):
        forbidden = ("C:\\Users\\", "C:/Users/", "@gmail.com", "@example.invalid",
                     "analysis/continuous_case_audit", "arxiv.org", ".tex\"")
        for path in MODULE.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix == ".gz":
                with gzip.open(path, "rt", encoding="utf-8") as stream:
                    content = stream.read()
            elif path.suffix in {".md", ".py", ".json", ".csv", ".svg", ".txt"}:
                content = path.read_text(encoding="utf-8")
            else:
                continue
            for value in forbidden:
                self.assertNotIn(value, content, path.relative_to(MODULE).as_posix())


if __name__ == "__main__":
    unittest.main()
