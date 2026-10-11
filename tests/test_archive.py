from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("archive_checks", ROOT / "scripts/verify_archive.py")
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)


class ArchiveTests(unittest.TestCase):
    def test_committed_counts_and_replayed_analysis(self):
        checks.verify_observation_counts(ROOT)
        checks.verify_history(ROOT)

    def test_documentation_links(self):
        self.assertGreater(checks.verify_links(ROOT), 100)

    def test_lf_and_crlf_hashes_match(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name) / "input.csv"
            p.write_bytes(b"a,b\n1,2\n")
            before = checks.sha256_lf(p)
            p.write_bytes(b"a,b\r\n1,2\r\n")
            self.assertEqual(before, checks.sha256_lf(p))

    def test_no_git_archive_enumeration(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            (p / "README.md").write_text("ok")
            (p / "artifacts").mkdir()
            (p / "artifacts/temporary.json").write_text("{}")
            self.assertEqual(checks.archive_paths(p), [p / "README.md"])

    def test_broken_and_outside_links_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            for target in ("missing.csv", "../outside"):
                (p / "README.md").write_text(f"[data]({target})")
                with self.assertRaises(ValueError):
                    checks.verify_links(p)

    def test_license_redaction_does_not_relax_data_checksums(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            (p / "data.csv").write_text("value\n1\n")
            (p / "LICENSE").write_text("Copyright: [redacted]")
            digest = checks.sha256_lf(p / "data.csv")
            (p / "SHA256SUMS").write_text(f"{digest}  data.csv\n")
            self.assertEqual(checks.verify_checksums(p), 1)
            (p / "data.csv").write_text("value\n2\n")
            with self.assertRaises(ValueError):
                checks.verify_checksums(p)


if __name__ == "__main__":
    unittest.main()
