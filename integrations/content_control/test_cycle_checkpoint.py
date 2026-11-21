"""Synthetic cycle recovery tests; no media or creative acceptance claims."""
import json
from pathlib import Path
import shutil
import stat
import unittest
from unittest.mock import patch
import zipfile

from integrations.content_control import test_cycle_review as fixtures
from integrations.content_control.cycle_review import inspect_cycle, record_review
from integrations.content_control.cycle_checkpoint import create_checkpoint, restore_checkpoint, _publish_restore
from integrations.content_control.review_package import digest


class CheckpointTests(unittest.TestCase):
    setUp = fixtures.ReviewTests.setUp
    tearDown = fixtures.ReviewTests.tearDown

    def make(self):
        self.archive = self.base / 'checkpoint.zip'
        self.receipt = create_checkpoint(self.root, self.archive)
        return self.base / 'restored'

    def restore(self, output):
        return restore_checkpoint(self.archive, output, expected_sha256=digest(self.archive))

    def rewrite(self, mutate):
        with zipfile.ZipFile(self.archive) as bundle:
            entries = [(m, bundle.read(m)) for m in bundle.infolist()]
        entries = mutate(entries)
        with zipfile.ZipFile(self.archive, 'w') as bundle:
            for name, value in entries: bundle.writestr(name, value)

    def test_roundtrip_after_original_deleted_supports_review(self):
        output = self.make(); before = inspect_cycle(self.root)
        shutil.rmtree(self.root)
        result = restore_checkpoint(self.archive, output, expected_sha256=self.receipt['checkpoint_sha256'])
        self.assertEqual(inspect_cycle(output), before)
        self.assertEqual(result['status'], 'RESTORED_AWAITING_REVIEW')
        for flag in self.flags: self.assertFalse(result[flag])
        review = record_review(output, self.submitted, self.recorded)
        self.assertEqual(review['candidate_sha256'], self.candidate)
        self.assertFalse(review['production_approved'])

    def test_missing_or_wrong_external_hash_rejected(self):
        output = self.make()
        for sha in ('', 'invalid', '0' * 64):
            with self.assertRaises(ValueError): restore_checkpoint(self.archive, output, expected_sha256=sha)
            self.assertFalse(output.exists())

    def test_unrelated_files_are_not_archived(self):
        (self.root / 'secret.txt').write_text('must not retain')
        self.make()
        with zipfile.ZipFile(self.archive) as bundle:
            self.assertNotIn('secret.txt', bundle.namelist())
            self.assertIn('render/video.mp4', bundle.namelist())
            self.assertIn('render/captions.vtt', bundle.namelist())

    def test_extra_traversal_duplicate_or_missing_member_rejected(self):
        for name in ('../escape', '/absolute', 'cycle.json', 'render\\escape'):
            with self.subTest(name=name):
                output = self.make()
                self.rewrite(lambda entries: entries + [(name, b'bad')])
                with self.assertRaises(ValueError): self.restore(output)
                self.assertFalse(output.exists()); self.archive.unlink()
        output = self.make()
        self.rewrite(lambda entries: entries[1:])
        with self.assertRaises(ValueError): self.restore(output)
        self.assertFalse(output.exists())

    def test_symlink_member_and_source_symlink_rejected(self):
        output = self.make()
        def mutate(entries):
            for info, _ in entries:
                if info.filename == 'brief.json': info.external_attr = (stat.S_IFLNK | 0o777) << 16
            return entries
        self.rewrite(mutate)
        with self.assertRaises(ValueError): self.restore(output)
        self.assertFalse(output.exists())
        target = self.base / 'alias.zip'; target.symlink_to(self.archive)
        with self.assertRaises(ValueError): restore_checkpoint(target, output, expected_sha256=digest(self.archive))

    def test_tampering_and_approval_promotion_leave_no_partial_output(self):
        for kind in ('bytes', 'approval'):
            output = self.make()
            def mutate(entries):
                result = []
                for info, data in entries:
                    if kind == 'bytes' and info.filename == 'render/video.mp4': data = b'tampered'
                    if kind == 'approval' and info.filename == 'checkpoint.json':
                        manifest = json.loads(data); manifest['production_approved'] = True
                        data = json.dumps(manifest).encode()
                    result.append((info, data))
                return result
            self.rewrite(mutate)
            with self.assertRaises(ValueError): self.restore(output)
            self.assertFalse(output.exists())
            self.assertFalse(list(self.base.glob('.cycle-restore-*')))
            self.archive.unlink()

    def test_concurrently_created_empty_destination_is_not_replaced(self):
        output = self.make()
        def competing_writer(source, destination):
            destination.mkdir()
            _publish_restore(source, destination)
        with patch('integrations.content_control.cycle_checkpoint._publish_restore', side_effect=competing_writer):
            with self.assertRaises(FileExistsError): self.restore(output)
        self.assertTrue(output.is_dir()); self.assertEqual(list(output.iterdir()), [])
        self.assertFalse(list(self.base.glob('.cycle-restore-*')))

    def test_size_bounds_and_existing_output(self):
        output = self.make()
        with patch('integrations.content_control.cycle_checkpoint.FILE_LIMIT', 1):
            with self.assertRaises(ValueError): self.restore(output)
        self.assertFalse(output.exists())
        output.mkdir(); (output / 'keep').write_text('keep')
        with self.assertRaises(ValueError): self.restore(output)
        self.assertEqual((output / 'keep').read_text(), 'keep')
        with self.assertRaises(ValueError): create_checkpoint(self.root, self.archive)
        with self.assertRaises(ValueError): create_checkpoint(self.root, self.root / 'checkpoint.zip')


if __name__ == '__main__': unittest.main()
