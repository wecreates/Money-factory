"""Reject redirected review directories; fixtures do not establish acceptance."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import inspect_review as inspection
import production_agent as agent
import test_production_snapshot as fixture


class ReviewDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ProductionSnapshotTests(); self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        with patch.object(fixture.agent, 'run_review_child', side_effect=self.case.finish):
            self.case.run_agent()
        self.output = self.case.output

    def inspect(self): return inspection.inspect_review(self.case.job, self.output)

    def test_package_symlink_is_rejected_by_generation_and_inspection(self):
        package = self.output/'package'; moved = self.case.root/'outside-package'
        package.rename(moved); package.symlink_to(moved, target_is_directory=True)
        for verify in (lambda: agent.validate_review_output(self.output, 'kdp'), self.inspect):
            with self.subTest(verify=verify), self.assertRaises(OSError): verify()
        self.assertTrue(package.is_symlink())

    def test_inspection_rejects_symlink_output_root(self):
        moved = self.case.root/'outside-output'
        self.output.rename(moved); self.output.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(OSError): self.inspect()
        self.assertTrue(self.output.is_symlink())

    def test_package_replacement_during_reads_never_follows_new_directory(self):
        package = self.output/'package'; moved = self.output/'held-package'
        real_read = agent.output_json
        def replace(path, *args, **kwargs):
            value = real_read(path, *args, **kwargs)
            if Path(path).name == 'result.json':
                package.rename(moved); package.mkdir()
                (package/'manifest.json').write_text('not JSON; must never be read')
            return value
        with patch.object(agent, 'output_json', side_effect=replace):
            with self.assertRaisesRegex(ValueError, '^PACKAGE_DIRECTORY_CHANGED$'):
                self.inspect()
        self.assertEqual((package/'manifest.json').read_text(), 'not JSON; must never be read')

    def test_root_replacement_during_inspection_is_rejected(self):
        moved = self.case.root/'held-output'; real_read = agent.output_json
        def replace(path, *args, **kwargs):
            value = real_read(path, *args, **kwargs)
            if Path(path).name == 'result.json':
                self.output.rename(moved); self.output.mkdir()
                (self.output/'package').mkdir()
                (self.output/'package/manifest.json').write_text('must not be read')
            return value
        with patch.object(agent, 'output_json', side_effect=replace):
            with self.assertRaisesRegex(ValueError, '^OUTPUT_DIRECTORY_CHANGED$'):
                self.inspect()
        self.assertTrue((moved/'money-factory-receipt.json').is_file())

    def test_directory_descriptors_close_on_success_and_validation_failure(self):
        before = len(os.listdir('/proc/self/fd'))
        for _ in range(20): self.inspect()
        artifact = self.output/'package/art.bin'; artifact.write_bytes(b'changed')
        for _ in range(20):
            with self.assertRaisesRegex(ValueError, '^ARTIFACT_HASH_MISMATCH$'): self.inspect()
        self.assertEqual(len(os.listdir('/proc/self/fd')), before)

    def test_bad_package_directory_closes_root_descriptor(self):
        package = self.output/'package'; package.rename(self.output/'held-package')
        before = len(os.listdir('/proc/self/fd'))
        for kind in ('missing', 'file', 'fifo'):
            if kind == 'file': package.write_bytes(b'not a directory')
            if kind == 'fifo': os.mkfifo(package)
            try:
                for _ in range(20):
                    with self.assertRaises(OSError): self.inspect()
                self.assertEqual(len(os.listdir('/proc/self/fd')), before)
            finally: package.unlink(missing_ok=True)


if __name__ == '__main__': unittest.main()
