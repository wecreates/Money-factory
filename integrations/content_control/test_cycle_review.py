"""Small synthetic packets exercise identity/attestation rules, not real media QA."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from integrations.content_control.cycle_editorial import compile_editorial
from integrations.content_control.cycle_package import editorial_digest
from integrations.content_control.cycle_review import CHECKS, inspect_cycle, lint_package, record_review, revision_brief
from integrations.content_control.review_package import digest
from integrations.content_control.test_cycle_editorial import brief


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
        rendered = dict(self.flags, technical_status='PASS', candidate_sha256=self.candidate,
                        caption_sha256=captions, editorial_sha256=editorial_digest(editorial))
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
        self.submitted = self.base / 'submitted.json'
        self.recorded = self.base / 'recorded.json'
        self.review = {'candidate_sha256': self.candidate, 'reviewer': 'Fixture reviewer',
                       'reviewed_at': '2026-01-04T00:00:00Z',
                       'checks': {name: {'passed': True, 'evidence': 'Synthetic fixture statement for ' + name}
                                  for name in CHECKS}}
        write(self.submitted, self.review)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_checks_record_statement_without_promoting_approval(self):
        before = inspect_cycle(self.root)
        result = record_review(self.root, self.submitted, self.recorded)
        self.assertEqual(result['status'], 'EDITORIAL_REVIEW_RECORDED')
        self.assertFalse(result['independent_verification'])
        self.assertFalse(result['production_approved'])
        self.assertFalse(result['full_av_review'])
        self.assertFalse(result['publication_enabled'])
        self.assertEqual(inspect_cycle(self.root), before)

    def test_incomplete_and_failed_checks_produce_actionable_revision(self):
        del self.review['checks']['originality']
        self.review['checks']['voice_naturalness'] = {'passed': False, 'evidence': 'Narration sounds rushed from seconds 3 to 8.',
                                                    'feedback': 'Slow the middle sentence and rerender narration.'}
        write(self.submitted, self.review)
        result = record_review(self.root, self.submitted, self.recorded)
        self.assertEqual(result['status'], 'REVISION_REQUIRED')
        self.assertEqual({item['check'] for item in result['feedback']}, {'originality', 'voice_naturalness'})

    def test_candidate_mismatch_and_predated_review_rejected(self):
        for field, value in [('candidate_sha256', '0' * 64), ('reviewed_at', '2026-01-01T00:00:00Z')]:
            review = copy.deepcopy(self.review); review[field] = value
            write(self.submitted, review)
            with self.assertRaises(ValueError): record_review(self.root, self.submitted, self.recorded)
            self.assertFalse(self.recorded.exists())

    def test_current_package_artifacts_are_verified_before_decisions(self):
        (self.delivery / 'thumbnail-1.png').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'artifact changed'): record_review(self.root, self.submitted, self.recorded)

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
        record_review(self.root, self.submitted, self.recorded)
        original = self.recorded.read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'): record_review(self.root, self.submitted, self.recorded)
        self.assertEqual(original, self.recorded.read_bytes())
        with self.assertRaisesRegex(ValueError, 'separate'): record_review(self.root, self.submitted, self.root / 'review.json')
        with self.assertRaisesRegex(ValueError, 'separate'):
            record_review(self.root, self.submitted, self.base / 'elsewhere' / '..' / 'cycle' / 'review.json')

    def test_revision_preserves_provenance_and_remains_runnable_input(self):
        record_review(self.root, self.submitted, self.recorded)
        updated = brief(); updated['scenes'][1]['narration'] = 'My wallet requests an urgent meeting.'
        output = self.base / 'revision'
        result = revision_brief(self.root, self.recorded, updated, output)
        self.assertEqual(result['status'], 'REVISION_BRIEF_READY')
        self.assertEqual(result['supersedes_candidate_sha256'], self.candidate)
        compiled = compile_editorial(json.loads((output / 'brief.json').read_text()))
        self.assertEqual(compiled['sources'], compile_editorial(brief())['sources'])
        self.assertFalse(result['feedback_resolution_verified'])

    def test_unchanged_revision_or_rewritten_source_provenance_rejected(self):
        record_review(self.root, self.submitted, self.recorded)
        with self.assertRaisesRegex(ValueError, 'must change'):
            revision_brief(self.root, self.recorded, brief(), self.base / 'same')
        updated = brief(); updated['sources'][0]['excerpt'] = 'Rewritten source history.'
        with self.assertRaisesRegex(ValueError, 'provenance'):
            revision_brief(self.root, self.recorded, updated, self.base / 'bad')

    def test_review_from_other_cycle_cannot_certify_revision(self):
        record_review(self.root, self.submitted, self.recorded)
        review = json.loads(self.recorded.read_text()); review['source_files_sha256']['cycle.json'] = '0' * 64
        write(self.recorded, review)
        with self.assertRaisesRegex(ValueError, 'bind current cycle'):
            revision_brief(self.root, self.recorded, brief(), self.base / 'bad')


if __name__ == '__main__': unittest.main()
