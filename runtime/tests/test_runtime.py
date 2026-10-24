"""Check relocation and isolation without running Docker or system services."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE))
import quota_driver
import runtime_support as runtime
import verify


class RuntimeTests(unittest.TestCase):
    def test_exact_copies_and_function_bodies(self):
        self.assertEqual(verify.verify()['extracted_functions'], 10)

    def test_design_labels_resolve_to_existing_locks(self):
        for label in runtime.ARCHIVED_PATHS:
            self.assertTrue(runtime.runtime_path(label).is_file())

    def test_compose_arguments_reference_only_retained_files(self):
        upstream = Path('upstream/otel-demo')
        for prefix in (runtime.compose_prefix(runtime.ROOT, upstream, 'test'), runtime.prefix(upstream, 'test')):
            self.assertEqual(prefix[:4], ['docker', 'compose', '--project-name', 'test'])
            files = [Path(prefix[i+1]) for i,v in enumerate(prefix) if v in ('-f','--env-file')]
            for path in files:
                if path.is_absolute():
                    self.assertTrue(path.is_file(), path)
                    self.assertTrue(path.is_relative_to(runtime.ROOT/'runtime'))

    def test_driver_rejects_local_or_self_hosted_execution_before_commands(self):
        for env in ({}, {'GITHUB_ACTIONS':'true', 'RUNNER_ENVIRONMENT':'self-hosted'}):
            with patch.dict(os.environ, env, clear=True), patch.object(quota_driver,'command') as command:
                with self.assertRaises(RuntimeError):
                    quota_driver.configure(Path('unused'))
                command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
