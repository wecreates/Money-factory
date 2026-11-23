"""Synthetic queue and package fixtures cover durable fresh-cycle delivery."""
import json
import shutil
import unittest
from zipfile import BadZipFile, ZipFile

from integrations.content_control import test_cycle_review as fixtures
from integrations.content_control.cycle_job import brief_digest, production_input
from integrations.content_control.review_delivery import export_review, status
from integrations.content_control.review_package import digest
from integrations.local_agent_queue import Queue, canonical


class CycleDeliveryTests(unittest.TestCase):
    setUp = fixtures.ReviewTests.setUp
    tearDown = fixtures.ReviewTests.tearDown

    def queue_review(self, minimum=None, picture_seconds=None):
        brief = json.loads((self.root / 'brief.json').read_text())
        request = {'operation': 'produce-content-cycle', 'brief': brief, 'brief_sha256': brief_digest(brief),
                   'timeout_seconds': 300, 'publication_enabled': False, 'paid_generation_enabled': False}
        if minimum is not None:
            request['minimum_duration_seconds'] = minimum
        queue = Queue(self.base / 'queue'); self.addCleanup(queue.close)
        queue.enqueue({'id': 'cycle-test', 'adapter': 'content-control-cycle', 'request': request,
                       'max_attempts': 1, 'publication_enabled': False, 'paid_generation_enabled': False})
        with queue.consumer():
            claim = queue.claim()
            attempt = queue.root / 'attempts/cycle-test/1'
            directory = attempt / 'cycle'; shutil.copytree(self.root, directory)
            (directory / 'brief.json').write_bytes(production_input(request)[0])
            delivery = directory / 'delivery'
            render = json.loads((delivery / 'render.json').read_text())
            if minimum is not None:
                render.update(minimum_duration_seconds=minimum, measured_narration_frame_budget=minimum*24,
                              encoded_picture_duration_seconds=picture_seconds)
            for target in (delivery, directory / 'render'):
                fixtures.write(target / 'render.json', dict(render, status='AWAITING_REVIEW'))
            package = json.loads((delivery / 'package.json').read_text())
            package.update(production_ready=False, render_receipt_sha256=digest(delivery / 'render.json'))
            package['files_sha256']['render.json'] = package['render_receipt_sha256']
            fixtures.write(delivery / 'package.json', package)
            with ZipFile(delivery / 'review-package.zip', 'w') as archive:
                for name in (*package['files_sha256'], 'package.json'):
                    archive.write(delivery / name, name)
            cycle_path = directory / 'cycle.json'
            cycle = json.loads(cycle_path.read_text())
            cycle.update(brief_sha256=digest(directory / 'brief.json'), package_sha256=digest(delivery / 'package.json'),
                         archive_sha256=digest(directory / 'delivery/review-package.zip'),
                         production_ready=False, factual_review=False, competitor_comparison=False)
            if minimum is not None:
                cycle['minimum_duration_seconds'] = minimum
            fixtures.write(cycle_path, cycle)
            receipt = {'status': 'PASS', 'review_status': 'AWAITING_REVIEW', 'operation': request['operation'],
                       'brief_sha256': request['brief_sha256'], 'production_brief_sha256': cycle['brief_sha256'],
                       'candidate_sha256': self.candidate, 'pipeline_receipt_sha256': digest(cycle_path),
                       'artifact_directory': 'cycle', **self.flags, 'production_ready': False}
            if minimum is not None:
                receipt['minimum_duration_seconds'] = minimum
            fixtures.write(attempt / 'cycle-adapter-receipt.json', receipt)
            queue.finish(claim, receipt)
        return queue, directory, receipt

    def test_durable_completion_copies_exact_archive_outside_queue(self):
        queue, directory, _ = self.queue_review()
        db = queue.root / 'queue.sqlite3'; before = db.read_bytes()
        report = status(queue.root, 'cycle-test')
        self.assertTrue(report['delivery_ready'], report)
        output = self.base / 'export'
        result = export_review(queue.root, 'cycle-test', output)
        self.assertEqual(result, json.loads((output / 'package.json').read_text()))
        self.assertEqual(result['candidate_sha256'], self.candidate)
        self.assertEqual(result['archive_sha256'], digest(output / 'review-package.zip'))
        self.assertEqual(result['archive_sha256'], digest(directory / 'delivery/review-package.zip'))
        self.assertFalse(result['production_approved'])
        for path in (output, queue.root / 'other'):
            with self.assertRaisesRegex(ValueError, 'outside the queue'):
                export_review(queue.root, 'cycle-test', path)
        self.assertEqual(before, db.read_bytes())

    def test_minimum_duration_is_rechecked_from_queue_before_export(self):
        queue, _, _ = self.queue_review(minimum=510, picture_seconds=509.99)
        self.assertIn('minimum picture duration', status(queue.root, 'cycle-test')['delivery_error'])
        output = self.base / 'export'
        with self.assertRaisesRegex(ValueError, 'minimum picture duration'):
            export_review(queue.root, 'cycle-test', output)
        self.assertFalse(output.exists())

    def test_verified_minimum_duration_is_retained_in_export_provenance(self):
        queue, _, _ = self.queue_review(minimum=510, picture_seconds=510.0)
        output = self.base / 'export'
        result = export_review(queue.root, 'cycle-test', output)
        self.assertEqual(result['provenance']['minimum_duration_seconds'], 510)

    def test_non_success_mismatched_disk_receipt_and_corrupt_archive_are_blocked(self):
        queue, directory, receipt = self.queue_review()
        queue.db.execute("UPDATE jobs SET state='interrupted'")
        self.assertFalse(status(queue.root, 'cycle-test')['delivery_ready'])
        queue.db.execute("UPDATE jobs SET state='succeeded'")
        changed = {**receipt, 'production_brief_sha256': '0' * 64}
        path = directory.parent / 'cycle-adapter-receipt.json'
        fixtures.write(path, changed)
        self.assertIn('Adapter receipt differs', status(queue.root, 'cycle-test')['delivery_error'])
        queue.db.execute('UPDATE attempts SET receipt=?', (canonical(changed),))
        self.assertIn('immutable brief', status(queue.root, 'cycle-test')['delivery_error'])
        fixtures.write(path, receipt)
        queue.db.execute('UPDATE attempts SET receipt=?', (canonical(receipt),))
        (directory / 'delivery/review-package.zip').write_bytes(b'corrupt archive')
        self.assertFalse(status(queue.root, 'cycle-test')['delivery_ready'])
        with self.assertRaises(BadZipFile):
            export_review(queue.root, 'cycle-test', self.base / 'unused')
        self.assertFalse((self.base / 'unused').exists())


if __name__ == '__main__':
    unittest.main()
