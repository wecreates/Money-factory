"""Synthetic readiness tests; none are actual analytics or audience evidence."""
import hashlib
import json
import unittest
from unittest.mock import patch

from integrations.content_control.cycle_audience import record_audience_observation
from integrations.content_control.cycle_learning_readiness import (
    assess_learning_readiness, verify_learning_readiness,
)
from integrations.content_control import test_cycle_selection as selection_fixtures


class LearningReadinessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = selection_fixtures.SelectionTests()
        self.fixture.setUp()
        self.output = self.fixture.base / 'learning-readiness.json'

    def tearDown(self):
        self.fixture.tearDown()

    def record(self, *, performance=False):
        selection = self.fixture.selection()
        if performance:
            selection['performance'] = self.fixture.performance(selection)
        return self.fixture.record(selection)

    def assess(self, **kwargs):
        return assess_learning_readiness(
            self.fixture.root, self.fixture.submitted, self.fixture.recorded,
            1, self.output, **kwargs)

    def test_unavailable_analytics_stays_blocked_without_inventing_zeroes(self):
        recorded = self.record()
        result = self.assess()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['reason_code'], 'VERIFIED_AUDIENCE_PERFORMANCE_UNAVAILABLE')
        self.assertEqual(result['performance_status'], 'UNAVAILABLE')
        self.assertEqual(result['hypothesis'], recorded['next_idea_hypotheses'][0])
        self.assertTrue(result['reviewer_hypothesis_replayable'])
        self.assertFalse(result['performance_informed_learning_ready'])
        self.assertTrue({'impressions', 'clicks', 'ctr'}.isdisjoint(result))
        self.assertFalse(result['publication_enabled'])

    def test_supplied_selection_counts_cannot_open_learning_gate(self):
        self.record(performance=True)
        result = self.assess()
        self.assertEqual(result['reason_code'], 'AUDIENCE_PERFORMANCE_UNVERIFIED')
        self.assertEqual(result['performance_status'], 'SUPPLIED_UNVERIFIED')
        self.assertFalse(result['audience_performance_verified'])
        self.assertFalse(result['winner_inferred'])
        self.assertTrue({'impressions', 'clicks', 'ctr', 'source_url', 'evidence'}.isdisjoint(result))

    def audience(self):
        recorded = self.record()
        observation = self.fixture.base / 'audience.json'
        receipt = self.fixture.base / 'audience-receipt.json'
        value = {
            'schema_version': 1,
            'selection_receipt_sha256': hashlib.sha256(
                self.fixture.recorded.read_bytes()).hexdigest(),
            'candidate_sha256': recorded['candidate_sha256'],
            'package_sha256': recorded['package_sha256'],
            'thumbnail_sha256': recorded['thumbnail_sha256'],
            'title': recorded['title'],
            'impressions': 100,
            'clicks': 5,
            'window_start': '2026-01-04T00:00:00Z',
            'window_end': '2026-01-05T00:00:00Z',
            'observed_at': '2026-01-06T00:00:00Z',
            'source_url': 'https://example.com/analytics',
            'evidence': 'Synthetic analytics fixture; not actual audience evidence.',
        }
        selection_fixtures.write(observation, value)
        record_audience_observation(
            self.fixture.root, self.fixture.submitted, self.fixture.recorded,
            observation, receipt)
        return observation, receipt

    def test_audience_receipt_is_bound_but_remains_blocked(self):
        observation, receipt = self.audience()
        result = self.assess(audience_observation=observation,
                             audience_receipt=receipt)
        self.assertEqual(result['performance_source'], 'audience_receipt')
        self.assertEqual(result['performance_status'], 'SUPPLIED_UNVERIFIED')
        self.assertEqual(result['audience_observation_sha256'],
                         hashlib.sha256(observation.read_bytes()).hexdigest())
        self.assertEqual(result['audience_receipt_sha256'],
                         hashlib.sha256(receipt.read_bytes()).hexdigest())
        proof, proof_sha = verify_learning_readiness(
            self.fixture.root, self.fixture.submitted, self.fixture.recorded,
            1, self.output, audience_observation=observation,
            audience_receipt=receipt)
        self.assertEqual(proof, result)
        self.assertEqual(proof_sha, hashlib.sha256(self.output.read_bytes()).hexdigest())

    def test_replay_rejects_changed_receipt_and_invalid_hypothesis(self):
        self.record()
        self.assess()
        changed = json.loads(self.output.read_text())
        changed['performance_informed_learning_ready'] = True
        selection_fixtures.write(self.output, changed)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            verify_learning_readiness(
                self.fixture.root, self.fixture.submitted, self.fixture.recorded,
                1, self.output)
        with self.assertRaisesRegex(ValueError, 'recorded reviewer hypothesis'):
            assess_learning_readiness(
                self.fixture.root, self.fixture.submitted, self.fixture.recorded,
                2, self.fixture.base / 'other-readiness.json')

    def test_replay_rejects_assessment_that_predates_retained_evidence(self):
        self.record()
        self.assess()
        changed = json.loads(self.output.read_text())
        changed['assessed_at'] = '2000-01-01T00:00:00+00:00'
        selection_fixtures.write(self.output, changed)
        with self.assertRaisesRegex(ValueError, 'predates the selection receipt'):
            verify_learning_readiness(
                self.fixture.root, self.fixture.submitted, self.fixture.recorded,
                1, self.output)

    def test_replay_rejects_assessment_that_predates_audience_receipt(self):
        observation, receipt = self.audience()
        self.assess(audience_observation=observation, audience_receipt=receipt)
        changed = json.loads(self.output.read_text())
        changed['assessed_at'] = json.loads(
            self.fixture.recorded.read_text())['recorded_at']
        selection_fixtures.write(self.output, changed)
        with self.assertRaisesRegex(ValueError, 'predates the audience receipt'):
            verify_learning_readiness(
                self.fixture.root, self.fixture.submitted, self.fixture.recorded,
                1, self.output, audience_observation=observation,
                audience_receipt=receipt)

    def test_partial_audience_paths_and_enabled_side_effects_fail_closed(self):
        self.record()
        with self.assertRaisesRegex(ValueError, 'both original observation and receipt'):
            self.assess(audience_observation=self.fixture.base / 'missing.json')
        with patch.dict('os.environ', {'PUBLICATION_ENABLED': 'true'}), \
                self.assertRaisesRegex(ValueError, 'must remain disabled'):
            assess_learning_readiness(
                self.fixture.root, self.fixture.submitted, self.fixture.recorded,
                1, self.fixture.base / 'other-readiness.json')


if __name__ == '__main__':
    unittest.main()
