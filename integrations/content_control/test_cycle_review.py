"""Small synthetic packets exercise identity/attestation rules, not real media QA."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from integrations.content_control.cycle_editorial import LEARNING_IDENTITIES, compile_editorial
from integrations.content_control.cycle_package import editorial_digest
from integrations.content_control.cycle_live_comparison import record_live_comparison
from integrations.content_control.cycle_review import (CHECKS, LISTENER_CHECKS, WATCHER_CHECKS, inspect_cycle,
                                                       lint_package, record_review, revision_brief)
from integrations.content_control.cycle_render import VOICE_ASSIGNMENTS
from integrations.content_control.review_package import digest
from integrations.content_control.test_cycle_editorial import brief
from integrations.content_control.test_cycle_live_comparison import packet as comparison_packet


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'cycle'; self.root.mkdir()
        self.delivery = self.root / 'delivery'; self.delivery.mkdir()
        self.render = self.root / 'render'; self.render.mkdir()
        self.flags = {'publication_enabled': False, 'paid_generation_enabled': False,
                      'production_approved': False, 'full_av_review': False}
        editorial = compile_editorial(brief())
        write(self.root / 'brief.json', brief())
        write(self.root / 'editorial.json', editorial)
        write(self.delivery / 'editorial.json', editorial)
        (self.delivery / 'video.mp4').write_bytes(b'SYNTHETIC_VIDEO_FIXTURE_NOT_MEDIA')
        (self.delivery / 'captions.vtt').write_text('WEBVTT\n')
        self.candidate = digest(self.delivery / 'video.mp4')
        captions = digest(self.delivery / 'captions.vtt')
        voice = dict(status='GENERATED_PENDING_LISTENING_REVIEW',
                     clips=[{'scene_id': scene['id'],
                             'speaker': scene.get('speaker', 'narrator'),
                             'voice_id': VOICE_ASSIGNMENTS[scene.get('speaker', 'narrator')]}
                            for scene in editorial['scenes']],
                     voice_assignments=VOICE_ASSIGNMENTS, publication_enabled=False,
                     production_approved=False, full_av_review=False)
        write(self.render / 'voice.json', voice)
        rendered = dict(self.flags, technical_status='PASS', candidate_sha256=self.candidate,
                        caption_sha256=captions, editorial_sha256=editorial_digest(editorial),
                        duration_seconds=10.0, voice_receipt_sha256=digest(self.render / 'voice.json'))
        write(self.delivery / 'render.json', rendered)
        for name in ('video.mp4', 'captions.vtt', 'render.json'):
            (self.render / name).write_bytes((self.delivery / name).read_bytes())
        (self.delivery / 'index.html').write_text('fixture')
        for index in range(1, 4):
            (self.delivery / f'thumbnail-{index}.png').write_bytes(b'SYNTHETIC_IMAGE')
        package = dict(self.flags, status='AWAITING_REVIEW', technical_status='PASS',
                       candidate_sha256=self.candidate, caption_sha256=captions,
                       editorial_sha256=editorial_digest(editorial),
                       render_receipt_sha256=digest(self.delivery / 'render.json'),
                       files_sha256={p.name: digest(p) for p in self.delivery.iterdir()})
        write(self.delivery / 'package.json', package)
        with zipfile.ZipFile(self.delivery / 'review-package.zip', 'x') as archive:
            for path in self.delivery.iterdir():
                if path.suffix != '.zip': archive.write(path, path.name)
        cycle = dict(self.flags, status='AWAITING_REVIEW', technical_status='PASS',
                     finished_at='2026-01-03T00:00:00+00:00', candidate_sha256=self.candidate,
                     package_sha256=digest(self.delivery / 'package.json'),
                     editorial_sha256=digest(self.root / 'editorial.json'),
                     brief_sha256=digest(self.root / 'brief.json'))
        write(self.root / 'cycle.json', cycle)
        comparison = comparison_packet()
        comparison['candidate_sha256'] = self.candidate
        comparison['reviewed_at'] = '2026-01-04T03:00:00Z'
        expected_format = 'landscape' if editorial.get('layout') == 'landscape' else 'portrait'
        for index, reference in enumerate(comparison['references']):
            reference['topic'] = editorial['topic']
            reference['format'] = expected_format
            reference['selected_at'] = f'2026-01-04T0{index}:00:00Z'
            reference['observed_at'] = f'2026-01-04T0{index + 1}:00:00Z'
        self.comparison_source = self.base / 'comparison-source.json'
        self.comparison_receipt = self.base / 'comparison-receipt.json'
        write(self.comparison_source, comparison)
        record_live_comparison(self.root, self.comparison_source,
                               self.comparison_receipt)
        self.submitted = self.base / 'submitted.json'
        self.recorded = self.base / 'recorded.json'
        self.review = {'candidate_sha256': self.candidate, 'reviewer': 'Fixture reviewer',
                       'reviewed_at': '2026-01-04T04:00:00Z',
                       'checks': {name: {'passed': True, 'evidence': 'Synthetic fixture statement for ' + name}
                                  for name in CHECKS},
                       'watcher_review': {
                           'schema_version': 1, 'candidate_sha256': self.candidate,
                           'caption_sha256': captions, 'watcher': 'Fixture direct watcher',
                           'watched_at': '2026-01-04T00:00:00Z',
                           'basis': 'direct_full_audiovisual_watch_and_listen',
                           'coverage': [{'start_seconds': 0.0, 'end_seconds': 10.0}],
                           'checks': {name: {'passed': True,
                                            'evidence': 'Direct fixture audiovisual statement for ' + name}
                                      for name in WATCHER_CHECKS}},
                       'listener_review': {
                           'schema_version': 1, 'candidate_sha256': self.candidate,
                           'listener': 'Fixture direct listener', 'listened_at': '2026-01-04T00:00:00Z',
                           'basis': 'direct_full_mix_listening',
                           'coverage': [{'start_seconds': 0.0, 'end_seconds': 10.0}],
                           'checks': {name: {'passed': True,
                                            'evidence': 'Direct fixture listening statement for ' + name}
                                      for name in LISTENER_CHECKS}}}
        write(self.submitted, self.review)

    def tearDown(self):
        self.temp.cleanup()

    def record(self, output=None, **kwargs):
        return record_review(
            self.root, self.submitted, output or self.recorded,
            live_comparison_source=self.comparison_source,
            live_comparison_receipt=self.comparison_receipt, **kwargs)

    def test_all_checks_record_statement_without_promoting_approval(self):
        before = inspect_cycle(self.root)
        result = self.record()
        self.assertEqual(result['status'], 'EDITORIAL_REVIEW_RECORDED')
        self.assertFalse(result['independent_verification'])
        self.assertFalse(result['production_approved'])
        self.assertFalse(result['full_av_review'])
        self.assertFalse(result['publication_enabled'])
        watcher = result['watcher_review']
        self.assertTrue(watcher['watcher_attestation_recorded'])
        self.assertFalse(watcher['independent_full_audiovisual_verification'])
        self.assertEqual(watcher['candidate_sha256'], self.candidate)
        self.assertEqual(set(watcher['checks']), set(WATCHER_CHECKS))
        listener = result['listener_review']
        self.assertTrue(listener['listener_attestation_recorded'])
        self.assertFalse(listener['independent_listening_verification'])
        self.assertEqual(listener['candidate_sha256'], self.candidate)
        self.assertEqual(set(listener['checks']), set(LISTENER_CHECKS))
        self.assertEqual(result['live_comparison_receipt'],
                         json.loads(self.comparison_receipt.read_text()))
        self.assertEqual(inspect_cycle(self.root), before)

    def test_reference_comparison_requires_replayable_exact_receipt(self):
        with self.assertRaisesRegex(ValueError, 'source and receipt required'):
            record_review(self.root, self.submitted, self.recorded)

        changed = json.loads(self.comparison_receipt.read_text())
        changed['references'][0][
            'candidate_differences']['audio'] = (
                'Changed comparator evidence must not inherit the retained receipt identity.')
        changed_receipt = self.base / 'changed-comparison-receipt.json'
        write(changed_receipt, changed)
        with self.assertRaisesRegex(ValueError, 'identity, evidence or scope changed'):
            record_review(
                self.root, self.submitted, self.recorded,
                live_comparison_source=self.comparison_source,
                live_comparison_receipt=changed_receipt)

        forged = json.loads(self.comparison_receipt.read_text())
        forged['submitted_observations_sha256'] = '0' * 64
        forged_receipt = self.base / 'forged-source-hash-receipt.json'
        write(forged_receipt, forged)
        with self.assertRaisesRegex(ValueError, 'observations changed'):
            record_review(
                self.root, self.submitted, self.recorded,
                live_comparison_source=self.comparison_source,
                live_comparison_receipt=forged_receipt)

        predates = copy.deepcopy(self.review)
        predates['reviewed_at'] = '2026-01-04T02:30:00Z'
        write(self.submitted, predates)
        with self.assertRaisesRegex(ValueError, 'predates the live comparison'):
            self.record()

    def test_revision_replays_comparison_and_retains_its_identities(self):
        recorded = self.record()
        updated = brief()
        updated['scenes'][1]['narration'] = 'My wallet requests an urgent meeting.'
        output = self.base / 'comparison-revision'
        revision = revision_brief(self.root, self.recorded, updated, output)
        self.assertEqual(revision['live_comparison_observations_sha256'],
                         recorded['live_comparison_receipt'][
                             'submitted_observations_sha256'])
        self.assertRegex(revision['live_comparison_receipt_sha256'], r'^[a-f0-9]{64}$')

        changed = json.loads(self.recorded.read_text())
        changed['live_comparison_receipt']['normalized_observations_sha256'] = '0' * 64
        write(self.recorded, changed)
        with self.assertRaisesRegex(ValueError, 'identity, evidence or scope changed'):
            revision_brief(self.root, self.recorded, updated,
                           self.base / 'bad-comparison-revision')

    def test_full_av_requires_direct_complete_granular_watching_and_listening(self):
        cases = []
        missing = copy.deepcopy(self.review); del missing['watcher_review']; cases.append(missing)
        sampled = copy.deepcopy(self.review); sampled['watcher_review']['basis'] = 'sampled_frames'; cases.append(sampled)
        wrong = copy.deepcopy(self.review); wrong['watcher_review']['candidate_sha256'] = '0' * 64; cases.append(wrong)
        captions = copy.deepcopy(self.review); captions['watcher_review']['caption_sha256'] = '0' * 64; cases.append(captions)
        gap = copy.deepcopy(self.review); gap['watcher_review']['coverage'] = [
            {'start_seconds': 0.0, 'end_seconds': 4.0},
            {'start_seconds': 5.0, 'end_seconds': 10.0}]; cases.append(gap)
        incomplete = copy.deepcopy(self.review)
        del incomplete['watcher_review']['checks']['audio_visual_sync']; cases.append(incomplete)
        for index, review in enumerate(cases):
            with self.subTest(index=index):
                write(self.submitted, review)
                with self.assertRaises(ValueError):
                    self.record()
                self.assertFalse(self.recorded.exists())

    def test_full_av_summary_must_match_all_granular_watcher_judgments(self):
        self.review['watcher_review']['checks']['audio_visual_sync'] = {
            'passed': False, 'evidence': 'Narration visibly leads the scene change at second 6.',
            'feedback': 'Align the scene change to the spoken transition at second 6.'}
        write(self.submitted, self.review)
        with self.assertRaisesRegex(ValueError, 'audiovisual summary disagrees'):
            self.record()

    def test_voice_check_requires_direct_complete_granular_listening(self):
        cases = []
        missing = copy.deepcopy(self.review); del missing['listener_review']; cases.append(missing)
        asr = copy.deepcopy(self.review); asr['listener_review']['basis'] = 'asr_transcript'; cases.append(asr)
        wrong = copy.deepcopy(self.review); wrong['listener_review']['candidate_sha256'] = '0' * 64; cases.append(wrong)
        gap = copy.deepcopy(self.review); gap['listener_review']['coverage'] = [
            {'start_seconds': 0.0, 'end_seconds': 4.0},
            {'start_seconds': 5.0, 'end_seconds': 10.0}]; cases.append(gap)
        incomplete = copy.deepcopy(self.review)
        del incomplete['listener_review']['checks']['pronunciation']; cases.append(incomplete)
        for index, review in enumerate(cases):
            with self.subTest(index=index):
                write(self.submitted, review)
                with self.assertRaises(ValueError):
                    self.record()
                self.assertFalse(self.recorded.exists())

    def test_listener_summary_must_match_all_granular_judgments(self):
        self.review['listener_review']['checks']['mix_balance'] = {
            'passed': False, 'evidence': 'Music masks narration from seconds 6 to 8.',
            'feedback': 'Reduce music beneath the narration in that interval.'}
        write(self.submitted, self.review)
        with self.assertRaisesRegex(ValueError, 'summary disagrees'):
            self.record()

    def test_listener_rejects_reassigned_or_changed_voice_receipt(self):
        voice_path = self.render / 'voice.json'
        voice = json.loads(voice_path.read_text())
        voice['clips'][0]['voice_id'] = 'am_changed'
        write(voice_path, voice)
        rendered = json.loads((self.delivery / 'render.json').read_text())
        rendered['voice_receipt_sha256'] = digest(voice_path)
        write(self.delivery / 'render.json', rendered)
        (self.render / 'render.json').write_bytes((self.delivery / 'render.json').read_bytes())
        package = json.loads((self.delivery / 'package.json').read_text())
        package['files_sha256']['render.json'] = digest(self.delivery / 'render.json')
        package['render_receipt_sha256'] = digest(self.delivery / 'render.json')
        write(self.delivery / 'package.json', package)
        with zipfile.ZipFile(self.delivery / 'review-package.zip', 'w') as archive:
            for path in self.delivery.iterdir():
                if path.suffix != '.zip': archive.write(path, path.name)
        cycle = json.loads((self.root / 'cycle.json').read_text())
        cycle['package_sha256'] = digest(self.delivery / 'package.json')
        write(self.root / 'cycle.json', cycle)
        with self.assertRaisesRegex(ValueError, 'voice assignment changed'):
            self.record()

    def test_concurrent_voice_change_blocks_final_review_record(self):
        from integrations.content_control import cycle_review as module
        original = module._listener_attestation

        def change_after_check(*args, **kwargs):
            result = original(*args, **kwargs)
            voice_path = self.render / 'voice.json'
            voice = json.loads(voice_path.read_text())
            voice['clips'][0]['voice_id'] = 'am_changed_after_check'
            write(voice_path, voice)
            return result

        with patch('integrations.content_control.cycle_review._listener_attestation',
                   side_effect=change_after_check), self.assertRaises(ValueError):
            self.record()
        self.assertFalse(self.recorded.exists())

    def test_revision_revalidates_recorded_listener_and_current_voice_identity(self):
        self.record()
        updated = brief(); updated['scenes'][1]['narration'] = 'My wallet requests an urgent meeting.'

        changed_review = json.loads(self.recorded.read_text())
        changed_review['listener_review']['voice_receipt_sha256'] = '0' * 64
        write(self.recorded, changed_review)
        with self.assertRaisesRegex(ValueError, 'listener review identity'):
            revision_brief(self.root, self.recorded, updated, self.base / 'bad-listener')

        self.recorded.unlink()
        self.record()
        voice_path = self.render / 'voice.json'
        voice = json.loads(voice_path.read_text())
        voice['clips'][0]['voice_id'] = 'am_changed_after_review'
        write(voice_path, voice)
        with self.assertRaisesRegex(ValueError, 'voice receipt identity'):
            revision_brief(self.root, self.recorded, updated, self.base / 'bad-voice')

    def test_revision_revalidates_recorded_watcher_identity(self):
        self.record()
        updated = brief(); updated['scenes'][1]['narration'] = 'My wallet requests an urgent meeting.'
        changed_review = json.loads(self.recorded.read_text())
        changed_review['watcher_review']['caption_sha256'] = '0' * 64
        write(self.recorded, changed_review)
        with self.assertRaisesRegex(ValueError, 'different captions'):
            revision_brief(self.root, self.recorded, updated, self.base / 'bad-watcher')

    def test_incomplete_and_failed_checks_produce_actionable_revision(self):
        del self.review['checks']['originality']
        self.review['checks']['voice_naturalness'] = {'passed': False, 'evidence': 'Narration sounds rushed from seconds 3 to 8.',
                                                    'feedback': 'Slow the middle sentence and rerender narration.'}
        self.review['listener_review']['checks']['naturalness'] = {
            'passed': False, 'evidence': 'Narration sounds rushed from seconds 3 to 8.',
            'feedback': 'Slow the middle sentence and rerender narration.'}
        write(self.submitted, self.review)
        result = self.record()
        self.assertEqual(result['status'], 'REVISION_REQUIRED')
        self.assertEqual({item['check'] for item in result['feedback']},
                         {'originality', 'voice_naturalness', 'listener.naturalness'})

    def test_candidate_mismatch_and_predated_review_rejected(self):
        for field, value in [('candidate_sha256', '0' * 64), ('reviewed_at', '2026-01-01T00:00:00Z')]:
            review = copy.deepcopy(self.review); review[field] = value
            write(self.submitted, review)
            with self.assertRaises(ValueError): self.record()
            self.assertFalse(self.recorded.exists())

    def test_current_package_artifacts_are_verified_before_decisions(self):
        (self.delivery / 'thumbnail-1.png').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'artifact changed'): self.record()

    def test_lint_binds_copy_candidate_and_package_without_approving_or_mutating(self):
        before = inspect_cycle(self.root)
        def dispatch(job, upstream):
            path = Path(job['input'])
            copy = json.loads(path.read_text())
            title = before['editorial']['title']
            self.assertEqual(copy, {'title': title, 'thumb': ' '.join(title.split())})
            self.assertIs(job['publication_enabled'], False)
            self.assertIs(job['paid_generation_enabled'], False)
            return {'tool': 'youtube-agent-skill', 'operation': 'package-lint', 'status': 'PASS',
                    'execution_status': 'PASS', 'exit_code': 0,
                    'input_sha256': digest(path), 'findings': [{'title': title, 'score': 40}],
                    'publication_enabled': False, 'paid_generation_enabled': False, 'production_ready': False}
        output = self.base / 'lint.json'
        with patch('integrations.run.source'), patch('integrations.youtube_skill.adapter.dispatch', side_effect=dispatch):
            result = lint_package(self.root, output)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                lint_package(self.root, output)
        self.assertEqual(result, json.loads(output.read_text()))
        self.assertEqual(result['status'], 'DIAGNOSTIC_COMPLETE')
        self.assertEqual(result['candidate_sha256'], self.candidate)
        self.assertEqual(result['package_sha256'], digest(self.delivery / 'package.json'))
        for name in (*self.flags, 'thumbnail_selection_verified', 'thumbnail_performance_verified'):
            self.assertIs(result[name], False)
        self.assertEqual(inspect_cycle(self.root), before)

    def test_lint_rejects_package_changed_during_tool_execution(self):
        def dispatch(job, upstream):
            (self.delivery / 'thumbnail-1.png').write_bytes(b'changed')
            return {'tool': 'youtube-agent-skill', 'operation': 'package-lint', 'status': 'BLOCKED',
                    'execution_status': 'BLOCKED',
                    'input_sha256': digest(Path(job['input'])), 'publication_enabled': False,
                    'paid_generation_enabled': False, 'production_ready': False}
        output = self.base / 'lint.json'
        with patch('integrations.run.source'), patch('integrations.youtube_skill.adapter.dispatch', side_effect=dispatch):
            with self.assertRaisesRegex(ValueError, 'Package artifact changed'):
                lint_package(self.root, output)
        self.assertFalse(output.exists())

    def test_original_render_tamper_is_rejected(self):
        (self.render / 'video.mp4').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'Original render'): inspect_cycle(self.root)

    def test_thumbnail_copy_cannot_be_added_to_legacy_package_receipt(self):
        package = self.delivery / 'package.json'
        receipt = json.loads(package.read_text())
        receipt['thumbnail_copy'] = 'Unauthored overlay'
        write(package, receipt)
        cycle = json.loads((self.root / 'cycle.json').read_text())
        cycle['package_sha256'] = digest(package)
        write(self.root / 'cycle.json', cycle)
        # Rebind generic receipts deliberately: the semantic copy check should
        # still enforce the compiled brief's absence of an override.
        with zipfile.ZipFile(self.delivery / 'review-package.zip', 'w') as archive:
            for path in self.delivery.iterdir():
                if path.suffix != '.zip':
                    archive.write(path, path.name)
        with self.assertRaisesRegex(ValueError, 'Thumbnail copy differs'):
            inspect_cycle(self.root)

    def test_archive_tamper_is_rejected(self):
        with zipfile.ZipFile(self.delivery / 'review-package.zip', 'a') as archive:
            archive.writestr('extra.txt', 'unexpected')
        with self.assertRaisesRegex(ValueError, 'Archive members'): inspect_cycle(self.root)

    def test_record_cannot_overwrite_or_mutate_cycle(self):
        self.record()
        original = self.recorded.read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'): self.record()
        self.assertEqual(original, self.recorded.read_bytes())
        with self.assertRaisesRegex(ValueError, 'separate'):
            self.record(self.root / 'review.json')
        with self.assertRaisesRegex(ValueError, 'separate'):
            self.record(self.base / 'elsewhere' / '..' / 'cycle' / 'review.json')

    def test_revision_preserves_provenance_and_remains_runnable_input(self):
        self.record()
        updated = brief(); updated['scenes'][1]['narration'] = 'My wallet requests an urgent meeting.'
        output = self.base / 'revision'
        result = revision_brief(self.root, self.recorded, updated, output)
        self.assertEqual(result['status'], 'REVISION_BRIEF_READY')
        self.assertEqual(result['supersedes_candidate_sha256'], self.candidate)
        compiled = compile_editorial(json.loads((output / 'brief.json').read_text()))
        self.assertEqual(compiled['sources'], compile_editorial(brief())['sources'])
        self.assertFalse(result['feedback_resolution_verified'])

    def test_unchanged_revision_or_rewritten_source_provenance_rejected(self):
        self.record()
        with self.assertRaisesRegex(ValueError, 'must change'):
            revision_brief(self.root, self.recorded, brief(), self.base / 'same')
        updated = brief(); updated['sources'][0]['excerpt'] = 'Rewritten source history.'
        with self.assertRaisesRegex(ValueError, 'provenance'):
            revision_brief(self.root, self.recorded, updated, self.base / 'bad')

    def test_revision_cannot_relabel_idea_learning_provenance(self):
        parent = brief()
        parent['idea_learning'] = {
            **dict.fromkeys(LEARNING_IDENTITIES, 'a' * 64),
            'hypothesis_index': 1, 'hypothesis': 'Keep both comparison amounts visible.',
            'application': 'Place the two amounts together on the opening card.',
            'prior_performance_status': 'UNAVAILABLE', 'audience_performance_verified': False,
        }
        snapshot = inspect_cycle(self.root)
        snapshot['editorial'] = compile_editorial(parent)
        updated = copy.deepcopy(parent)
        updated['scenes'][1]['narration'] = 'My wallet requests an urgent meeting.'
        with patch('integrations.content_control.cycle_review.inspect_cycle', return_value=snapshot):
            self.record()
            revision_brief(self.root, self.recorded, updated, self.base / 'valid')
            del updated['idea_learning']
            with self.assertRaisesRegex(ValueError, 'idea learning provenance'):
                revision_brief(self.root, self.recorded, updated, self.base / 'bad')

    def test_review_from_other_cycle_cannot_certify_revision(self):
        self.record()
        review = json.loads(self.recorded.read_text()); review['source_files_sha256']['cycle.json'] = '0' * 64
        write(self.recorded, review)
        with self.assertRaisesRegex(ValueError, 'bind current cycle'):
            revision_brief(self.root, self.recorded, brief(), self.base / 'bad')


if __name__ == '__main__': unittest.main()
