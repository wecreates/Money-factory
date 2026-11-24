"""Deterministic offline discovery-to-queue handoff tests."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest

from integrations.content_control.cycle_authoring import LONG_FORM_FORMAT
from integrations.content_control.cycle_offline_handoff import build_handoff, verify_handoff
from integrations.content_control.test_cycle_discovery import iso, reference, source
from integrations.local_agent_queue import validate as validate_queue


class OfflineHandoffTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pool = self.root / 'pool.json'
        self.output = self.root / 'handoff'
        created = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
        evidence = created - timedelta(days=1)
        self.pool.write_text(json.dumps({
            'schema_version': 1, 'created_at': iso(created), 'candidates': [
                {'id': 'fees', 'topic': 'How card fees change reward value',
                 'sources': [source('a', 'one.example', evidence),
                             source('b', 'two.example', evidence)],
                 'reference_observations': [reference(evidence, 'reference.example')]},
                {'id': 'minimums', 'topic': 'What a minimum payment does',
                 'sources': [source('c', 'one.example', evidence),
                             source('d', 'two.example', evidence),
                             source('e', 'three.example', evidence)],
                 'reference_observations': [reference(evidence, 'other-reference.example')]},
            ],
        }))

    def test_builds_replayable_long_form_queue_request_without_manual_script(self):
        manifest = build_handoff(self.pool, self.output, job_id='offline-long-form-01')
        self.assertEqual(manifest, verify_handoff(self.output))
        self.assertEqual(manifest['status'], 'VERIFIED_OFFLINE_QUEUE_HANDOFF')
        self.assertEqual(manifest['content_format'], LONG_FORM_FORMAT)
        self.assertEqual(manifest['selected_candidate_id'], 'minimums')
        self.assertFalse(manifest['publication_enabled'])
        self.assertFalse(manifest['paid_generation_enabled'])
        self.assertFalse(manifest['production_ready'])
        authoring = manifest['original_authoring']
        self.assertEqual(authoring['content_format'], LONG_FORM_FORMAT)
        self.assertGreaterEqual(authoring['planned_duration_seconds'], 120)
        self.assertEqual(authoring['speaker_sequence'][0], 'narrator')
        self.assertEqual(authoring['speaker_sequence'][-1], 'narrator')
        self.assertTrue({'narrator', 'dave', 'points_monk'}
                        <= set(authoring['speaker_sequence']))
        self.assertFalse(authoring['authorship_verified'])
        self.assertFalse(authoring['originality_review_complete'])
        self.assertFalse(authoring['long_form_production_verified'])

        job = json.loads((self.output / 'queue-job.json').read_text())
        self.assertEqual(validate_queue(job), job)
        self.assertEqual(job['request']['intake_input']['draft_json'],
                         (self.output / 'draft.json').read_text())
        self.assertFalse(job['request']['publication_enabled'])
        self.assertFalse(job['request']['paid_generation_enabled'])

    def test_standard_mode_is_bound_and_replayable(self):
        manifest = build_handoff(self.pool, self.output, job_id='offline-standard-01',
                                 content_format='standard', timeout_seconds=30,
                                 max_attempts=3)
        self.assertEqual(verify_handoff(self.output), manifest)
        self.assertEqual(manifest['content_format'], 'standard')
        self.assertNotIn('content_format', manifest['original_authoring'])
        job = json.loads((self.output / 'queue-job.json').read_text())
        self.assertEqual(job['request']['timeout_seconds'], 30)
        self.assertEqual(job['max_attempts'], 3)

    def test_tampering_is_rejected_without_rewriting_evidence(self):
        build_handoff(self.pool, self.output, job_id='offline-tamper-01')
        target = self.output / 'draft.json'
        before = target.read_bytes()
        target.write_bytes(before + b' ')
        with self.assertRaisesRegex(ValueError, 'artifact identity mismatch'):
            verify_handoff(self.output)
        self.assertEqual(target.read_bytes(), before + b' ')

    def test_fails_closed_on_flags_invalid_queue_options_and_existing_output(self):
        previous = os.environ.get('PUBLICATION_ENABLED')
        os.environ['PUBLICATION_ENABLED'] = 'true'
        try:
            with self.assertRaisesRegex(ValueError, 'must remain disabled'):
                build_handoff(self.pool, self.output, job_id='offline-flags-01')
        finally:
            if previous is None:
                os.environ.pop('PUBLICATION_ENABLED', None)
            else:
                os.environ['PUBLICATION_ENABLED'] = previous
        self.assertFalse(self.output.exists())

        with self.assertRaisesRegex(ValueError, '30..1800'):
            build_handoff(self.pool, self.output, job_id='offline-timeout-01',
                          timeout_seconds=29)
        self.assertFalse(self.output.exists())
        build_handoff(self.pool, self.output, job_id='offline-existing-01')
        with self.assertRaisesRegex(ValueError, 'Fresh offline handoff'):
            build_handoff(self.pool, self.output, job_id='offline-existing-02')


if __name__ == '__main__':
    unittest.main()
