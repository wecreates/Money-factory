"""Exercise replay of structured private-review evidence."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from integrations.content_control.offline_review_record import canonical_bytes, verify_record


VIDEO = hashlib.sha256(b'video').hexdigest()
CAPTIONS = hashlib.sha256(b'captions').hexdigest()


class OfflineReviewRecordTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'review.json'

    def record(self, *, complete=True, disposition='no_blocker_seen', findings=None):
        value = {
            'schema_version': 2,
            'status': 'FULL_REVIEW_RECORDED' if complete else 'OBSERVATIONS_RECORDED',
            'candidate_sha256': VIDEO,
            'caption_sha256': CAPTIONS,
            'recorded_at': '2026-11-25T19:00:00.000Z',
            'parent_video_sha256': None,
            'supersedes_record_sha256': None,
            'machine_observation': {
                'identity_verified': True,
                'browser_duration_seconds': 2.0,
                'natural_pass_complete': complete,
                'caption_pass_complete': complete,
                'started_at': '2026-11-25T18:59:58.000Z' if complete else None,
                'ended_at': '2026-11-25T19:00:00.000Z' if complete else None,
                'playback_intervals': [[0, 2]],
                'events': ([{'type': 'natural_pass_reset'},
                            {'type': 'natural_pass_started', 'valid': True},
                            {'type': 'playback_ended', 'natural_pass_complete': True}]
                           if complete else [{'type': 'pass_invalidated'}]),
                'invalidations': [] if complete else ['test blocked pass'],
            },
            'reviewer_attestation': {
                'reviewer': 'local reviewer',
                'roles': ['watcher', 'listener'],
                'review_round': 'initial',
                'audio_output': 'headphones',
                'device_environment': 'Local browser and headphones',
                'disposition': disposition,
                'summary': 'Complete pass recorded.',
                'watched_every_interval': complete,
                'listened_every_interval': complete,
                'checked_voice': complete,
                'checked_mix': complete,
                'checked_picture_and_captions': complete,
            },
            'findings': findings or [],
            'reviewer_attested_full_watch_listen': complete,
            'review_coverage_complete': complete,
            'independent_acceptance': False,
            'full_av_acceptance': False,
            'production_approved': False,
            'publication_enabled': False,
            'paid_generation_enabled': False,
            'competitor_comparison_included': False,
            'physical_phone_verified': False,
        }
        value['record_sha256'] = hashlib.sha256(canonical_bytes(value)).hexdigest()
        self.path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        return value

    def rehash(self, value):
        value.pop('record_sha256', None)
        value['record_sha256'] = hashlib.sha256(canonical_bytes(value)).hexdigest()
        self.path.write_text(json.dumps(value))

    def test_complete_record_replays_without_granting_acceptance(self):
        original = self.record()
        replay = verify_record(self.path, video_sha256=VIDEO, caption_sha256=CAPTIONS)
        self.assertEqual(replay['record_sha256'], original['record_sha256'])
        self.assertTrue(replay['review_coverage_complete'])
        self.assertFalse(replay['independent_acceptance'])

    def test_partial_record_is_retained_honestly(self):
        self.record(complete=False, disposition='blocked')
        replay = verify_record(self.path, video_sha256=VIDEO, caption_sha256=CAPTIONS)
        self.assertEqual(replay['status'], 'OBSERVATIONS_RECORDED')
        self.assertFalse(replay['review_coverage_complete'])

    def test_identity_digest_and_safety_tampering_fail_closed(self):
        for field, changed, message in (
                ('candidate_sha256', '0' * 64, 'identity mismatch'),
                ('publication_enabled', True, 'must remain false'),
                ('review_coverage_complete', False, 'does not match')):
            with self.subTest(field=field):
                value = self.record()
                value[field] = changed
                if field != 'candidate_sha256':
                    self.rehash(value)
                else:
                    self.path.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, message):
                    verify_record(self.path, video_sha256=VIDEO, caption_sha256=CAPTIONS)

    def test_unrehashable_mutation_and_blocker_disposition_are_rejected(self):
        value = self.record()
        value['reviewer_attestation']['summary'] = 'Changed after export.'
        self.path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            verify_record(self.path, video_sha256=VIDEO, caption_sha256=CAPTIONS)

        blocker = {'start_seconds': 0, 'end_seconds': 1,
                   'category': 'pronunciation', 'severity': 'blocker',
                   'observation': 'Name is mispronounced.',
                   'requested_repair': 'Regenerate the isolated phrase.',
                   'resolution_state': 'open'}
        self.record(findings=[blocker])
        with self.assertRaisesRegex(ValueError, 'requires repair'):
            verify_record(self.path, video_sha256=VIDEO, caption_sha256=CAPTIONS)

    def test_rehashed_false_machine_evidence_cannot_claim_complete_review(self):
        changes = (
            (lambda value: value['machine_observation'].__setitem__('identity_verified', False),
             'verified exact identities'),
            (lambda value: value['machine_observation'].__setitem__('browser_duration_seconds', None),
             'duration'),
            (lambda value: value['machine_observation'].__setitem__('playback_intervals', []),
             'playback intervals'),
            (lambda value: value['machine_observation'].__setitem__('started_at', None),
             'start and end timestamps'),
            (lambda value: value['machine_observation'].__setitem__('events', []),
             'natural-pass start event'),
            (lambda value: value['machine_observation'].__setitem__(
                'events', list(reversed(value['machine_observation']['events']))),
             'start before terminal end'),
            (lambda value: value['machine_observation'].__setitem__('invalidations', ['hidden']),
             'pass invalidations'),
            (lambda value: value['reviewer_attestation'].__setitem__('roles', ['not-a-role']),
             'reviewer roles'),
            (lambda value: value['reviewer_attestation'].__setitem__('reviewer', '  '),
             'Reviewer label'),
            (lambda value: value['reviewer_attestation'].__setitem__('device_environment', ''),
             'device and environment'),
        )
        for mutate, message in changes:
            with self.subTest(message=message):
                value = self.record()
                mutate(value)
                self.rehash(value)
                with self.assertRaisesRegex(ValueError, message):
                    verify_record(self.path, video_sha256=VIDEO, caption_sha256=CAPTIONS)

    def test_finding_bounds_repair_and_revision_lineage_fail_closed(self):
        blocker = {'start_seconds': 0, 'end_seconds': 1,
                   'category': 'pronunciation', 'severity': 'blocker',
                   'observation': 'Name is mispronounced.',
                   'requested_repair': '', 'resolution_state': 'open'}
        self.record(disposition='repair_required', findings=[blocker])
        with self.assertRaisesRegex(ValueError, 'requested repair'):
            verify_record(self.path, video_sha256=VIDEO, caption_sha256=CAPTIONS)

        blocker['requested_repair'] = 'Regenerate the phrase.'
        blocker['end_seconds'] = 3
        self.record(disposition='repair_required', findings=[blocker])
        with self.assertRaisesRegex(ValueError, 'outside the video'):
            verify_record(self.path, video_sha256=VIDEO, caption_sha256=CAPTIONS)

        value = self.record()
        value['reviewer_attestation']['review_round'] = 'post_repair'
        self.rehash(value)
        with self.assertRaisesRegex(ValueError, 'different parent'):
            verify_record(self.path, video_sha256=VIDEO, caption_sha256=CAPTIONS)

        value = self.record()
        value['parent_video_sha256'] = '1' * 64
        self.rehash(value)
        with self.assertRaisesRegex(ValueError, 'must not claim'):
            verify_record(self.path, video_sha256=VIDEO, caption_sha256=CAPTIONS)

    def test_canonical_digest_is_key_order_independent(self):
        value = {'é': [3, 2, 1], 'a': {'z': False, 'b': 'text'}}
        reordered = {'a': {'b': 'text', 'z': False}, 'é': [3, 2, 1]}
        self.assertEqual(canonical_bytes(value), canonical_bytes(reordered))


if __name__ == '__main__':
    unittest.main()
