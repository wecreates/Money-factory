"""Queue/delivery identity tests; fixture media is synthetic, not playback proof."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from integrations.local_agent_queue import Queue, canonical
from integrations.content_control.runtime_doctor import SOURCES
from integrations.content_control.video_job import digest
from integrations.content_control.review_delivery import verify_delivery, status, export_review


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.queue = Queue(self.root / 'queue'); self.addCleanup(self.queue.close)
        sources = {name: hashlib.sha256(name.encode()).hexdigest() for name in SOURCES}
        self.spec = {'id': 'private-review', 'adapter': 'content-control-video',
                     'request': {'operation': 'produce-episode1-review', 'source_commit': 'a'*40,
                        'source_manifest_sha256': hashlib.sha256(canonical(sources).encode()).hexdigest(),
                        'timeout_seconds': 900, 'publication_enabled': False, 'paid_generation_enabled': False},
                     'max_attempts': 2, 'publication_enabled': False, 'paid_generation_enabled': False}
        self.queue.enqueue(self.spec)
        with self.queue.consumer():
            attempt = self.queue.claim()
            self.attempt = self.queue.root / 'attempts/private-review/1'
            self.review = self.attempt / 'review'; self.review.mkdir(parents=True)
            for name in ('video.mp4', 'captions.vtt', 'video.mp4.json', 'encoded-verification.json', 'audio-verification.json', 'REVIEW.md'):
                (self.review / name).write_text('synthetic ' + name)
            self.run = {'status': 'AWAITING_REVIEW', 'technical_status': 'PASS',
                        'publication_enabled': False, 'production_approved': False, 'full_av_review': False,
                        'source_inputs_unchanged': True, 'renderer_scratch_cleaned': True,
                        'source_sha256': sources, 'candidate_sha256': digest(self.review / 'video.mp4'),
                        'caption_sha256': digest(self.review / 'captions.vtt'),
                        'artifacts_sha256': {p.name: digest(p) for p in self.review.iterdir()}}
            (self.review / 'run.json').write_text(json.dumps(self.run))
            self.receipt = {'status': 'PASS', 'review_status': 'AWAITING_REVIEW',
                            **{name: self.spec['request'][name] for name in ('operation', 'source_commit', 'source_manifest_sha256')},
                            'publication_enabled': False, 'paid_generation_enabled': False,
                            'production_ready': False, 'production_approved': False, 'full_av_review': False,
                            'artifact_directory': 'review', 'source_inputs_unchanged': True,
                            'candidate_sha256': self.run['candidate_sha256'],
                            'pipeline_receipt_sha256': digest(self.review / 'run.json')}
            (self.attempt / 'video-adapter-receipt.json').write_text(json.dumps(self.receipt))
            self.queue.finish(attempt, self.receipt)

    def rewrite_receipt(self):
        (self.attempt / 'video-adapter-receipt.json').write_text(json.dumps(self.receipt))
        self.queue.db.execute('UPDATE attempts SET receipt=?', (canonical(self.receipt),))

    def rebind_run(self):
        (self.review / 'run.json').write_text(json.dumps(self.run))
        self.receipt['pipeline_receipt_sha256'] = digest(self.review / 'run.json')
        self.rewrite_receipt()

    def test_success_is_read_only_and_provenance_bound(self):
        before = (self.queue.root / 'queue.sqlite3').read_bytes()
        directory, proof = verify_delivery(self.queue.root, self.spec['id'])
        self.assertEqual(directory, self.review)
        self.assertEqual(proof['candidate_sha256'], self.run['candidate_sha256'])
        self.assertFalse(proof['production_approved'])
        self.assertTrue(status(self.queue.root, self.spec['id'])['delivery_ready'])
        self.assertEqual(before, (self.queue.root / 'queue.sqlite3').read_bytes())

    def test_all_unfinished_or_unsuccessful_states_refuse_leftover_video(self):
        for state in ('queued', 'running', 'interrupted', 'blocked', 'failed'):
            with self.subTest(state=state):
                self.queue.db.execute('UPDATE jobs SET state=?', (state,))
                self.queue.db.execute('UPDATE attempts SET state=?', (state,))
                with self.assertRaises(ValueError): verify_delivery(self.queue.root, self.spec['id'])
                self.assertFalse(status(self.queue.root, self.spec['id'])['delivery_ready'])

    def test_corrupt_or_missing_artifacts_are_not_ready(self):
        for name in ('video.mp4', 'captions.vtt', 'encoded-verification.json', 'run.json'):
            with self.subTest(name=name):
                path = self.review / name; before = path.read_bytes()
                path.write_bytes(b'changed')
                with self.assertRaises(ValueError): verify_delivery(self.queue.root, self.spec['id'])
                self.assertFalse(status(self.queue.root, self.spec['id'])['delivery_ready'])
                path.write_bytes(before)
        (self.review / 'video.mp4').unlink()
        with self.assertRaises(ValueError): verify_delivery(self.queue.root, self.spec['id'])

    def test_readiness_and_packager_use_same_artifact_boundary(self):
        (self.review / 'unrecorded.txt').write_text('not in bound receipt')
        self.assertFalse(status(self.queue.root, self.spec['id'])['delivery_ready'])
        (self.review / 'unrecorded.txt').unlink()
        self.run['caption_sha256'] = 'b'*64; self.rebind_run()
        self.assertFalse(status(self.queue.root, self.spec['id'])['delivery_ready'])

    def test_db_and_adapter_receipt_must_match(self):
        self.receipt['candidate_sha256'] = 'b'*64
        (self.attempt / 'video-adapter-receipt.json').write_text(json.dumps(self.receipt))
        with self.assertRaises(ValueError): verify_delivery(self.queue.root, self.spec['id'])

    def test_false_gates_cannot_be_changed_even_with_rebound_receipts(self):
        for flag in ('publication_enabled', 'paid_generation_enabled', 'production_approved', 'production_ready', 'full_av_review'):
            with self.subTest(flag=flag):
                self.receipt[flag] = True; self.rewrite_receipt()
                with self.assertRaises(ValueError): verify_delivery(self.queue.root, self.spec['id'])
                self.receipt[flag] = False; self.rewrite_receipt()
        self.run['production_approved'] = True; self.rebind_run()
        with self.assertRaises(ValueError): verify_delivery(self.queue.root, self.spec['id'])

    def test_request_digest_source_manifest_and_completion_history_are_checked(self):
        self.queue.db.execute("UPDATE jobs SET digest=?", ('0'*64,))
        with self.assertRaises(ValueError): verify_delivery(self.queue.root, self.spec['id'])
        self.queue.db.execute('UPDATE jobs SET digest=?', (hashlib.sha256(canonical(self.spec).encode()).hexdigest(),))
        self.run['source_sha256'][SOURCES[0]] = 'f'*64; self.rebind_run()
        with self.assertRaises(ValueError): verify_delivery(self.queue.root, self.spec['id'])
        self.queue.db.execute('UPDATE jobs SET attempts=2')
        with self.assertRaises(ValueError): verify_delivery(self.queue.root, self.spec['id'])

    def test_traversal_and_symlink_paths_cannot_supply_delivery_bytes(self):
        original = (self.review / 'video.mp4').read_bytes()
        outside = self.root / 'outside.mp4'; outside.write_bytes(original)
        (self.review / 'video.mp4').unlink(); (self.review / 'video.mp4').symlink_to(outside)
        with self.assertRaises(ValueError): verify_delivery(self.queue.root, self.spec['id'])
        (self.review / 'video.mp4').unlink(); (self.review / 'video.mp4').write_bytes(original)
        self.run['artifacts_sha256']['../outside.mp4'] = digest(outside); self.rebind_run()
        with self.assertRaises(ValueError): verify_delivery(self.queue.root, self.spec['id'])
        linked = self.root / 'linked'; linked.symlink_to(self.queue.root, target_is_directory=True)
        with self.assertRaises(ValueError): verify_delivery(linked, self.spec['id'])
        with self.assertRaises(ValueError): verify_delivery(self.queue.root, '../private-review')

    def test_missing_queue_status_cli_does_not_create_database(self):
        missing = self.root / 'missing'
        result = subprocess.run([sys.executable, '-m', 'integrations.content_control.review_delivery',
                                 '--queue', str(missing), '--id', 'private-review', 'status'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['status'], 'DELIVERY_BLOCKED')
        self.assertFalse(missing.exists())

    def test_shared_package_roundtrip_retains_original_hashes_and_false_gates(self):
        import zipfile
        output = self.root / 'delivery'
        before = (self.queue.root / 'queue.sqlite3').read_bytes()
        result = export_review(self.queue.root, self.spec['id'], output)
        self.assertEqual(result['status'], 'AWAITING_REVIEW')
        self.assertEqual(result['candidate_sha256'], digest(output / 'review/video.mp4'))
        self.assertFalse(result['production_approved'])
        self.assertEqual(result['provenance']['job_digest'], self.queue.get(self.spec['id'])['digest'])
        with zipfile.ZipFile(output / 'review-package.zip') as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(hashlib.sha256(archive.read('review/video.mp4')).hexdigest(), self.run['candidate_sha256'])
        with self.assertRaises(ValueError): export_review(self.queue.root, self.spec['id'], output)
        self.assertEqual(before, (self.queue.root / 'queue.sqlite3').read_bytes())

    def test_export_calls_shared_packager_only_after_verification(self):
        # Contract fixture until the shared packager's independent media tests run.
        import types
        from integrations.content_control.review_package import inspect_packet
        module = types.ModuleType('integrations.content_control.review_package')
        with patch.dict(sys.modules, {module.__name__: module}):
            module.inspect_packet = inspect_packet
            module.package_review = lambda *args, **kwargs: {'args': args, 'kwargs': kwargs}
            exported = export_review(self.queue.root, self.spec['id'], self.root / 'export')
            self.assertEqual(exported['args'][0], self.review)
            self.assertEqual(exported['kwargs']['expected_candidate_sha256'], self.run['candidate_sha256'])
            (self.review / 'video.mp4').write_text('changed')
            with self.assertRaises(ValueError): export_review(self.queue.root, self.spec['id'], self.root / 'export')


if __name__ == '__main__':
    unittest.main()
