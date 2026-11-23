"""Orchestrator failure routing with real editorial validation and fake media.

Mocks exercise orchestration only; media behavior has independent integration
tests and is never inferred from these synthetic render/package fixtures.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control import complete_cycle as m
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


if __name__ == '__main__': unittest.main()
