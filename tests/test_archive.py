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
    def test_retained_scope_and_language(self):
        checks.verify_scope(ROOT)

    def test_documentation_links(self):
        self.assertGreater(checks.verify_links(ROOT), 20)

    def test_lf_and_crlf_hashes_match(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name) / "input.csv"
            p.write_bytes(b"a,b\n1,2\n")
            before = checks.sha256_lf(p)
            p.write_bytes(b"a,b\r\n1,2\r\n")
            self.assertEqual(before, checks.sha256_lf(p))

    def test_compressed_primary_inputs_are_hashed_as_binary(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/"inputs.json.gz"
            p.write_bytes(b"a\r\nb")
            before=checks.sha256_lf(p)
            p.write_bytes(b"a\nb")
            self.assertNotEqual(before,checks.sha256_lf(p))

    def test_png_figures_are_hashed_as_binary(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)/"figure.png"
            data = b"\x89PNG\r\n\x1a\n\x00example"
            p.write_bytes(data)
            import hashlib
            self.assertEqual(checks.sha256_lf(p), hashlib.sha256(data).hexdigest())

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

    def test_license_is_separate_from_measurement_checksums(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            (p / "data.csv").write_text("value\n1\n")
            (p / "LICENSE").write_text("License text")
            digest = checks.sha256_lf(p / "data.csv")
            (p / "SHA256SUMS").write_text(f"{digest}  data.csv\n")
            self.assertEqual(checks.verify_checksums(p), 1)
            (p / "data.csv").write_text("value\n2\n")
            with self.assertRaises(ValueError):
                checks.verify_checksums(p)


if __name__ == "__main__":
    unittest.main()
