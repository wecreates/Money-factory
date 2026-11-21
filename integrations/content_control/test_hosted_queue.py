"""Persistent queue contract tests using synthetic packet bytes, never model evidence."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control import hosted_queue as hosted
from integrations.content_control.video_job import digest
from integrations.local_agent_queue import Queue, work, canonical


class HostedQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'proof'
        files = {'synthetic-fixture-only': 'd' * 64}
        self.source = {'source_commit': 'a' * 40, 'source_files': files,
                       'source_manifest_sha256': hashlib.sha256(canonical(files).encode()).hexdigest()}
        with patch.object(hosted, 'describe_source', return_value=self.source), \
             patch.object(hosted, 'collect_snapshot', return_value={'scope': 'synthetic-unit-test-only'}):
            hosted.prepare(self.output, '/fixture', self.source['source_commit'])

    def finish(self, *, blocked=False, override=None):
        queue = Queue(self.output / 'queue')
        def fixture_executor(attempt):
            if blocked:
                return {'status': 'BLOCKED', 'publication_enabled': False}
            folder = queue.root / 'attempts' / hosted.JOB_ID / '1'
            packet = folder / 'review'
            packet.mkdir(parents=True)
            for name in ('video.mp4', 'captions.vtt', 'encoded-verification.json', 'audio-verification.json'):
                (packet / name).write_text('synthetic unit-test fixture, not real media: ' + name)
            receipt = {'status': 'AWAITING_REVIEW', 'technical_status': 'PASS',
                       'publication_enabled': False, 'production_approved': False, 'full_av_review': False,
                       'source_inputs_unchanged': True, 'renderer_scratch_cleaned': True,
                       'source_sha256': self.source['source_files'],
                       'candidate_sha256': digest(packet / 'video.mp4'),
                       'artifacts_sha256': {p.name: digest(p) for p in packet.iterdir()}}
            hosted.write_json(packet / 'run.json', receipt)
            outer = {'status': 'PASS', 'review_status': 'AWAITING_REVIEW',
                     'publication_enabled': False, 'paid_generation_enabled': False,
                     'production_approved': False, 'full_av_review': False,
                     'production_ready': False, 'artifact_directory': 'review',
                     'source_inputs_unchanged': True, 'capacity': {'admitted_workers': 1},
                     'source_commit': self.source['source_commit'],
                     'source_manifest_sha256': self.source['source_manifest_sha256'],
                     'candidate_sha256': receipt['candidate_sha256'],
                     'pipeline_receipt_sha256': digest(packet / 'run.json')}
            outer.update(override or {})
            hosted.write_json(folder / 'video-adapter-receipt.json', outer)
            return outer
        try:
            work(queue, max_jobs=1, executor=fixture_executor)
        finally:
            queue.close()

    def test_closed_sqlite_and_packet_reopen_in_a_separate_process(self):
        self.finish()
        result = subprocess.run([sys.executable, '-m', 'integrations.content_control.hosted_queue',
                                 '--output', str(self.output), 'verify'], capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'QUEUED_PACKET_VERIFIED')
        self.assertEqual(report['queue_state']['attempts'], 1)
        self.assertFalse(report['publication_enabled'])
        self.assertFalse(report['production_approved'])
        self.assertFalse(report['full_av_review'])
        self.assertFalse(report['persistent_worker_verified'])
        self.assertEqual(report['queue_database_sha256'], digest(self.output / 'queue/queue.sqlite3'))

    def test_blocked_queue_never_becomes_success(self):
        self.finish(blocked=True)
        report = hosted.verify(self.output)
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertEqual(report['queue_state']['state'], 'blocked')

    def test_changed_artifact_rejected_after_queue_success(self):
        self.finish()
        (self.output / 'queue/attempts' / hosted.JOB_ID / '1/review/video.mp4').write_text('changed')
        self.assertEqual(hosted.verify(self.output)['status'], 'BLOCKED')

    def test_changed_saved_job_does_not_match_durable_request(self):
        self.finish()
        path = self.output / 'job.json'
        job = json.loads(path.read_text())
        job['request']['timeout_seconds'] = 901
        path.write_text(json.dumps(job))
        self.assertIn('durable queue identity', hosted.verify(self.output)['blocker'])

    def test_nonadmitted_or_approved_receipt_cannot_certify_packet(self):
        self.finish(override={'capacity': {'admitted_workers': 0}, 'full_av_review': True})
        self.assertIn('admitted unpublished', hosted.verify(self.output)['blocker'])

    def test_attempt_row_must_record_finished_success(self):
        self.finish()
        queue = Queue(self.output / 'queue')
        queue.db.execute('UPDATE attempts SET finished=NULL')
        queue.close()
        self.assertIn('attempt completion', hosted.verify(self.output)['blocker'])

    def test_production_ready_or_different_directory_is_not_accepted(self):
        self.finish(override={'production_ready': True, 'artifact_directory': 'elsewhere'})
        self.assertIn('admitted unpublished', hosted.verify(self.output)['blocker'])

    def test_source_manifest_bytes_must_match_pin(self):
        self.finish()
        path = self.output / 'source.json'
        source = json.loads(path.read_text())
        source['source_files']['synthetic-fixture-only'] = 'e' * 64
        path.write_text(json.dumps(source))
        self.assertIn('manifest bytes', hosted.verify(self.output)['blocker'])

    def test_prepare_does_not_overwrite_or_accept_moving_ref(self):
        with self.assertRaises(ValueError):
            hosted.prepare(self.output, '/fixture', 'main')
        with patch.object(hosted, 'describe_source', return_value=self.source):
            with self.assertRaises(FileExistsError):
                hosted.prepare(self.output, '/fixture', self.source['source_commit'])


if __name__ == '__main__':
    unittest.main()
