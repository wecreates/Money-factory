"""Fixtures exercise the handoff contract; actual sources are checked separately."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from integrations.content_control.cycle_intake import prepare_brief, verify_intake
from integrations.content_control.cycle_audience import record_audience_observation
from integrations.content_control.cycle_editorial import compile_editorial
from integrations.content_control.cycle_job import brief_digest
from integrations.content_control.test_cycle_editorial import brief as sample_brief
from integrations.content_control import test_cycle_selection as selection_fixtures


class IntakeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.research, self.draft, self.output = (root / name for name in ('research.json', 'draft.json', 'ready'))
        fixture = sample_brief()
        self.research_data = {key: fixture[key] for key in ('schema_version', 'topic', 'sources', 'reference_observations')}
        self.research.write_text(json.dumps(self.research_data))
        self.draft_data = {key: fixture[key] for key in ('schema_version', 'title', 'scenes')}
        self.draft_data['research_sha256'] = hashlib.sha256(self.research.read_bytes()).hexdigest()

    def write_draft(self):
        self.draft.write_text(json.dumps(self.draft_data))

    def test_ready_brief_preserves_sources_and_binds_exact_draft(self):
        self.write_draft()
        receipt = prepare_brief(self.research, self.draft, self.output)
        raw = (self.output / 'brief.json').read_bytes()
        output = json.loads(raw)
        self.assertEqual(output['sources'], self.research_data['sources'])
        self.assertEqual(output['scenes'], self.draft_data['scenes'])
        self.assertEqual(receipt['draft_sha256'], hashlib.sha256(self.draft.read_bytes()).hexdigest())
        self.assertEqual(receipt['brief_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt['queue_brief_sha256'], brief_digest(output))
        self.assertEqual(receipt, json.loads((self.output / 'intake.json').read_text()))
        self.assertFalse(receipt['factual_review'])
        self.assertFalse(receipt['production_approved'])
        with self.assertRaisesRegex(ValueError, 'Fresh intake'):
            prepare_brief(self.research, self.draft, self.output)

    def test_draft_cannot_replace_research_or_cite_unknown_records(self):
        self.draft_data['sources'] = []
        self.write_draft()
        with self.assertRaisesRegex(ValueError, 'Unexpected intake fields'):
            prepare_brief(self.research, self.draft, self.output)
        del self.draft_data['sources']
        self.draft_data['scenes'][0]['source_ids'] = ['invented']
        self.write_draft()
        with self.assertRaisesRegex(ValueError, 'unknown source'):
            prepare_brief(self.research, self.draft, self.output)
        self.assertFalse(self.output.exists())

    def test_verify_rebuilds_existing_intake_without_writes(self):
        self.write_draft()
        created = prepare_brief(self.research, self.draft, self.output)
        paths = [self.research, self.draft, self.output / 'brief.json', self.output / 'intake.json']
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
        proof = verify_intake(self.research, self.draft, self.output)
        self.assertEqual(proof['status'], 'INTAKE_VERIFIED')
        self.assertEqual(proof['intake_receipt_sha256'], hashlib.sha256(before[-1][0]).hexdigest())
        for key in ('research_sha256', 'draft_sha256', 'brief_sha256', 'queue_brief_sha256'):
            self.assertEqual(proof[key], created[key])
        for key in ('factual_review', 'full_av_review', 'production_approved', 'publication_enabled'):
            self.assertIs(proof[key], False)
        self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in paths], before)

    def test_verify_rejects_changed_sources_draft_brief_or_receipt(self):
        self.write_draft()
        prepare_brief(self.research, self.draft, self.output)
        brief = self.output / 'brief.json'
        receipt = self.output / 'intake.json'
        bad_receipt = {**json.loads(receipt.read_bytes()), 'draft_sha256': 'not-a-digest'}
        for path, changed, error in (
            (self.research, self.research.read_bytes() + b'\n', 'exact research bytes'),
            (self.draft, self.draft.read_bytes() + b'\n', 'brief does not match'),
            (brief, brief.read_bytes() + b'\n', 'brief does not match'),
            (receipt, json.dumps(bad_receipt).encode(), 'receipt does not match'),
        ):
            with self.subTest(path=path.name):
                before = path.read_bytes()
                path.write_bytes(changed)
                with self.assertRaisesRegex(ValueError, error):
                    verify_intake(self.research, self.draft, self.output)
                self.assertEqual(path.read_bytes(), changed)
                path.write_bytes(before)

    def test_verify_accepts_legacy_windows_receipt_bytes(self):
        self.write_draft()
        prepare_brief(self.research, self.draft, self.output)
        receipt = self.output / 'intake.json'
        windows_receipt = receipt.read_bytes().replace(b'\n', b'\r\n')
        receipt.write_bytes(windows_receipt)
        proof = verify_intake(self.research, self.draft, self.output)
        self.assertEqual(proof['intake_receipt_sha256'], hashlib.sha256(windows_receipt).hexdigest())
        self.assertEqual(receipt.read_bytes(), windows_receipt)

    def test_draft_rejects_even_whitespace_changes_to_research(self):
        self.write_draft()
        self.research.write_bytes(self.research.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'exact research bytes'):
            prepare_brief(self.research, self.draft, self.output)
        self.assertFalse(self.output.exists())

    def test_formatted_brief_must_fit_renderer_limit(self):
        self.draft_data['scenes'][0]['unused'] = [[0] * 100] * 300
        self.write_draft()
        with self.assertRaisesRegex(ValueError, 'Formatted brief exceeds renderer'):
            prepare_brief(self.research, self.draft, self.output)
        self.assertFalse(self.output.exists())

    def learning_inputs(self):
        prior = selection_fixtures.SelectionTests()
        prior.setUp()
        self.addCleanup(prior.tearDown)
        selection = prior.selection()
        selection['performance'] = prior.performance(selection)
        recorded = prior.record(selection)
        self.draft_data['idea_learning'] = {
            'selection_receipt_sha256': hashlib.sha256(prior.recorded.read_bytes()).hexdigest(),
            'hypothesis_index': 1,
            'application': 'Use a shorter question and compare the two amounts side by side.',
        }
        self.write_draft()
        paths = {'prior_cycle': prior.root, 'selection_path': prior.submitted, 'selection_receipt': prior.recorded}
        return prior, recorded, paths

    def test_prior_selection_remains_bound_in_the_compiled_editorial(self):
        prior, recorded, paths = self.learning_inputs()
        receipt = prepare_brief(self.research, self.draft, self.output, **paths)
        brief = json.loads((self.output / 'brief.json').read_text())
        learning = receipt['idea_learning']
        self.assertEqual(learning, compile_editorial(brief)['idea_learning'])
        self.assertEqual(learning['prior_candidate_sha256'], prior.candidate)
        self.assertEqual(learning['prior_thumbnail_sha256'], recorded['thumbnail_sha256'])
        self.assertEqual(learning['hypothesis'], recorded['next_idea_hypotheses'][0])
        self.assertEqual(learning['prior_performance_status'], 'SUPPLIED_UNVERIFIED')
        self.assertIs(learning['audience_performance_verified'], False)
        self.assertTrue({'impressions', 'clicks', 'ctr'}.isdisjoint(learning))
        self.assertEqual(brief['sources'], self.research_data['sources'])
        brief['idea_learning']['audience_performance_verified'] = True
        with self.assertRaisesRegex(ValueError, 'must remain unverified'):
            compile_editorial(brief)

    def test_verify_revalidates_required_prior_selection(self):
        _, _, paths = self.learning_inputs()
        prepare_brief(self.research, self.draft, self.output, **paths)
        with self.assertRaisesRegex(ValueError, 'requires the prior cycle'):
            verify_intake(self.research, self.draft, self.output)
        proof = verify_intake(self.research, self.draft, self.output, **paths)
        self.assertEqual(proof['status'], 'INTAKE_VERIFIED')
        paths['selection_receipt'].write_bytes(paths['selection_receipt'].read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'does not bind this selection receipt'):
            verify_intake(self.research, self.draft, self.output, **paths)

    def test_rejects_a_changed_receipt_even_if_the_draft_rebinds_it(self):
        prior, recorded, paths = self.learning_inputs()
        recorded['next_idea_hypotheses'] = ['This text did not come from the selection.']
        selection_fixtures.write(prior.recorded, recorded)
        self.draft_data['idea_learning']['selection_receipt_sha256'] = hashlib.sha256(prior.recorded.read_bytes()).hexdigest()
        self.write_draft()
        with self.assertRaisesRegex(ValueError, 'does not match the original'):
            prepare_brief(self.research, self.draft, self.output, **paths)
        self.assertFalse(self.output.exists())

    def test_rejects_partial_paths_wrong_hypothesis_and_output_in_prior_cycle(self):
        prior, _, paths = self.learning_inputs()
        with self.assertRaisesRegex(ValueError, 'requires the prior cycle'):
            prepare_brief(self.research, self.draft, self.output, prior_cycle=prior.root)
        with self.assertRaisesRegex(ValueError, 'separate from the prior cycle'):
            prepare_brief(self.research, self.draft, prior.root / 'intake', **paths)
        self.draft_data['idea_learning']['hypothesis_index'] = 2
        self.write_draft()
        with self.assertRaisesRegex(ValueError, 'select a recorded hypothesis'):
            prepare_brief(self.research, self.draft, self.output, **paths)
        self.assertFalse(self.output.exists())

    def audience_learning_inputs(self):
        prior = selection_fixtures.SelectionTests()
        prior.setUp()
        self.addCleanup(prior.tearDown)
        selection = prior.selection()
        recorded = prior.record(selection)
        observation_path = prior.base / 'audience-observation.json'
        audience_receipt = prior.base / 'audience-receipt.json'
        observation = {
            'schema_version': 1,
            'selection_receipt_sha256': hashlib.sha256(prior.recorded.read_bytes()).hexdigest(),
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
        selection_fixtures.write(observation_path, observation)
        record_audience_observation(prior.root, prior.submitted, prior.recorded,
                                    observation_path, audience_receipt)
        self.draft_data['idea_learning'] = {
            'selection_receipt_sha256': hashlib.sha256(prior.recorded.read_bytes()).hexdigest(),
            'audience_receipt_sha256': hashlib.sha256(audience_receipt.read_bytes()).hexdigest(),
            'hypothesis_index': 1,
            'application': 'Use a shorter question and compare the two amounts side by side.',
        }
        self.write_draft()
        paths = {'prior_cycle': prior.root, 'selection_path': prior.submitted,
                 'selection_receipt': prior.recorded, 'audience_observation': observation_path,
                 'audience_receipt': audience_receipt}
        return prior, recorded, observation_path, audience_receipt, paths

    def test_audience_receipt_feeds_one_hypothesis_without_promoting_metrics(self):
        prior, recorded, observation_path, audience_receipt, paths = self.audience_learning_inputs()
        receipt = prepare_brief(self.research, self.draft, self.output, **paths)
        brief = json.loads((self.output / 'brief.json').read_text())
        learning = receipt['idea_learning']
        self.assertEqual(learning, compile_editorial(brief)['idea_learning'])
        self.assertEqual(learning['selection_receipt_sha256'],
                         hashlib.sha256(prior.recorded.read_bytes()).hexdigest())
        self.assertEqual(learning['audience_observation_sha256'],
                         hashlib.sha256(observation_path.read_bytes()).hexdigest())
        self.assertEqual(learning['audience_receipt_sha256'],
                         hashlib.sha256(audience_receipt.read_bytes()).hexdigest())
        self.assertEqual(learning['prior_candidate_sha256'], prior.candidate)
        self.assertEqual(learning['prior_thumbnail_sha256'], recorded['thumbnail_sha256'])
        self.assertEqual(learning['hypothesis'], recorded['next_idea_hypotheses'][0])
        self.assertEqual(learning['prior_performance_status'], 'SUPPLIED_UNVERIFIED')
        self.assertIs(learning['audience_performance_verified'], False)
        self.assertTrue({'impressions', 'clicks', 'ctr', 'source_url', 'evidence'}.isdisjoint(learning))
        proof = verify_intake(self.research, self.draft, self.output, **paths)
        self.assertEqual(proof['idea_learning'], learning)

    def test_audience_learning_requires_exact_original_evidence(self):
        _, _, observation_path, audience_receipt, paths = self.audience_learning_inputs()
        for missing in ('audience_observation', 'audience_receipt'):
            with self.subTest(missing=missing), self.assertRaisesRegex(
                    ValueError, 'Audience-bound learning requires'):
                prepare_brief(self.research, self.draft, self.output,
                              **{key: value for key, value in paths.items() if key != missing})
            self.assertFalse(self.output.exists())
        wrong = dict(self.draft_data['idea_learning'], audience_receipt_sha256='0' * 64)
        self.draft_data['idea_learning'] = wrong
        self.write_draft()
        with self.assertRaisesRegex(ValueError, 'does not bind this audience receipt'):
            prepare_brief(self.research, self.draft, self.output, **paths)
        self.assertFalse(self.output.exists())
        self.draft_data['idea_learning']['audience_receipt_sha256'] = hashlib.sha256(
            audience_receipt.read_bytes()).hexdigest()
        self.write_draft()
        observation_path.write_bytes(observation_path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            prepare_brief(self.research, self.draft, self.output, **paths)
        self.assertFalse(self.output.exists())

    def test_audience_learning_schema_rejects_missing_identity_or_promoted_status(self):
        _, _, _, _, paths = self.audience_learning_inputs()
        prepare_brief(self.research, self.draft, self.output, **paths)
        brief = json.loads((self.output / 'brief.json').read_text())
        for mutate, error in (
            (lambda value: value.pop('audience_observation_sha256'), 'exact handoff fields'),
            (lambda value: value.update(prior_performance_status='UNAVAILABLE'),
             'audience receipt must remain supplied'),
            (lambda value: value.update(audience_performance_verified=True), 'must remain unverified'),
        ):
            changed = json.loads(json.dumps(brief))
            mutate(changed['idea_learning'])
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                compile_editorial(changed)
