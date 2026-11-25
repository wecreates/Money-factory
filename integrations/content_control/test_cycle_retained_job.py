"""Test the retained-cycle queue contract; fixtures do not represent media QA."""
import json
import os
import sys
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from integrations.content_control.cycle_checkpoint import create_checkpoint
from integrations.content_control.retained_cycle_job import ADAPTER, IDENTITY_FIELDS, OPERATION, RECEIPT
from integrations.content_control.review_delivery import export_review, status, verify_exported_cycle
from integrations.content_control.review_package import digest
from integrations.content_control import test_cycle_review as fixtures
from integrations.local_agent_queue import Queue, validate, work


class RetainedCycleTests(unittest.TestCase):
    setUp = fixtures.ReviewTests.setUp
    tearDown = fixtures.ReviewTests.tearDown

    def setup_job(self, *, package_ready=False, **changes):
        package_path = self.delivery / 'package.json'
        package = json.loads(package_path.read_text())
        fixtures.write(package_path, dict(package, schema_version=1, production_ready=package_ready))
        archive_path = self.delivery / 'review-package.zip'
        with ZipFile(archive_path, 'w') as archive:
            for name in (*package['files_sha256'], 'package.json'):
                archive.write(self.delivery / name, name)
        cycle_path = self.root / 'cycle.json'
        cycle = json.loads(cycle_path.read_text())
        fixtures.write(cycle_path, dict(cycle, production_ready=False,
                                       archive_sha256=digest(archive_path), package_sha256=digest(package_path)))
        checkpoint = self.base / 'checkpoint.zip'
        create_checkpoint(self.root, checkpoint)
        request = {'operation': OPERATION, 'checkpoint_sha256': digest(checkpoint),
                   'publication_enabled': False, 'paid_generation_enabled': False, 'timeout_seconds': 15,
                   **{key: digest(self.root / path) for key, path in IDENTITY_FIELDS.items()}}
        request.update(changes)
        job = {'id': 'retained', 'adapter': ADAPTER, 'request': request,
               'max_attempts': 1, 'publication_enabled': False, 'paid_generation_enabled': False}
        return checkpoint, job

    def execute(self, job, checkpoint):
        queue = Queue(self.base / 'queue')
        self.addCleanup(queue.close)
        queue.enqueue(job)
        outcome = work(queue, cycle_checkpoint_path=checkpoint)
        self.assertEqual(outcome['processed'][0]['attempts'], 1)
        return queue

    def test_restored_cycle_delivers_after_original_checkpoint_removed(self):
        checkpoint, job = self.setup_job()
        queue = self.execute(job, checkpoint)
        checkpoint.unlink()
        report = status(queue.root, job['id'])
        self.assertTrue(report['delivery_ready'], report)
        output = self.base / 'export'
        delivery = export_review(queue.root, job['id'], output)
        verified = verify_exported_cycle(output, delivery['delivery_identity_sha256'])
        self.assertEqual(verified['status'], 'PASS')
        self.assertEqual(delivery['provenance']['adapter'], ADAPTER)
        self.assertEqual(delivery['provenance']['checkpoint_sha256'], job['request']['checkpoint_sha256'])
        self.assertEqual(delivery['provenance']['caption_sha256'], digest(output / 'review/captions.vtt'))
        self.assertEqual(verified['candidate_sha256'], self.candidate)
        self.assertFalse(verified['full_av_review'])
        self.assertFalse(verified['production_approved'])

    def test_wrong_caption_pin_blocks_before_durable_completion(self):
        checkpoint, job = self.setup_job(caption_sha256='0' * 64)
        queue = self.execute(job, checkpoint)
        self.assertEqual(queue.get(job['id'])['state'], 'blocked')
        self.assertFalse(status(queue.root, job['id'])['delivery_ready'])

    def test_pinned_production_ready_package_still_blocks_delivery(self):
        checkpoint, job = self.setup_job(package_ready=True)
        queue = self.execute(job, checkpoint)
        self.assertEqual(queue.get(job['id'])['state'], 'blocked')
        self.assertFalse(status(queue.root, job['id'])['delivery_ready'])

    def test_path_in_request_rejected(self):
        _, job = self.setup_job(checkpoint_path='/not/a/job/field')
        with self.assertRaisesRegex(ValueError, 'Invalid retained cycle request'):
            validate(job)

    def test_source_symlink_blocks(self):
        checkpoint, job = self.setup_job()
        link = self.base / 'untrusted.zip'
        link.symlink_to(checkpoint)
        queue = self.execute(job, link)
        self.assertEqual(queue.get(job['id'])['state'], 'blocked')

    def test_paid_or_publication_environment_blocks_before_copy(self):
        checkpoint, job = self.setup_job()
        with patch.dict('os.environ', {'PUBLICATION_ENABLED': 'true'}):
            queue = self.execute(job, checkpoint)
        self.assertEqual(queue.get(job['id'])['state'], 'blocked')
        attempt = queue.root / 'attempts' / job['id'] / '1'
        self.assertFalse((attempt / 'checkpoint.zip').exists())

    def assert_guardian_bounds_worker(self, program, *, copied_checkpoint):
        checkpoint, job = self.setup_job(timeout_seconds=5)
        pid_file = self.base / 'child-pid'
        def command(request, attempt, source):
            return [sys.executable, '-c', program, json.dumps(request), str(attempt), str(source), str(pid_file)]
        started = time.monotonic()
        with patch('integrations.content_control.retained_cycle_job._worker_command', side_effect=command):
            queue = self.execute(job, checkpoint)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 10)
        result = queue.get(job['id'])
        self.assertEqual(result['state'], 'blocked')
        self.assertIn('deadline', result['receipts'][0]['receipt']['reason'])
        self.assertFalse(status(queue.root, job['id'])['delivery_ready'])
        attempt = queue.root / 'attempts' / job['id'] / '1'
        self.assertEqual((attempt / 'checkpoint.zip').exists(), copied_checkpoint)
        self.assertFalse((attempt / RECEIPT).exists())
        pid = int(pid_file.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_deadline_includes_blocked_restore_primitive(self):
        self.assert_guardian_bounds_worker('''
import json, os, sys, time
from pathlib import Path
from integrations.content_control import retained_cycle_job as job
def blocked(*args, **kwargs):
    Path(sys.argv[4]).write_text(str(os.getpid()))
    time.sleep(60)
job.restore_checkpoint = blocked
job._restore_job(job.validate(json.loads(sys.argv[1])), Path(sys.argv[2]), Path(sys.argv[3]))
''', copied_checkpoint=True)

    def test_deadline_includes_child_startup(self):
        self.assert_guardian_bounds_worker('''
import os, sys, time
from pathlib import Path
Path(sys.argv[4]).write_text(str(os.getpid()))
time.sleep(60)
''', copied_checkpoint=False)

    def test_changed_copy_or_receipt_blocks_delivery(self):
        checkpoint, job = self.setup_job()
        queue = self.execute(job, checkpoint)
        attempt = queue.root / 'attempts' / job['id'] / '1'
        self.assertTrue(status(queue.root, job['id'])['delivery_ready'])
        paths = ('checkpoint.zip', 'cycle/delivery/captions.vtt', 'cycle/render/voice.json', RECEIPT)
        for name in paths:
            with self.subTest(artifact=name):
                path = attempt / name
                before = path.read_bytes()
                path.write_bytes(before + b'changed')
                self.assertFalse(status(queue.root, job['id'])['delivery_ready'])
                path.write_bytes(before)
        self.assertTrue(status(queue.root, job['id'])['delivery_ready'])
