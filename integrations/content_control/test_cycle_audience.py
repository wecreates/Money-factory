"""Synthetic observations test identity replay, not real audience performance."""
import copy
import hashlib
import json
from unittest.mock import patch
import unittest

from integrations.content_control.cycle_audience import (
    record_audience_observation, verify_audience_observation,
)
from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control import test_cycle_selection as fixtures

write = fixtures.write


class AudienceObservationTests(unittest.TestCase):
    def setUp(self):
        self.prior = fixtures.SelectionTests()
        self.prior.setUp()
        self.addCleanup(self.prior.tearDown)
        self.selection = self.prior.selection()
        self.recorded_selection = self.prior.record(self.selection)
        self.observation_path = self.prior.base / 'audience-observation.json'
        self.receipt_path = self.prior.base / 'audience-receipt.json'

    def observation(self):
        return {
            'schema_version': 1,
            'selection_receipt_sha256': hashlib.sha256(self.prior.recorded.read_bytes()).hexdigest(),
            'candidate_sha256': self.recorded_selection['candidate_sha256'],
            'package_sha256': self.recorded_selection['package_sha256'],
            'thumbnail_sha256': self.recorded_selection['thumbnail_sha256'],
            'title': self.recorded_selection['title'],
            'impressions': 100,
            'clicks': 5,
            'window_start': '2026-01-04T00:00:00Z',
            'window_end': '2026-01-05T00:00:00Z',
            'observed_at': '2026-01-06T00:00:00Z',
            'source_url': 'https://example.com/analytics',
            'evidence': 'Synthetic analytics fixture; not actual audience evidence.',
        }

    def record(self, observation=None):
        write(self.observation_path, observation or self.observation())
        return record_audience_observation(
            self.prior.root, self.prior.submitted, self.prior.recorded,
            self.observation_path, self.receipt_path)

    def test_records_hash_bound_unverified_counts_without_mutating_cycle(self):
        before = inspect_cycle(self.prior.root)
        result = self.record()
        self.assertEqual(result['status'], 'AUDIENCE_OBSERVATION_RECORDED')
        self.assertEqual(result['selection_receipt_sha256'],
                         hashlib.sha256(self.prior.recorded.read_bytes()).hexdigest())
        self.assertEqual(result['ctr'], 0.05)
        self.assertEqual(result['performance_status'], 'SUPPLIED_UNVERIFIED')
        self.assertFalse(result['audience_performance_verified'])
        self.assertFalse(result['publication_enabled'])
        self.assertFalse(result['paid_generation_enabled'])
        self.assertEqual(inspect_cycle(self.prior.root), before)

    def test_replay_reconstructs_exact_receipt_and_detects_changes(self):
        recorded = self.record()
        expected, receipt_sha = verify_audience_observation(
            self.prior.root, self.prior.submitted, self.prior.recorded,
            self.observation_path, self.receipt_path)
        self.assertEqual(expected, recorded)
        self.assertEqual(receipt_sha, hashlib.sha256(self.receipt_path.read_bytes()).hexdigest())
        changed = self.observation()
        changed['clicks'] = 6
        write(self.observation_path, changed)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            verify_audience_observation(
                self.prior.root, self.prior.submitted, self.prior.recorded,
                self.observation_path, self.receipt_path)

    def test_rejects_wrong_selection_identity_and_hidden_fields(self):
        for field, value in (
            ('selection_receipt_sha256', '0' * 64),
            ('candidate_sha256', '0' * 64),
            ('package_sha256', '0' * 64),
            ('thumbnail_sha256', '0' * 64),
            ('title', 'Different title'),
            ('publication_enabled', False),
        ):
            with self.subTest(field=field):
                observation = self.observation()
                observation[field] = value
                write(self.observation_path, observation)
                with self.assertRaises(ValueError):
                    record_audience_observation(
                        self.prior.root, self.prior.submitted, self.prior.recorded,
                        self.observation_path, self.receipt_path)
                self.assertFalse(self.receipt_path.exists())

    def test_rejects_invalid_counts_dates_and_source(self):
        cases = (
            ('impressions', True), ('clicks', 101), ('clicks', -1),
            ('window_start', '2026-01-03T23:59:59Z'),
            ('window_end', '2026-01-07T00:00:00Z'),
            ('source_url', 'https://user:secret@example.com'),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                observation = self.observation()
                observation[field] = value
                write(self.observation_path, observation)
                with self.assertRaises(ValueError):
                    record_audience_observation(
                        self.prior.root, self.prior.submitted, self.prior.recorded,
                        self.observation_path, self.receipt_path)
                self.assertFalse(self.receipt_path.exists())

    def test_rejects_rewritten_selection_and_receipt_predating_observation(self):
        self.record()
        rewritten = copy.deepcopy(self.recorded_selection)
        rewritten['next_idea_hypotheses'] = ['A rewritten hypothesis cannot validate an old receipt.']
        write(self.prior.recorded, rewritten)
        with self.assertRaisesRegex(ValueError, 'does not match the original'):
            verify_audience_observation(
                self.prior.root, self.prior.submitted, self.prior.recorded,
                self.observation_path, self.receipt_path)
        write(self.prior.recorded, self.recorded_selection)
        receipt = json.loads(self.receipt_path.read_text())
        receipt['recorded_at'] = '2026-01-05T00:00:00+00:00'
        write(self.receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, 'predates audience observation'):
            verify_audience_observation(
                self.prior.root, self.prior.submitted, self.prior.recorded,
                self.observation_path, self.receipt_path)

    def test_zero_impressions_remains_unknown_and_output_guards_hold(self):
        observation = self.observation()
        observation['impressions'] = observation['clicks'] = 0
        result = self.record(observation)
        self.assertIsNone(result['ctr'])
        original = self.receipt_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.record(observation)
        self.assertEqual(self.receipt_path.read_bytes(), original)
        with patch.dict('os.environ', {'PUBLICATION_ENABLED': 'true'}):
            with self.assertRaisesRegex(ValueError, 'must remain disabled'):
                record_audience_observation(
                    self.prior.root, self.prior.submitted, self.prior.recorded,
                    self.observation_path, self.prior.base / 'other.json')


if __name__ == '__main__':
    unittest.main()
