"""Recorder tests use fixture media and explicitly synthetic observations."""
from datetime import datetime, timezone
import json
import shutil
import unittest
from unittest.mock import patch

from integrations.content_control import test_cycle_queue_short_review as fixtures
from integrations.content_control.cycle_queue_short_attestation import (
    UNVERIFIED, prepare_submission, record_attestation, verify_attestation,
)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'Media tools unavailable')
class QueueShortAttestationTests(unittest.TestCase):
    setUp = fixtures.QueueShortReviewTests.setUp
    tearDown = fixtures.QueueShortReviewTests.tearDown
    queue_review = fixtures.QueueShortReviewTests.queue_review
    prepare = fixtures.QueueShortReviewTests.prepare

    def filled_submission(self, queue, short):
        value = prepare_submission(queue.root, 'cycle-test', short)
        for role, timestamp in (('watcher', 'watched_at'), ('listener', 'listened_at')):
            review = value[role + '_review']
            self.assertEqual(review['coverage'], [])
            self.assertTrue(all(check['passed'] is None for check in review['checks'].values()))
            review[role] = 'Synthetic ' + role + ' fixture'
            review[timestamp] = datetime.now(timezone.utc).isoformat()
            review['coverage'] = [{'start_seconds': 0, 'end_seconds': value['duration_seconds']}]
            for check in review['checks'].values():
                check.update(passed=True, evidence='Synthetic observation, not real review.')
        return value

    def test_complete_observations_replay_without_acceptance(self):
        queue, short, bound = self.prepare(caption_safe_area=True)
        submitted = self.base / 'submitted-short-av.json'
        output = self.base / 'recorded-short-av.json'
        submitted.write_text(json.dumps(self.filled_submission(queue, short)))
        queue_before = (queue.root / 'queue.sqlite3').read_bytes()
        recorded = record_attestation(queue.root, 'cycle-test', short, submitted, output)
        self.assertEqual(recorded['status'], 'WATCH_LISTEN_ATTESTATION_RECORDED')
        self.assertEqual(recorded['candidate_sha256'], bound['candidate_sha256'])
        self.assertEqual(recorded['caption_sha256'], bound['caption_sha256'])
        self.assertEqual(recorded['preview_caption_mode'], 'burned')
        self.assertEqual(recorded['encoded_streams_sha256']['audio'], bound['encoded_streams_sha256']['audio'])
        self.assertEqual(recorded['parent_voice_receipt_sha256'], fixtures.digest(self.render / 'voice.json'))
        self.assertTrue(all(recorded[key] is False for key in UNVERIFIED))
        self.assertEqual(verify_attestation(queue.root, 'cycle-test', short, output), recorded)
        self.assertEqual((queue.root / 'queue.sqlite3').read_bytes(), queue_before)

        recorded['full_av_review'] = 0
        output.write_text(json.dumps(recorded))
        with self.assertRaisesRegex(ValueError, 'cannot grant verification'):
            verify_attestation(queue.root, 'cycle-test', short, output)

    def test_fails_closed_on_stale_target_partial_coverage_and_asr(self):
        queue, short, _ = self.prepare()
        for label, expected in (('caption_sha256', 'different derivative identities'),
                                ('partial', 'complete program'),
                                ('basis', 'Direct listener observation')):
            with self.subTest(case=label):
                value = self.filled_submission(queue, short)
                if label == 'caption_sha256':
                    value[label] = '0' * 64
                elif label == 'partial':
                    value['listener_review']['coverage'][0]['end_seconds'] /= 2
                else:
                    value['listener_review']['basis'] = 'asr_transcript'
                submitted = self.base / (label + '.json')
                submitted.write_text(json.dumps(value))
                output = self.base / 'must-not-record.json'
                with self.assertRaisesRegex(ValueError, expected):
                    record_attestation(queue.root, 'cycle-test', short, submitted, output)
                self.assertFalse(output.exists())

    def test_failed_observations_keep_repair_feedback_and_refuse_publication(self):
        queue, short, _ = self.prepare()
        value = self.filled_submission(queue, short)
        value['listener_review']['checks']['pronunciation'] = {
            'passed': False, 'evidence': 'Synthetic pronunciation note at 00:00.250.',
            'feedback': 'Replace the affected spoken phrase and replay this Short.',
        }
        submitted = self.base / 'submitted-listener-repair.json'
        output = self.base / 'recorded-listener-repair.json'
        submitted.write_text(json.dumps(value))
        with patch.dict('os.environ', {'PUBLICATION_ENABLED': 'true'}):
            with self.assertRaisesRegex(ValueError, 'must remain disabled'):
                record_attestation(queue.root, 'cycle-test', short, submitted, output)
        recorded = record_attestation(queue.root, 'cycle-test', short, submitted, output)
        self.assertEqual(recorded['status'], 'REVISION_REQUIRED')
        self.assertEqual(recorded['feedback'], [{
            'check': 'listener.pronunciation',
            'action': 'Replace the affected spoken phrase and replay this Short.',
        }])
        self.assertTrue(all(recorded[key] is False for key in UNVERIFIED))
