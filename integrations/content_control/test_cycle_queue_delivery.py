"""Synthetic queue and package fixtures cover durable fresh-cycle delivery."""
import hashlib
import json
import shutil
import unittest
from zipfile import BadZipFile, ZipFile

from integrations.content_control import test_cycle_review as fixtures
from integrations.content_control.cycle_job import brief_digest, production_handoff
from integrations.content_control.test_cycle_job import intake_request, synthetic_picture_mp4
from integrations.content_control.review_delivery import export_review, status, verify_exported_cycle
from integrations.content_control.review_package import digest
from integrations.local_agent_queue import Queue, canonical


class CycleDeliveryTests(unittest.TestCase):
    setUp = fixtures.ReviewTests.setUp
    tearDown = fixtures.ReviewTests.tearDown

    def queue_review(self, minimum=None, picture_seconds=None, media=None, with_intake=False):
        brief = json.loads((self.root / 'brief.json').read_text())
        request = {'operation': 'produce-content-cycle', 'brief': brief, 'brief_sha256': brief_digest(brief),
                   'timeout_seconds': 300, 'publication_enabled': False, 'paid_generation_enabled': False}
        if with_intake:
            request, _ = intake_request(self.base, brief)
        if minimum is not None:
            request['minimum_duration_seconds'] = minimum
        queue = Queue(self.base / 'queue'); self.addCleanup(queue.close)
        queue.enqueue({'id': 'cycle-test', 'adapter': 'content-control-cycle', 'request': request,
                       'max_attempts': 1, 'publication_enabled': False, 'paid_generation_enabled': False})
        with queue.consumer():
            claim = queue.claim()
            attempt = queue.root / 'attempts/cycle-test/1'
            directory = attempt / 'cycle'; shutil.copytree(self.root, directory)
            raw, _, files, proof = production_handoff(request)
            (directory / 'brief.json').write_bytes(raw)
            if proof is not None:
                (attempt / 'brief.json').write_bytes(raw)
                for name, data in files.items():
                    (attempt / name).write_bytes(data)
            delivery = directory / 'delivery'
            if media is not None:
                for target in (delivery, directory / 'render'):
                    shutil.copyfile(media, target / 'video.mp4')
            candidate = digest(delivery / 'video.mp4')
            render = json.loads((delivery / 'render.json').read_text())
            render['candidate_sha256'] = candidate
            if minimum is not None:
                render.update(minimum_duration_seconds=minimum, measured_narration_frame_budget=minimum*24,
                              encoded_picture_duration_seconds=picture_seconds)
            for target in (delivery, directory / 'render'):
                fixtures.write(target / 'render.json', dict(render, status='AWAITING_REVIEW'))
            package = json.loads((delivery / 'package.json').read_text())
            package.update(schema_version=1, production_ready=False, candidate_sha256=candidate,
                           render_receipt_sha256=digest(delivery / 'render.json'))
            package['files_sha256']['render.json'] = package['render_receipt_sha256']
            package['files_sha256']['video.mp4'] = candidate
            fixtures.write(delivery / 'package.json', package)
            with ZipFile(delivery / 'review-package.zip', 'w') as archive:
                for name in (*package['files_sha256'], 'package.json'):
                    archive.write(delivery / name, name)
            cycle_path = directory / 'cycle.json'
            cycle = json.loads(cycle_path.read_text())
            cycle.update(candidate_sha256=candidate, brief_sha256=digest(directory / 'brief.json'),
                         package_sha256=digest(delivery / 'package.json'),
                         archive_sha256=digest(directory / 'delivery/review-package.zip'),
                         production_ready=False, factual_review=False, competitor_comparison=False)
            if minimum is not None:
                cycle['minimum_duration_seconds'] = minimum
            if proof is not None:
                cycle['verified_intake'] = proof
            fixtures.write(cycle_path, cycle)
            receipt = {'status': 'PASS', 'review_status': 'AWAITING_REVIEW', 'operation': request['operation'],
                       'brief_sha256': request['brief_sha256'], 'production_brief_sha256': cycle['brief_sha256'],
                       'candidate_sha256': candidate, 'pipeline_receipt_sha256': digest(cycle_path),
                       'artifact_directory': 'cycle', **self.flags, 'production_ready': False}
            if minimum is not None:
                receipt['minimum_duration_seconds'] = minimum
            if proof is not None:
                receipt['verified_intake'] = proof
            fixtures.write(attempt / 'cycle-adapter-receipt.json', receipt)
            queue.finish(claim, receipt)
        return queue, directory, receipt

    def test_durable_completion_copies_exact_archive_outside_queue(self):
        queue, directory, _ = self.queue_review()
        db = queue.root / 'queue.sqlite3'; before = db.read_bytes()
        report = status(queue.root, 'cycle-test')
        self.assertTrue(report['delivery_ready'], report)
        output = self.base / 'export'
        result = export_review(queue.root, 'cycle-test', output)
        self.assertEqual(result, json.loads((output / 'package.json').read_text()))
        self.assertEqual(result['candidate_sha256'], self.candidate)
        self.assertEqual(result['archive_sha256'], digest(output / 'review-package.zip'))
        self.assertEqual(result['archive_sha256'], digest(directory / 'delivery/review-package.zip'))
        self.assertEqual(result['entrypoint'], 'review/index.html')
        self.assertEqual(result['entrypoint_sha256'], digest(output / result['entrypoint']))
        self.assertEqual(result['candidate_sha256'], digest(output / 'review/video.mp4'))
        self.assertEqual(result['package_sha256'], digest(output / 'review/package.json'))
        self.assertEqual(result['files_sha256']['review/index.html'], result['entrypoint_sha256'])
        self.assertEqual(result['files_sha256']['review/video.mp4'], result['candidate_sha256'])
        self.assertEqual(
            {path.relative_to(output).as_posix() for path in (output / 'review').iterdir()},
            set(result['files_sha256']))
        identity = {
            'job_id': result['provenance']['job_id'], 'job_digest': result['provenance']['job_digest'],
            'attempt': result['provenance']['attempt'], 'candidate_sha256': result['candidate_sha256'],
            'package_sha256': result['package_sha256'], 'archive_sha256': result['archive_sha256'],
            'entrypoint': result['entrypoint'], 'entrypoint_sha256': result['entrypoint_sha256'],
            'files_sha256': result['files_sha256'], 'provenance': result['provenance'],
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_ready': False, 'production_approved': False, 'full_av_review': False,
        }
        self.assertEqual(result['delivery_identity_sha256'],
                         hashlib.sha256(canonical(identity).encode()).hexdigest())
        self.assertFalse(result['production_approved'])
        verified = verify_exported_cycle(output, result['delivery_identity_sha256'])
        self.assertEqual(verified['status'], 'PASS')
        self.assertEqual(verified['delivery_identity_sha256'], result['delivery_identity_sha256'])
        for path in (output, queue.root / 'other'):
            with self.assertRaisesRegex(ValueError, 'outside the queue'):
                export_review(queue.root, 'cycle-test', path)
        self.assertEqual(before, db.read_bytes())

    def test_retained_export_verifier_rejects_tree_archive_and_receipt_changes(self):
        queue, _, _ = self.queue_review()
        output = self.base / 'export'
        result = export_review(queue.root, 'cycle-test', output)
        expected = result['delivery_identity_sha256']
        self.assertEqual(verify_exported_cycle(output, expected)['candidate_sha256'], self.candidate)
        cases = (
            output / 'review/video.mp4',
            output / 'review/index.html',
            output / 'review-package.zip',
            output / 'package.json',
        )
        for path in cases:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                with self.assertRaises(ValueError):
                    verify_exported_cycle(output, expected)
                path.write_bytes(original)
        extra = output / 'review/unbound.txt'
        extra.write_text('unbound')
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            verify_exported_cycle(output, expected)
        extra.unlink()
        receipt = json.loads((output / 'package.json').read_text())
        receipt['delivery_identity_sha256'] = '0' * 64
        fixtures.write(output / 'package.json', receipt)
        with self.assertRaisesRegex(ValueError, 'identity receipt changed'):
            verify_exported_cycle(output, expected)

    def test_retained_verifier_requires_external_identity_and_strict_gate_schema(self):
        queue, _, _ = self.queue_review()
        output = self.base / 'export'
        result = export_review(queue.root, 'cycle-test', output)
        expected = result['delivery_identity_sha256']
        for supplied in (None, '', '0' * 63):
            with self.subTest(supplied=supplied):
                with self.assertRaisesRegex(ValueError, 'Trusted expected'):
                    verify_exported_cycle(output, supplied)
        path = output / 'package.json'
        original = path.read_bytes()
        for field in ('phone_playback_verified', 'listening_verified', 'publishing_enabled'):
            with self.subTest(field=field):
                receipt = json.loads(original)
                receipt[field] = True
                fixtures.write(path, receipt)
                with self.assertRaisesRegex(ValueError, 'schema is invalid'):
                    verify_exported_cycle(output, expected)
        receipt = json.loads(original)
        receipt['scope'] = 'Phone playback accepted'
        fixtures.write(path, receipt)
        with self.assertRaisesRegex(ValueError, 'not an unpublished cycle review'):
            verify_exported_cycle(output, expected)
        path.write_bytes(original)

    def test_forged_cycle_provenance_is_rejected_even_with_matching_supplied_identity(self):
        queue, _, _ = self.queue_review()
        output = self.base / 'export'
        export_review(queue.root, 'cycle-test', output)
        path = output / 'package.json'
        original = path.read_bytes()
        for field, value in (('adapter', 'other-adapter'), ('completed_at_unix', 0)):
            with self.subTest(field=field):
                receipt = json.loads(original)
                receipt['provenance'][field] = value
                identity = {
                    'job_id': receipt['provenance']['job_id'],
                    'job_digest': receipt['provenance']['job_digest'],
                    'attempt': receipt['provenance']['attempt'],
                    'candidate_sha256': receipt['candidate_sha256'],
                    'package_sha256': receipt['package_sha256'],
                    'archive_sha256': receipt['archive_sha256'],
                    'entrypoint': receipt['entrypoint'],
                    'entrypoint_sha256': receipt['entrypoint_sha256'],
                    'files_sha256': receipt['files_sha256'],
                    'provenance': receipt['provenance'],
                    'publication_enabled': False, 'paid_generation_enabled': False,
                    'production_ready': False, 'production_approved': False, 'full_av_review': False,
                }
                receipt['delivery_identity_sha256'] = hashlib.sha256(canonical(identity).encode()).hexdigest()
                fixtures.write(path, receipt)
                with self.assertRaisesRegex(ValueError, 'provenance is invalid'):
                    verify_exported_cycle(output, receipt['delivery_identity_sha256'])
        path.write_bytes(original)

    def test_coherent_self_contained_rewrite_cannot_replace_trusted_identity(self):
        queue, _, _ = self.queue_review()
        output = self.base / 'export'
        result = export_review(queue.root, 'cycle-test', output)
        expected = result['delivery_identity_sha256']
        video = output / 'review/video.mp4'
        video.write_bytes(b'coherently replaced video')
        package_path = output / 'review/package.json'
        package = json.loads(package_path.read_text())
        candidate = digest(video)
        package['candidate_sha256'] = candidate
        package['files_sha256']['video.mp4'] = candidate
        fixtures.write(package_path, package)
        package_sha = digest(package_path)
        archive_path = output / 'review-package.zip'
        with ZipFile(archive_path, 'w') as archive:
            for artifact in sorted((output / 'review').iterdir()):
                archive.write(artifact, artifact.name)
        archive_sha = digest(archive_path)
        receipt_path = output / 'package.json'
        receipt = json.loads(receipt_path.read_text())
        receipt['candidate_sha256'] = candidate
        receipt['package_sha256'] = package_sha
        receipt['archive_sha256'] = archive_sha
        receipt['files_sha256']['review/video.mp4'] = candidate
        receipt['files_sha256']['review/package.json'] = package_sha
        receipt['provenance'].update(candidate_sha256=candidate, package_sha256=package_sha,
                                     review_archive_sha256=archive_sha)
        identity = {
            'job_id': receipt['provenance']['job_id'], 'job_digest': receipt['provenance']['job_digest'],
            'attempt': receipt['provenance']['attempt'], 'candidate_sha256': candidate,
            'package_sha256': package_sha, 'archive_sha256': archive_sha,
            'entrypoint': receipt['entrypoint'], 'entrypoint_sha256': receipt['entrypoint_sha256'],
            'files_sha256': receipt['files_sha256'], 'provenance': receipt['provenance'],
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_ready': False, 'production_approved': False, 'full_av_review': False,
        }
        receipt['delivery_identity_sha256'] = hashlib.sha256(canonical(identity).encode()).hexdigest()
        fixtures.write(receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, 'trusted expected identity'):
            verify_exported_cycle(output, expected)

    def test_retained_export_has_queue_independent_verification_cli(self):
        import subprocess
        import sys
        queue, _, _ = self.queue_review()
        output = self.base / 'export'
        exported = export_review(queue.root, 'cycle-test', output)
        result = subprocess.run([
            sys.executable, '-m', 'integrations.content_control.review_delivery',
            'verify', '--output', str(output),
            '--expected-delivery-identity', exported['delivery_identity_sha256'],
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'PASS')

    def test_minimum_duration_is_rechecked_from_queue_before_export(self):
        queue, _, _ = self.queue_review(minimum=510, picture_seconds=509.99)
        self.assertIn('minimum picture duration', status(queue.root, 'cycle-test')['delivery_error'])
        output = self.base / 'export'
        with self.assertRaisesRegex(ValueError, 'minimum picture duration'):
            export_review(queue.root, 'cycle-test', output)
        self.assertFalse(output.exists())

    def test_verified_intake_is_retained_and_rechecked_before_export(self):
        queue, directory, receipt = self.queue_review(with_intake=True)
        report = status(queue.root, 'cycle-test')
        self.assertTrue(report['delivery_ready'], report)
        proof = receipt['verified_intake']
        self.assertEqual(report['provenance']['verified_intake'], proof)
        exported = export_review(queue.root, 'cycle-test', self.base / 'export-with-intake')
        self.assertEqual(exported['provenance']['verified_intake'], proof)
        intake = directory.parent / 'intake.json'
        intake.write_bytes(intake.read_bytes().replace(b'\r\n', b'\n'))
        report = status(queue.root, 'cycle-test')
        self.assertFalse(report['delivery_ready'])
        self.assertIn('Retained intake differs from queued handoff', report['delivery_error'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Media tools unavailable')
    def test_verified_minimum_duration_is_retained_in_export_provenance(self):
        media = self.base / 'one-second-picture.mp4'
        synthetic_picture_mp4(media, 1)
        queue, _, _ = self.queue_review(minimum=1, picture_seconds=1, media=media)
        output = self.base / 'export'
        result = export_review(queue.root, 'cycle-test', output)
        self.assertEqual(result['candidate_sha256'], digest(media))
        self.assertEqual(result['provenance']['minimum_duration_seconds'], 1)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Media tools unavailable')
    def test_export_rejects_digest_bound_short_picture_with_longer_audio(self):
        media = self.base / 'short-picture.mp4'
        synthetic_picture_mp4(media, 0.5)
        queue, _, _ = self.queue_review(minimum=1, picture_seconds=1, media=media)
        self.assertIn('minimum picture duration', status(queue.root, 'cycle-test')['delivery_error'])
        output = self.base / 'export'
        with self.assertRaisesRegex(ValueError, 'minimum picture duration'):
            export_review(queue.root, 'cycle-test', output)
        self.assertFalse(output.exists())

    def test_non_success_mismatched_disk_receipt_and_corrupt_archive_are_blocked(self):
        queue, directory, receipt = self.queue_review()
        queue.db.execute("UPDATE jobs SET state='interrupted'")
        self.assertFalse(status(queue.root, 'cycle-test')['delivery_ready'])
        queue.db.execute("UPDATE jobs SET state='succeeded'")
        changed = {**receipt, 'production_brief_sha256': '0' * 64}
        path = directory.parent / 'cycle-adapter-receipt.json'
        fixtures.write(path, changed)
        self.assertIn('Adapter receipt differs', status(queue.root, 'cycle-test')['delivery_error'])
        queue.db.execute('UPDATE attempts SET receipt=?', (canonical(changed),))
        self.assertIn('immutable brief', status(queue.root, 'cycle-test')['delivery_error'])
        fixtures.write(path, receipt)
        queue.db.execute('UPDATE attempts SET receipt=?', (canonical(receipt),))
        (directory / 'delivery/review-package.zip').write_bytes(b'corrupt archive')
        self.assertFalse(status(queue.root, 'cycle-test')['delivery_ready'])
        with self.assertRaises(BadZipFile):
            export_review(queue.root, 'cycle-test', self.base / 'unused')
        self.assertFalse((self.base / 'unused').exists())


if __name__ == '__main__':
    unittest.main()
