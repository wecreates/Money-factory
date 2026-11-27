"""Synthetic review packets test rejection routing, not real playback or approval."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from integrations.content_control import cycle_review as review
from integrations.content_control.offline_review_record import canonical_bytes


def fixture_record(disposition='repair_required', findings=None):
    record = {
        'schema_version': 2, 'status': 'OBSERVATIONS_RECORDED',
        'candidate_sha256': 'a' * 64, 'caption_sha256': 'b' * 64,
        'recorded_at': '2026-01-04T03:30:00Z',
        'parent_video_sha256': None, 'supersedes_record_sha256': None,
        'machine_observation': {
            'identity_verified': True, 'browser_duration_seconds': 60.0,
            'natural_pass_complete': False, 'caption_pass_complete': False,
            'started_at': None, 'ended_at': None,
            'playback_intervals': [[0, 5]], 'events': [], 'invalidations': [],
        },
        'reviewer_attestation': {
            'reviewer': 'Synthetic partial reviewer', 'roles': ['watcher'],
            'review_round': 'initial', 'audio_output': 'speakers',
            'device_environment': 'Explicit synthetic unit fixture',
            'disposition': disposition,
            'summary': 'Synthetic opening lacks purposeful character action; hold candidate.',
            'watched_every_interval': False, 'listened_every_interval': False,
            'checked_voice': False, 'checked_mix': False,
            'checked_picture_and_captions': False,
        },
        'findings': findings or [], 'reviewer_attested_full_watch_listen': False,
        'review_coverage_complete': False, 'independent_acceptance': False,
        'full_av_acceptance': False, 'production_approved': False,
        'publication_enabled': False, 'paid_generation_enabled': False,
        'competitor_comparison_included': False, 'physical_phone_verified': False,
    }
    return seal(record)


def seal(record):
    record.pop('record_sha256', None)
    record['record_sha256'] = hashlib.sha256(canonical_bytes(record)).hexdigest()
    return record


class PrivateDispositionChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='private-disposition-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'record.json'
        self.snapshot = {'candidate_sha256': 'a' * 64,
                         'files_sha256': {'delivery/captions.vtt': 'b' * 64},
                         'cycle': {'finished_at': '2026-01-03T00:00:00+00:00'}}

    def receipt(self, record):
        self.path.write_text(json.dumps(record), encoding='utf-8')
        return review._private_review_receipt(self.root, self.snapshot, self.path)

    def test_negative_partial_dispositions_require_repair_without_findings(self):
        for disposition in ('repair_required', 'blocked'):
            with self.subTest(disposition=disposition):
                record = fixture_record(disposition)
                before = copy.deepcopy(record)
                receipt, feedback, _ = self.receipt(record)
                self.assertEqual(receipt['status'], 'PRIVATE_REVIEW_REPAIR_REQUIRED')
                self.assertEqual(len(feedback), 1)
                self.assertEqual(feedback[0]['check'], 'private_review.disposition')
                self.assertIn(disposition, feedback[0]['action'])
                self.assertIn(record['reviewer_attestation']['summary'], feedback[0]['action'])
                self.assertIn('Coverage remains limited', feedback[0]['action'])
                self.assertFalse(receipt['review_coverage_complete'])
                for key in ('production_approved', 'full_av_acceptance', 'independent_acceptance',
                            'publication_enabled', 'paid_generation_enabled'):
                    self.assertIs(receipt[key], False)
                self.assertEqual(json.loads(receipt['submitted_record_json']), before)
                self.assertEqual(review._validate_recorded_private_review(
                    self.root, self.snapshot, receipt), feedback)

    def test_positive_partial_record_retained_without_approval_or_feedback(self):
        receipt, feedback, _ = self.receipt(fixture_record('no_blocker_seen'))
        self.assertEqual(receipt['status'], 'PRIVATE_REVIEW_RECORDED')
        self.assertEqual(feedback, [])
        self.assertFalse(receipt['review_coverage_complete'])
        self.assertFalse(receipt['production_approved'])
        self.assertFalse(receipt['full_av_acceptance'])

    def test_long_negative_summary_routes_excerpt_and_preserves_full_source(self):
        record = fixture_record('blocked')
        summary = 'Long valid negative summary. ' * 120
        self.assertGreater(len(summary), 3000)
        record['reviewer_attestation']['summary'] = summary
        seal(record)
        receipt, feedback, _ = self.receipt(record)
        self.assertEqual(receipt['status'], 'PRIVATE_REVIEW_REPAIR_REQUIRED')
        self.assertEqual(len(feedback), 1)
        self.assertIn(summary[:1600], feedback[0]['action'])
        self.assertIn('full summary retained in submitted_record_json', feedback[0]['action'])
        self.assertLess(len(feedback[0]['action']), 2200)
        self.assertEqual(json.loads(receipt['submitted_record_json'])[
            'reviewer_attestation']['summary'], summary)
        self.assertEqual(review._validate_recorded_private_review(
            self.root, self.snapshot, receipt), feedback)
        self.assertFalse(receipt['review_coverage_complete'])
        self.assertFalse(receipt['full_av_acceptance'])

    def test_structured_open_blocker_not_duplicated_by_disposition(self):
        finding = {'start_seconds': 0, 'end_seconds': 5, 'category': 'movement_staging',
                   'severity': 'blocker', 'observation': 'Synthetic character loop has no payoff.',
                   'requested_repair': 'Stage a purposeful original action.', 'resolution_state': 'open'}
        receipt, feedback, _ = self.receipt(fixture_record(findings=[finding]))
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0]['check'], 'private_review.movement_staging')
        self.assertEqual(receipt['status'], 'PRIVATE_REVIEW_REPAIR_REQUIRED')

    def test_resolved_findings_do_not_cancel_negative_disposition(self):
        finding = {'start_seconds': 0, 'end_seconds': 5, 'category': 'caption_sync',
                   'severity': 'blocker', 'observation': 'Earlier synthetic cue issue.',
                   'requested_repair': 'Keep repaired cue.', 'resolution_state': 'resolved'}
        receipt, feedback, _ = self.receipt(fixture_record(findings=[finding]))
        self.assertEqual([item['check'] for item in feedback], ['private_review.disposition'])
        self.assertEqual(receipt['status'], 'PRIVATE_REVIEW_REPAIR_REQUIRED')

    def test_malformed_and_changed_identity_still_rejected(self):
        record = fixture_record()
        record['reviewer_attestation']['disposition'] = 'approved'
        with self.assertRaisesRegex(ValueError, 'disposition'):
            self.receipt(seal(record))
        record = fixture_record()
        record['candidate_sha256'] = 'c' * 64
        with self.assertRaisesRegex(ValueError, 'candidate identity'):
            self.receipt(seal(record))
        record = fixture_record()
        record['reviewer_attestation']['summary'] = 'tampered after signature'
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.receipt(record)


if __name__ == '__main__':
    unittest.main(verbosity=2)
