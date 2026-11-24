"""Orchestrator failure routing with real editorial validation and fake media.

Mocks exercise orchestration only; media behavior has independent integration
tests and is never inferred from these synthetic render/package fixtures.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control import complete_cycle as m
from integrations.content_control.cycle_audience import record_audience_observation
from integrations.content_control.cycle_intake import prepare_brief
from integrations.content_control import test_cycle_selection as selection_fixtures
from integrations.content_control.test_cycle_editorial import brief


class CompleteCycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'input.json'; self.source.write_text(json.dumps(brief()))
        self.output = self.root / 'attempt'

    def render(self, editorial, output, **kwargs):
        output.mkdir()
        (output / 'video.mp4').write_bytes(b'synthetic orchestration fixture')
        return {'technical_status': 'PASS', 'candidate_sha256': m.digest(output / 'video.mp4'),
                'publication_enabled': False, 'paid_generation_enabled': False,
                'production_approved': False, 'full_av_review': False}

    def package(self, editorial, render, output, **kwargs):
        output.mkdir()
        receipt = {'status': 'AWAITING_REVIEW', 'technical_status': 'PASS',
                   'candidate_sha256': m.digest(render / 'video.mp4'),
                   'publication_enabled': False, 'paid_generation_enabled': False,
                   'production_approved': False, 'full_av_review': False}
        (output / 'package.json').write_text(json.dumps(receipt))
        (output / 'review-package.zip').write_bytes(b'synthetic archive fixture')
        return dict(receipt, archive_sha256=m.digest(output / 'review-package.zip'))

    def execute(self, render=None, package=None, **kwargs):
        with patch.object(m, 'render_cycle', side_effect=render or self.render), \
                patch.object(m, 'package_cycle', side_effect=package or self.package):
            return m.run_cycle(self.source, self.output, voice_python='/unused/python', voice_root='/unused/voice', **kwargs)

    def revision(self):
        from integrations.content_control.test_cycle_lineage import handoff
        path = self.root / 'revision.json'
        path.write_text(json.dumps(handoff(m.digest(self.source)), indent=2) + '\n')
        return path

    def intake(self):
        sample = brief()
        research, draft = self.root / 'research.json', self.root / 'draft.json'
        research.write_text(json.dumps({key: sample[key] for key in
                                        ('schema_version', 'topic', 'sources', 'reference_observations')}))
        draft.write_text(json.dumps({key: sample[key] for key in ('schema_version', 'title', 'scenes')} |
                                    {'research_sha256': m.digest(research)}))
        directory = self.root / 'intake'
        prepare_brief(research, draft, directory)
        self.source = directory / 'brief.json'
        return {'research_path': research, 'draft_path': draft}, directory / 'intake.json'

    @staticmethod
    def audience_learning():
        return {
            'selection_receipt_sha256': '1' * 64,
            'prior_candidate_sha256': '2' * 64,
            'prior_package_sha256': '3' * 64,
            'prior_thumbnail_sha256': '4' * 64,
            'audience_observation_sha256': '5' * 64,
            'audience_receipt_sha256': '6' * 64,
            'hypothesis_index': 1,
            'hypothesis': 'Test simpler wording in the next unpublished candidate.',
            'application': 'Use a shorter question in the next unpublished candidate.',
            'prior_performance_status': 'SUPPLIED_UNVERIFIED',
            'audience_performance_verified': False,
        }

    def audience_intake(self):
        prior = selection_fixtures.SelectionTests()
        prior.setUp(); self.addCleanup(prior.tearDown)
        selection = prior.selection()
        recorded = prior.record(selection)
        observation = prior.base / 'audience.json'
        audience_receipt = prior.base / 'audience-receipt.json'
        selection_fixtures.write(observation, {
            'schema_version': 1,
            'selection_receipt_sha256': m.digest(prior.recorded),
            'candidate_sha256': recorded['candidate_sha256'],
            'package_sha256': recorded['package_sha256'],
            'thumbnail_sha256': recorded['thumbnail_sha256'],
            'title': recorded['title'],
            'impressions': 100, 'clicks': 5,
            'window_start': '2026-01-04T00:00:00Z',
            'window_end': '2026-01-05T00:00:00Z',
            'observed_at': '2026-01-06T00:00:00Z',
            'source_url': 'https://example.com/analytics',
            'evidence': 'Synthetic analytics fixture; not actual audience evidence.',
        })
        record_audience_observation(prior.root, prior.submitted, prior.recorded,
                                    observation, audience_receipt)
        sample = brief()
        research, draft = self.root / 'audience-research.json', self.root / 'audience-draft.json'
        research.write_text(json.dumps({key: sample[key] for key in
                                        ('schema_version', 'topic', 'sources', 'reference_observations')}))
        draft.write_text(json.dumps({key: sample[key] for key in ('schema_version', 'title', 'scenes')} | {
            'research_sha256': m.digest(research),
            'idea_learning': {'selection_receipt_sha256': m.digest(prior.recorded),
                              'audience_receipt_sha256': m.digest(audience_receipt),
                              'hypothesis_index': 1,
                              'application': 'Use a shorter question in the next unpublished candidate.'}}))
        directory = self.root / 'audience-intake'
        inputs = {'research_path': research, 'draft_path': draft, 'prior_cycle': prior.root,
                  'selection_path': prior.submitted, 'selection_receipt': prior.recorded,
                  'audience_observation': observation, 'audience_receipt': audience_receipt}
        prepare_brief(research, draft, directory, **{key: value for key, value in inputs.items()
                                                     if key not in ('research_path', 'draft_path')})
        self.source = directory / 'brief.json'
        return inputs

    def test_explicit_verified_intake_is_bound_to_completed_brief(self):
        inputs, receipt = self.intake()
        result = self.execute(intake_inputs=inputs)
        self.assertEqual(result['status'], 'AWAITING_REVIEW')
        proof = result['verified_intake']
        self.assertEqual(proof['status'], 'INTAKE_VERIFIED')
        self.assertEqual(proof['brief_sha256'], m.digest(self.output / 'brief.json'))
        self.assertEqual(proof['intake_receipt_sha256'], m.digest(receipt))
        self.assertFalse(proof['factual_review'])
        self.assertFalse(proof['publication_enabled'])
        self.assertFalse(result['production_approved'])
        self.assertIn('cycle_intake.py', result['tool_sha256'])
        self.assertEqual(result['steps'][-1], {'name': 'intake', 'status': 'PASS'})

    def test_audience_learning_requires_matching_verified_intake(self):
        value = brief(); value['idea_learning'] = self.audience_learning()
        self.source.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'exact replayable verified intake'):
            self.execute(render=lambda *a, **k: self.fail('Rendered forged learning'))
        self.assertFalse(self.output.exists())

    def test_verified_audience_learning_binds_audience_tool(self):
        result = self.execute(intake_inputs=self.audience_intake())
        self.assertEqual(result['status'], 'AWAITING_REVIEW')
        self.assertIn('audience_receipt_sha256', result['verified_intake']['idea_learning'])
        self.assertIn('cycle_audience.py', result['tool_sha256'])
        self.assertEqual(result['tool_sha256']['cycle_audience.py'],
                         m.digest(Path(m.__file__).parent / 'cycle_audience.py'))

    def test_legacy_brief_does_not_claim_neighboring_intake(self):
        self.intake()
        self.assertNotIn('verified_intake', self.execute())

    def test_changed_intake_rejected_before_render(self):
        inputs, _ = self.intake()
        with inputs['research_path'].open('ab') as stream:
            stream.write(b'\n')
        with self.assertRaisesRegex(ValueError, 'exact research bytes'):
            self.execute(intake_inputs=inputs, render=lambda *a, **k: self.fail('Rendered changed intake'))
        self.assertFalse(self.output.exists())

    def test_intake_mutation_during_package_blocks_success(self):
        inputs, receipt = self.intake()
        original = receipt.read_bytes()
        def mutate(editorial, render, output, **kwargs):
            result = self.package(editorial, render, output, **kwargs)
            # Valid legacy CRLF serialization, but no longer the verified identity.
            receipt.write_bytes(original.replace(b'\n', b'\r\n'))
            return result
        result = self.execute(intake_inputs=inputs, package=mutate)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['failed_step'], 'intake')
        self.assertEqual(result['verified_intake']['intake_receipt_sha256'], hashlib.sha256(original).hexdigest())

    def test_explicit_revision_retained_but_neighbor_not_autodetected(self):
        revision = self.revision()
        self.assertNotIn('revision_lineage', self.execute())
        self.output = self.root / 'revised-attempt'
        result = self.execute(revision_path=revision)
        self.assertEqual(result['status'], 'AWAITING_REVIEW')
        self.assertEqual(result['revision_lineage']['revision_sha256'], m.digest(revision))
        self.assertEqual(result['revision_lineage']['revision_json'], revision.read_text())
        self.assertFalse(result['revision_lineage']['feedback_resolution_verified'])
        self.assertIn('cycle_lineage.py', result['tool_sha256'])

    def test_invalid_revision_fails_before_render(self):
        revision = self.revision()
        value = json.loads(revision.read_text()); value['brief_sha256'] = '0' * 64
        revision.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'different brief'):
            self.execute(revision_path=revision, render=lambda *a, **k: self.fail('Rendered invalid revision'))
        self.assertFalse(self.output.exists())

    def test_revision_mutation_prevents_completion(self):
        revision = self.revision()
        original = revision.read_text()
        def mutate(editorial, render, output, **kwargs):
            result = self.package(editorial, render, output, **kwargs)
            revision.write_text(original + '\n')
            return result
        result = self.execute(revision_path=revision, package=mutate)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('Revision handoff changed', result['reason'])
        self.assertEqual(result['revision_lineage']['revision_json'], original)

    def test_all_stages_keep_approval_closed(self):
        result = self.execute()
        self.assertEqual(result['status'], 'AWAITING_REVIEW')
        self.assertEqual(result['technical_status'], 'PASS')
        for key in ('publication_enabled', 'paid_generation_enabled', 'production_ready', 'full_av_review'):
            self.assertFalse(result[key])
        self.assertEqual(result['package_sha256'], m.digest(self.output / 'delivery/package.json'))
        self.assertEqual([s['name'] for s in result['steps']], ['editorial', 'render', 'package'])

    def test_render_hash_mismatch_never_packages(self):
        def bad(editorial, output, **kwargs):
            result = self.render(editorial, output, **kwargs)
            result['candidate_sha256'] = '0' * 64
            return result
        result = self.execute(render=bad, package=lambda *a, **k: self.fail('Package called after invalid render'))
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['failed_step'], 'render')

    def test_explicit_minimum_reaches_renderer_and_shortfall_never_packages(self):
        def shortfall(editorial, output, **kwargs):
            self.assertEqual(kwargs['minimum_duration'], 510)
            return {'technical_status': 'FAIL'}
        result = self.execute(render=shortfall, minimum_duration=510,
                              package=lambda *a, **k: self.fail('Packaged shortfall'))
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['failed_step'], 'render')
        self.assertEqual(result['minimum_duration_seconds'], 510)

    def portrait_source(self):
        data = brief()
        data['portrait_handoff'] = {
            **dict.fromkeys(('candidate_sha256', 'cycle_sha256', 'brief_sha256', 'package_sha256', 'render_sha256'),
                            'a' * 64),
            'scenes': [{'scene_id': 's1', 'start_seconds': 3, 'end_seconds': 9},
                       {'scene_id': 's2', 'start_seconds': 9, 'end_seconds': 12}],
        }
        self.source.write_text(json.dumps(data))
        return data

    def test_verified_portrait_handoff_applies_measured_maximum_only_to_derivative(self):
        self.portrait_source()

        def render_with_maximum(editorial, output, **kwargs):
            self.assertEqual(kwargs['maximum_duration'], 60)
            return self.render(editorial, output, **kwargs)

        result = self.execute(render=render_with_maximum)
        self.assertEqual(result['status'], 'AWAITING_REVIEW', result)
        self.assertEqual(result['maximum_duration_seconds'], 60)

    def test_malformed_portrait_handoff_or_conflicting_minimum_rejected_before_render(self):
        data = self.portrait_source()
        with self.assertRaisesRegex(ValueError, 'minimum exceeds'):
            self.execute(minimum_duration=61)
        data['portrait_handoff']['scenes'][1]['start_seconds'] = 8
        self.source.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'contiguous'):
            self.execute()
        self.assertFalse(self.output.exists())

    def test_failed_render_is_retained_as_blocked(self):
        result = self.execute(render=lambda *a, **k: {'technical_status': 'FAIL'})
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(json.loads((self.output / 'cycle.json').read_text())['failed_step'], 'render')

    def test_failed_package_and_different_candidate_block(self):
        for fail in ('exception', 'mismatch', 'failed_status'):
            with self.subTest(fail=fail):
                self.output = self.root / fail
                def bad(editorial, render, output, **kwargs):
                    if fail == 'exception': raise RuntimeError('Package failed')
                    result = self.package(editorial, render, output, **kwargs)
                    if fail == 'mismatch': result['candidate_sha256'] = '0' * 64
                    else: result['status'] = 'BLOCKED'; result['technical_status'] = 'FAIL'
                    return result
                result = self.execute(package=bad)
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertEqual(result['failed_step'], 'package')

    def test_input_mutation_prevents_completion(self):
        def mutate(editorial, render, output, **kwargs):
            result = self.package(editorial, render, output, **kwargs)
            self.source.write_text('{}')
            return result
        result = self.execute(package=mutate)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('Input brief changed', result['reason'])

    def test_output_never_overwritten(self):
        self.output.mkdir(); marker = self.output / 'keep'; marker.write_text('unchanged')
        with self.assertRaises(FileExistsError): self.execute()
        self.assertEqual(marker.read_text(), 'unchanged')


class CheckpointCLITests(unittest.TestCase):
    def invoke(self, status, checkpoint_error=None):
        import contextlib
        import io
        args = ['complete_cycle', '--brief', '/brief', '--output', '/cycle',
                '--voice-python', '/python', '--voice-root', '/voice', '--checkpoint', '/backup.zip']
        result = {'status': status, 'publication_enabled': False}
        stream = io.StringIO()
        with patch('sys.argv', args), patch.object(m, 'run_cycle', return_value=result), \
                patch('integrations.content_control.cycle_checkpoint.create_checkpoint',
                      side_effect=checkpoint_error, return_value={'status': 'CHECKPOINT_CREATED'}) as backup, \
                contextlib.redirect_stdout(stream):
            code = m.main()
        return code, json.loads(stream.getvalue()), backup, result

    def test_completed_cycle_requests_backup_without_mutating_receipt(self):
        code, output, backup, original = self.invoke('AWAITING_REVIEW')
        self.assertEqual(code, 0)
        backup.assert_called_once_with('/cycle', '/backup.zip')
        self.assertNotIn('checkpoint', original)
        self.assertFalse(output['publication_enabled'])

    def test_failed_cycle_does_not_attempt_checkpoint(self):
        code, output, backup, original = self.invoke('BLOCKED')
        self.assertEqual(code, 2)
        backup.assert_not_called()

    def test_backup_failure_is_visible_without_relabeling_completed_media(self):
        code, output, backup, original = self.invoke('AWAITING_REVIEW', ValueError('disk full'))
        self.assertEqual(code, 2)
        self.assertEqual(output['status'], 'AWAITING_REVIEW')
        self.assertEqual(output['checkpoint']['status'], 'BLOCKED')
        self.assertNotIn('checkpoint', original)

    def test_cli_rejects_partial_verified_intake_path_options(self):
        import contextlib
        import io
        args = ['complete_cycle', '--brief', '/brief', '--output', '/cycle',
                '--voice-python', '/python', '--voice-root', '/voice', '--intake-prior-cycle', '/prior']
        with patch('sys.argv', args), patch.object(m, 'run_cycle') as run, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            m.main()
        run.assert_not_called()

    def test_cli_hands_original_intake_paths_to_production(self):
        import contextlib
        import io
        args = ['complete_cycle', '--brief', '/intake/brief.json', '--output', '/cycle',
                '--voice-python', '/python', '--voice-root', '/voice',
                '--intake-research', '/research', '--intake-draft', '/draft',
                '--intake-prior-cycle', '/prior', '--intake-selection', '/selection',
                '--intake-selection-receipt', '/receipt',
                '--intake-audience-observation', '/audience-observation',
                '--intake-audience-receipt', '/audience-receipt']
        with patch('sys.argv', args), patch.object(m, 'run_cycle', return_value={'status': 'AWAITING_REVIEW'}) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(), 0)
        self.assertEqual(run.call_args.kwargs['intake_inputs'],
                         {'research_path': '/research', 'draft_path': '/draft',
                          'prior_cycle': '/prior', 'selection_path': '/selection', 'selection_receipt': '/receipt',
                          'audience_observation': '/audience-observation',
                          'audience_receipt': '/audience-receipt'})

    def test_cli_rejects_partial_audience_learning_evidence(self):
        import contextlib
        import io
        args = ['complete_cycle', '--brief', '/brief', '--output', '/cycle',
                '--voice-python', '/python', '--voice-root', '/voice',
                '--intake-research', '/research', '--intake-draft', '/draft',
                '--intake-audience-observation', '/audience-observation']
        with patch('sys.argv', args), patch.object(m, 'run_cycle') as run, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            m.main()
        run.assert_not_called()


if __name__ == '__main__': unittest.main()
