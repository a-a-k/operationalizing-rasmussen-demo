from __future__ import annotations

import copy
import gzip
import json
import math
import ast
import io
import re
import subprocess
import sys
import tempfile
import tokenize
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe3/scripts"))
from study import DESIGN, RUNTIME, VERSION, features, generator_valid, load, matrix, validate, verify
from measure import quantile, summarize
from observe import checked_delta
from analyze import analyze, pair_counts, save
import run_block


class DesignTests(unittest.TestCase):
    def setUp(self):
        self.design, self.runtime = load(ROOT / DESIGN), load(ROOT / RUNTIME)

    def test_fixed_inputs_and_action_pins(self):
        self.assertTrue(verify(ROOT)["valid"])

    def test_matrix_deterministic_and_position_balanced(self):
        rows = matrix(self.design)
        self.assertEqual(rows, matrix(self.design))
        self.assertEqual(len(rows), 28)
        self.assertEqual(sum(len(row["order"]) for row in rows), 104)
        for key, arm in self.design["arms"].items():
            selected = [r for r in rows if r["arm"] == key]
            for i in range(len(arm["points"])):
                self.assertEqual(set(Counter(r["order"][i] for r in selected).values()),
                                 {arm["blocks"] // len(arm["points"])})

    def test_generator_covers_both_timeouts(self):
        for arm in self.design["arms"].values():
            self.assertGreaterEqual(800, math.ceil(1.25 * arm["rate"] * 2 * arm["http_timeout_seconds"]))
        self.runtime["workload"]["pre_allocated_vus"] = 320
        with self.assertRaises(ValueError):
            validate(self.design, self.runtime)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.design, self.runtime = load(ROOT / DESIGN), load(ROOT / RUNTIME)

    def test_no_document_sources_or_identifying_docs_and_comments(self):
        paths = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT, text=True,
        ).split("\0")
        # Use local identity only to detect leaks; never write it into an artifact.
        identities = []
        for key in ("user.name", "user.email"):
            p = subprocess.run(["git", "config", "--get", key], cwd=ROOT, text=True, capture_output=True)
            if p.returncode == 0 and len(p.stdout.strip()) > 3:
                identities.append(p.stdout.strip())
        origin = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=ROOT, text=True).strip()
        origin = origin.removesuffix(".git")
        for relative in filter(None, paths):
            p = ROOT / relative
            self.assertNotIn(p.suffix.lower(), {".pdf", ".tex", ".bib", ".docx", ".pptx"}, relative)
            self.assertFalse(relative.startswith("protocol/"), relative)
            self.assertFalse(p.name.startswith("experiment_protocol_ru_"), relative)
            if p.suffix == ".md":
                text = p.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text), relative)
                self.assertIsNone(re.search(r"\b(manuscript|paper|article)\b", text, re.I), relative)
            elif p.suffix == ".py":
                source = p.read_text(encoding="utf-8")
                comments = [t.string for t in tokenize.generate_tokens(io.StringIO(source).readline)
                            if t.type == tokenize.COMMENT]
                comments.extend(ast.get_docstring(node) or "" for node in ast.walk(ast.parse(source))
                                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)))
                text = "\n".join(comments)
            elif p.suffix in {".js", ".yml", ".yaml"}:
                text = "\n".join(line for line in p.read_text(encoding="utf-8").splitlines()
                                  if line.lstrip().startswith(("#", "//", "/*", "*")))
            else:
                continue
            self.assertNotIn(origin, text, relative)
            for identity in identities:
                self.assertNotIn(identity.casefold(), text.casefold(), relative)

    def test_comparator_matches_are_real(self):
        arm = self.design["arms"]["context"]
        for comparison in arm["comparisons"]:
            a, b = (features(arm, arm["points"][comparison[k]]) for k in ("left", "right"))
            for key in comparison["matched_features"]:
                self.assertAlmostEqual(a[key], b[key], places=12)
        a = features(arm, arm["points"]["anchor_019"])
        b = features(arm, arm["points"]["payment_011"])
        self.assertNotAlmostEqual(a["R_group"], b["R_group"])
        arm["points"]["payment_011"]["checkout"] += 0.01
        with self.assertRaises(ValueError):
            validate(self.design, self.runtime)

    def test_both_radial_scores_misrank_historical_pair(self):
        arm = self.design["arms"]["ab"]
        a, b = (features(arm, arm["points"][p]) for p in ("A", "B"))
        self.assertGreater(a["E"], b["E"])
        self.assertGreater(a["d_A"], b["d_A"])
        self.assertLess(a["R_group"], b["R_group"])

    def test_no_binary_scientific_success_rule(self):
        self.design["analysis"]["binary_success_criterion"] = "unsupported"
        with self.assertRaises(ValueError):
            validate(self.design, self.runtime)


class MeasurementTests(unittest.TestCase):
    def measure(self, *, started=100, finished=100, successes=100, durations=None, exit_code=0):
        durations = [100] * finished if durations is None else durations
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            config = {"rate": 10, "duration_seconds": 10, "preAllocatedVUs": 800, "maxVUs": 800,
                      "http_timeout_seconds": 10, "timeUnit": "1s", "gracefulStop_seconds": 30}
            (folder / "scenario-config.json").write_text(json.dumps(config))
            (folder / "run-status.json").write_text(json.dumps({"exit_code": exit_code}))
            (folder / "summary.json").write_text("{}")
            rows = []
            def add(metric, value, tags=None):
                rows.append({"type": "Point", "metric": metric, "data": {"value": value, "tags": tags or {}}})
            for name, value in {"protocol_iterations_started": started, "protocol_iterations_finished": finished,
                                "successful_iterations": successes, "checkout_requests_started": started,
                                "dropped_iterations": 100 - started}.items():
                add(name, value)
            for value in durations:
                add("http_req_duration", value, {"request_name": "checkout"})
            for _ in range(finished):
                add("protocol_iteration_duration", 200)
            raw = "\n".join(json.dumps(row) for row in rows) + "\n"
            (folder / "raw-metrics.jsonl").write_text(raw, encoding="utf-8", newline="\n")
            result = summarize(folder, rate=10, seconds=10, vus=800, timeout=10, p95_limit=500, error_limit=0.01)
            self.assertEqual(gzip.decompress((folder / "raw-metrics.jsonl.gz").read_bytes()).decode(), raw)
            self.assertFalse((folder / "raw-metrics.jsonl").exists())
            return result

    def test_success_and_lossless_primary_evidence(self):
        self.assertTrue(self.measure()["safe"])

    def test_failed_dropped_unfinished_not_double_counted(self):
        result = self.measure(started=95, finished=92, successes=90)
        self.assertEqual((result["failed_iterations"], result["dropped_iterations"], result["unfinished_iterations"]), (2, 5, 3))
        self.assertEqual(result["error_count"], 10)
        self.assertEqual(result["error_rate"], 0.1)
        self.assertFalse(result["safe"])

    def test_exact_error_boundary_is_unsafe(self):
        self.assertFalse(self.measure(successes=99)["safe"])

    def test_timeout_latencies_are_included(self):
        result = self.measure(successes=90, durations=[100] * 90 + [10000] * 10)
        self.assertEqual(result["p95_ms"], 10000)

    def test_missing_checkout_p95_still_recoverable_unsafe(self):
        result = self.measure(started=100, finished=0, successes=0, durations=[])
        self.assertIsNone(result["p95_ms"])
        self.assertFalse(result["safe"])
        self.assertEqual(result["unfinished_iterations"], 100)

    def test_generator_boundary(self):
        self.assertTrue(generator_valid(self.measure(started=99, finished=99, successes=99)))
        self.assertFalse(generator_valid(self.measure(started=98, finished=98, successes=98)))

    def test_bad_counters_rejected(self):
        with self.assertRaises(ValueError):
            self.measure(started=100, finished=101)

    def test_type7_quantile(self):
        self.assertIsNone(quantile([], 0.95))
        self.assertEqual(quantile([1, 2], 0.95), 1.95)


class DiagnosticsTests(unittest.TestCase):
    def test_no_counter_deltas_across_restarts_or_resets(self):
        old = {"identity": ["id", 1, 10], "cpu": {"usage_usec": 1000000, "nr_periods": 10, "nr_throttled": 2}}
        new = copy.deepcopy(old)
        new["cpu"] = {"usage_usec": 1500000, "nr_periods": 14, "nr_throttled": 3}
        self.assertEqual(checked_delta(old, new, 2)["cpu_cores"], 0.25)
        self.assertEqual(checked_delta(old, new, 2)["throttled_period_fraction"], 0.25)
        new["identity"][1] = 2
        self.assertIsNone(checked_delta(old, new, 2))
        new["identity"][1] = 1
        new["cpu"]["usage_usec"] = 0
        self.assertIsNone(checked_delta(old, new, 2))

    def test_teardown_is_not_post_intervention_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            events = [{"Action": "die", "time": t, "Actor": {"Attributes": {"name": "checkout"}}} for t in (9, 15, 25)]
            (folder / "docker-events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
            diag = run_block.diagnostic_summary(folder, "1970-01-01T00:00:10+00:00", "1970-01-01T00:00:20+00:00", "k6")
            self.assertEqual([e["post_intervention"] for e in diag["failure_events"]], [False, True, False])
            self.assertTrue(diag["failure_events"][-1]["after_measurement"])


class ExecutionPathTests(unittest.TestCase):
    def execute_point(self, *, baseline_started=100, test_started=100, restart=False, cleanup_fails=False):
        arm = load(ROOT / DESIGN)["arms"]["ab"]
        runtime = load(ROOT / RUNTIME)
        parent = {"workload": {"health_check_timeout_seconds": 300},
                  "required_running_containers": ["checkout"], "system_under_test_containers": ["checkout"]}
        def measured(started):
            return {"safe": True, "p95_ms": 100, "error_rate": 0, "started_iterations": started,
                    "scheduled_iterations": 100, "k6_exit_code": 0}
        def fake_phase(repo, parent, runtime, arm, trial, point, name, seconds, folder, generator, *, primary):
            if name == "test":
                folder.mkdir(parents=True)
                run_block.write_json(folder / "run-status.json", {"started_at": run_block.utc(), "ended_at": run_block.utc()})
            return measured(baseline_started if name == "baseline" else test_started) if primary else None
        before = {"checkout": {"RestartCount": 0, "State": {"Running": True, "OOMKilled": False}}}
        after = {"checkout": {"RestartCount": int(restart), "State": {"Running": True, "OOMKilled": restart}}}
        fake_process = SimpleNamespace(pid=1, wait=lambda **kw: 0, terminate=lambda: None, kill=lambda: None)
        def fake_run(command, **kwargs):
            if cleanup_fails and "logs" in command:
                raise OSError("diagnostic collection unavailable")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        def quota(q):
            return {"valid": True, "effective": q}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict("os.environ", {"GITHUB_RUN_ID": "1", "GITHUB_SHA": "test"}), \
             patch.object(run_block, "run", fake_run), \
             patch.object(run_block, "phase", fake_phase), \
             patch.object(run_block, "apply"), \
             patch.object(run_block, "quota_check", quota), \
             patch.object(run_block, "wait_for_stack"), \
             patch.object(run_block, "inspect_all", side_effect=[before, before, after]), \
             patch.object(run_block.subprocess, "Popen", return_value=fake_process):
            result = run_block.point(ROOT, ROOT, parent, runtime, arm, "ab", "ab-001", "B", Path(tmp) / "point")
            saved = load(Path(tmp) / "point/point-result.json")
            self.assertEqual(saved["valid"], result["valid"])
            return result

    def test_actual_path_enforces_test_generator_gate(self):
        result = self.execute_point(test_started=98)
        self.assertFalse(result["valid"])
        self.assertTrue(result["primary_recoverable"])
        self.assertIn("test_started_below_99_percent", result["reason_codes"])

    def test_actual_path_enforces_baseline_gate(self):
        result = self.execute_point(baseline_started=98)
        self.assertFalse(result["valid"])
        self.assertIsNone(result["test"])
        self.assertIn("baseline_started_below_99_percent", result["reason_codes"])

    def test_restart_and_oom_do_not_override_slo_or_exclude(self):
        result = self.execute_point(restart=True)
        self.assertTrue(result["valid"])
        self.assertTrue(result["test"]["safe"])
        self.assertTrue(result["post_intervention_failures"])

    def test_diagnostic_failure_does_not_erase_outcome(self):
        result = self.execute_point(cleanup_fails=True)
        self.assertTrue(result["valid"])
        self.assertTrue(result["diagnostics"]["cleanup_errors"])


class AnalysisTests(unittest.TestCase):
    def block(self, index=0):
        design = load(ROOT / DESIGN)
        row = matrix(design)[index]
        arm = design["arms"][row["arm"]]
        points = {}
        for name, quotas in arm["points"].items():
            points[name] = {"valid": True, "primary_recoverable": True, "test": {"safe": True, "p95_ms": 100},
                            "reason_codes": [], "features": features(arm, quotas),
                            "provenance": {"runner_image_version": "fixture"}}
        return {"study_version": VERSION, "repository_commit": "commit", **row, "points": points, "valid": True}

    def test_both_contrast_directions_and_missing_latencies(self):
        a, b = {"test": {"safe": True, "p95_ms": 100}}, {"test": {"safe": False, "p95_ms": None}}
        report = pair_counts([(a, b), (b, a)])
        self.assertEqual(report["discordant"], 2)
        self.assertEqual(report["left_safe_right_unsafe"]["K"], 1)
        self.assertEqual(report["left_unsafe_right_safe"]["K"], 1)
        self.assertEqual(report["complete_latency_pairs"], 0)

    def test_technical_invalid_outcomes_not_hidden(self):
        b = self.block()
        b["points"]["B"].update(valid=False, reason_codes=["test_started_below_99_percent"])
        b["points"]["B"]["test"]["safe"] = False
        b["valid"] = False
        report = analyze(load(ROOT / DESIGN), {b["block_id"]: b}, "commit")
        comp = report["arms"]["ab"]["comparisons"]["radial_reversal"]
        self.assertEqual(comp["valid_pairs"]["left_safe_right_unsafe"]["N"], 0)
        self.assertEqual(comp["all_recoverable_pairs"]["left_safe_right_unsafe"]["K"], 1)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(len(report["missing_blocks"]), 27)

    def test_wrong_order_or_commit_rejected(self):
        b = self.block()
        with self.assertRaises(ValueError):
            analyze(load(ROOT / DESIGN), {b["block_id"]: b}, "other-commit")
        b["order"] = list(reversed(b["order"]))
        with self.assertRaises(ValueError):
            analyze(load(ROOT / DESIGN), {b["block_id"]: b}, "commit")

    def test_artifact_analysis_and_duplicate_detection(self):
        b = self.block()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            run_block.write_json(folder / "input/block-result.json", b)
            summary = save(ROOT, folder / "input", folder / "output", "commit")
            self.assertEqual(summary["received_blocks"], 1)
            self.assertTrue((folder / "output/point-level.csv").exists())
            run_block.write_json(folder / "input/duplicate/block-result.json", b)
            with self.assertRaises(ValueError):
                save(ROOT, folder / "input", folder / "output2", "commit")


if __name__ == "__main__":
    unittest.main()
