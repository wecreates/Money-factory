"""Derivative-aware private delivery for exact queue Short bytes."""
import hashlib
import json
import os
import shutil
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from integrations.content_control.cycle_queue_short import consume_short
from integrations.content_control import cycle_queue_short_delivery as delivery
from integrations.content_control.cycle_queue_short_delivery import (
    export_short_delivery, verify_short_delivery,
)
from integrations.content_control import test_cycle_queue_delivery as delivery_fixtures
from integrations.content_control.test_cycle_job import synthetic_picture_mp4
from integrations.content_control.review_package import digest
from integrations.local_agent_queue import canonical


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'Media tools unavailable')
class QueueShortDeliveryTests(unittest.TestCase):
    setUp = delivery_fixtures.CycleDeliveryTests.setUp
    tearDown = delivery_fixtures.CycleDeliveryTests.tearDown
    queue_review = delivery_fixtures.CycleDeliveryTests.queue_review

    def prepare(self, *, with_intake=False):
        media = self.base / 'portrait-parent.mp4'
        synthetic_picture_mp4(media, 2, audio_seconds=2)
        queue, _, _ = self.queue_review(media=media, with_intake=with_intake)
        short = self.base / 'short'
        receipt = consume_short(queue.root, 'cycle-test', short,
                                start=0, end=1, timeout=30)
        self.assertEqual(receipt['status'], 'AWAITING_REVIEW')
        return queue, short, receipt

    def test_verified_intake_uses_safe_queue_binding_projection(self):
        queue, short, _ = self.prepare(with_intake=True)
        output = self.base / 'short-delivery-with-intake'
        report = export_short_delivery(queue.root, 'cycle-test', short, output)
        self.assertFalse((output / 'review/queue-short.json').exists())
        binding = json.loads((output / 'review/queue-binding.json').read_text())
        self.assertEqual(binding['queue_receipt_sha256'],
                         digest(short / 'queue-short.json'))
        proof = json.loads((short / 'queue-short.json').read_text())[
            'source_provenance']['verified_intake']
        self.assertEqual(binding['verified_proofs_sha256']['verified_intake'],
                         hashlib.sha256(canonical(proof).encode()).hexdigest())
        self.assertNotIn('verified_intake', binding['verified_receipt']['source_provenance'])
        self.assertEqual(verify_short_delivery(
            output, report['delivery_identity_sha256'])['status'], 'PASS')

    def test_revision_discovery_unknown_claim_is_digest_only(self):
        media = self.base / 'portrait-parent.mp4'
        synthetic_picture_mp4(media, 2, audio_seconds=2)
        queue, directory, receipt = self.queue_review(media=media)
        proof = {'schema_version': 1, 'status': 'DISCOVERY_VERIFIED',
                 'publication_enabled': False, 'paid_generation_enabled': False,
                 'creative_accepted': True}
        cycle_path = directory / 'cycle.json'
        cycle = json.loads(cycle_path.read_text())
        cycle['verified_revision_discovery'] = proof
        cycle_path.write_text(json.dumps(cycle) + '\n')
        receipt.update(verified_revision_discovery=proof,
                       pipeline_receipt_sha256=digest(cycle_path))
        (directory.parent / 'cycle-adapter-receipt.json').write_text(
            json.dumps(receipt) + '\n')
        queue.db.execute('UPDATE attempts SET receipt=?', (canonical(receipt),))
        queue.db.commit()
        raw = (directory / 'brief.json').read_bytes()
        short = self.base / 'revision-short'
        with patch('integrations.content_control.cycle_job.production_handoff',
                   return_value=(raw, None, {}, proof)), \
                patch('integrations.content_control.cycle_job.verify_attempt_intake'):
            result = consume_short(queue.root, 'cycle-test', short,
                                   start=0, end=1, timeout=30)
            self.assertEqual(result['status'], 'AWAITING_REVIEW')
            output = self.base / 'revision-short-delivery'
            report = export_short_delivery(queue.root, 'cycle-test', short, output)
        binding = json.loads((output / 'review/queue-binding.json').read_text())
        self.assertNotIn('creative_accepted', json.dumps(binding['verified_receipt']))
        self.assertEqual(binding['verified_proofs_sha256']['verified_revision_discovery'],
                         hashlib.sha256(canonical(proof).encode()).hexdigest())
        self.assertEqual(verify_short_delivery(
            output, report['delivery_identity_sha256'])['status'], 'PASS')

    def test_exports_and_reopens_exact_derivative_not_parent(self):
        queue, short, receipt = self.prepare()
        before = (queue.root / 'queue.sqlite3').read_bytes()
        output = self.base / 'short-delivery'
        report = export_short_delivery(queue.root, 'cycle-test', short, output)
        self.assertEqual(report, json.loads((output / 'package.json').read_text()))
        self.assertEqual(report['candidate_sha256'], receipt['candidate_sha256'])
        self.assertNotEqual(report['candidate_sha256'], receipt['parent_candidate_sha256'])
        self.assertEqual(report['candidate_sha256'], digest(output / 'review/video.mp4'))
        self.assertEqual(report['caption_sha256'], digest(output / 'review/captions.vtt'))
        self.assertEqual(report['queue_receipt_sha256'], digest(output / 'review/queue-short.json'))
        self.assertEqual(report['archive_sha256'], digest(output / 'review-package.zip'))
        self.assertFalse(report['publication_enabled'])
        self.assertFalse(report['production_ready'])
        verified = verify_short_delivery(output, report['delivery_identity_sha256'])
        self.assertEqual(verified['status'], 'PASS')
        self.assertEqual(verified['candidate_sha256'], receipt['candidate_sha256'])
        self.assertEqual(before, (queue.root / 'queue.sqlite3').read_bytes())
        with ZipFile(output / 'review-package.zip') as archive:
            self.assertEqual(set(archive.namelist()), set(report['files_sha256']))

    def test_tampering_and_untrusted_identity_fail_closed(self):
        queue, short, _ = self.prepare()
        output = self.base / 'short-delivery'
        report = export_short_delivery(queue.root, 'cycle-test', short, output)
        expected = report['delivery_identity_sha256']
        for supplied in (None, '', '0' * 63, '0' * 64):
            with self.subTest(identity=supplied), self.assertRaises(ValueError):
                verify_short_delivery(output, supplied)
        for path in (output / 'review/video.mp4', output / 'review/queue-short.json',
                     output / 'review/delivery-manifest.json', output / 'review-package.zip'):
            original = path.read_bytes()
            with self.subTest(path=path.name):
                path.write_bytes(original + b'changed')
                with self.assertRaises(ValueError):
                    verify_short_delivery(output, expected)
                path.write_bytes(original)

        package = output / 'package.json'
        original = package.read_bytes()
        changed = json.loads(original)
        changed['full_av_review'] = True
        package.write_text(json.dumps(changed) + '\n')
        with self.assertRaises(ValueError):
            verify_short_delivery(output, expected)
        package.write_bytes(original)

    def test_requires_fresh_delivery_outside_queue_and_source(self):
        queue, short, _ = self.prepare()
        for output in (queue.root / 'delivery', short / 'delivery'):
            with self.subTest(output=output), self.assertRaisesRegex(
                    ValueError, 'outside queue and source'):
                export_short_delivery(queue.root, 'cycle-test', short, output)
        existing = self.base / 'existing'
        existing.mkdir()
        with self.assertRaisesRegex(ValueError, 'Fresh Short delivery'):
            export_short_delivery(queue.root, 'cycle-test', short, existing)

    def test_coherent_unknown_acceptance_claims_are_not_archived(self):
        queue, short, _ = self.prepare()
        short_path, queue_path = short / 'short.json', short / 'queue-short.json'
        original_short, original_queue = short_path.read_bytes(), queue_path.read_bytes()
        for index, (field, value) in enumerate((
                ('phone_playback_verified', True), ('creative_accepted', True),
                ('signed_off', True), ('creative_status', 'APPROVED'))):
            with self.subTest(field=field):
                short_path.write_bytes(original_short)
                queue_path.write_bytes(original_queue)
                short_receipt = json.loads(original_short)
                short_receipt[field] = value
                short_path.write_text(json.dumps(short_receipt) + '\n')
                queue_receipt = json.loads(original_queue)
                queue_receipt[field] = value
                queue_receipt['artifacts_sha256']['short.json'] = digest(short_path)
                queue_path.write_text(json.dumps(queue_receipt) + '\n')
                with self.assertRaisesRegex(ValueError, 'schema is invalid'):
                    export_short_delivery(
                        queue.root, 'cycle-test', short,
                        self.base / f'must-not-export-{index}')

    def rebind_artifact(self, short, name, receipt_field):
        identity = digest(short / name)
        short_path = short / 'short.json'
        short_receipt = json.loads(short_path.read_text())
        short_receipt[receipt_field] = identity
        short_path.write_text(json.dumps(short_receipt) + '\n')
        queue_path = short / 'queue-short.json'
        queue_receipt = json.loads(queue_path.read_text())
        queue_receipt[receipt_field] = identity
        queue_receipt['artifacts_sha256'][name] = identity
        queue_receipt['artifacts_sha256']['short.json'] = digest(short_path)
        queue_path.write_text(json.dumps(queue_receipt) + '\n')

    def rebind_review_and_preview(self, short):
        self.rebind_artifact(short, 'automated-review.json',
                             'automated_review_sha256')
        short_receipt = json.loads((short / 'short.json').read_text())
        (short / 'index.html').write_text(delivery._preview_html(
            short_receipt,
            burned_captions=short_receipt['preview_caption_mode'] == 'burned'))
        self.rebind_artifact(short, 'index.html', 'preview_sha256')

    def test_coherent_scope_objects_misleading_scope_and_status_fail_closed(self):
        queue, short, _ = self.prepare()
        short_path, queue_path = short / 'short.json', short / 'queue-short.json'
        original_short, original_queue = short_path.read_bytes(), queue_path.read_bytes()
        cases = (
            ('short', 'scope', {'creative_accepted': True}),
            ('short', 'scope', 'CREATIVE APPROVED AND SIGNED OFF'),
            ('queue', 'scope', {'creative_status': 'APPROVED'}),
            ('queue', 'scope', 'READY TO PUBLISH'),
            ('short', 'status', 'CREATIVE_ACCEPTED'),
            ('queue', 'status', 'SIGNED_OFF'),
        )
        for index, (target, field, value) in enumerate(cases):
            with self.subTest(target=target, field=field, value=value):
                short_path.write_bytes(original_short)
                queue_path.write_bytes(original_queue)
                short_receipt = json.loads(original_short)
                queue_receipt = json.loads(original_queue)
                if target == 'short':
                    short_receipt[field] = value
                    short_path.write_text(json.dumps(short_receipt) + '\n')
                    queue_receipt['artifacts_sha256']['short.json'] = digest(short_path)
                else:
                    queue_receipt[field] = value
                queue_path.write_text(json.dumps(queue_receipt) + '\n')
                with self.assertRaises(ValueError):
                    export_short_delivery(
                        queue.root, 'cycle-test', short,
                        self.base / f'blocked-scope-status-{index}')

    def test_coherently_rebound_nested_diagnostic_claim_is_rejected(self):
        queue, short, _ = self.prepare()
        path = short / 'automated-review.json'
        report = json.loads(path.read_text())
        report['reviewer']['phone_playback_verified'] = True
        path.write_text(json.dumps(report) + '\n')
        self.rebind_artifact(short, 'automated-review.json',
                             'automated_review_sha256')
        with self.assertRaisesRegex(ValueError, 'schema is invalid'):
            export_short_delivery(
                queue.root, 'cycle-test', short, self.base / 'blocked-diagnostic-claim')

    def test_coherently_rebound_diagnostic_identity_is_rejected(self):
        queue, short, _ = self.prepare()
        path = short / 'automated-review.json'
        report = json.loads(path.read_text())
        report['candidate_sha256'] = '0' * 64
        path.write_text(json.dumps(report) + '\n')
        self.rebind_artifact(short, 'automated-review.json',
                             'automated_review_sha256')
        with self.assertRaisesRegex(ValueError, 'binding is invalid'):
            export_short_delivery(
                queue.root, 'cycle-test', short, self.base / 'blocked-diagnostic-identity')

    def test_coherently_rebound_nested_diagnostic_values_are_rejected(self):
        queue, short, _ = self.prepare()
        diagnostic_path = short / 'automated-review.json'
        short_path, queue_path = short / 'short.json', short / 'queue-short.json'
        original_diagnostic = diagnostic_path.read_bytes()
        original_short, original_queue = short_path.read_bytes(), queue_path.read_bytes()

        def picture_object(report):
            report['reviewer']['picture_checks'][0] = {'creative_accepted': True}

        def unexpected_check(report):
            report['reviewer']['comparison_checks'].append('signed off')

        def interval_object(report):
            report['analysis']['intervals_to_review'] = [{'creative_status': 'APPROVED'}]

        def unexpected_status(report):
            report['analysis']['status'] = 'CREATIVE_ACCEPTED'

        def unexpected_failure(report):
            report['analysis'].update(status='BLOCKED', scan_failure_code='SIGNED_OFF')

        def string_interval(report):
            report['watcher']['black_intervals'] = [['0', '1']]

        def object_interval(report):
            report['listener']['silence_intervals'] = [[0, {'approved': True}]]

        def string_level(report):
            report['listener']['peak_dbfs'] = 'loud enough'

        def comparison_reason_object(report):
            report['competitor_comparison']['reason'] = {'creative_accepted': True}

        def comparison_candidate_mismatch(report):
            report['competitor_comparison']['candidate_sha256'] = '0' * 64

        for index, mutation in enumerate((
                picture_object, unexpected_check, interval_object, unexpected_status,
                unexpected_failure, string_interval, object_interval, string_level,
                comparison_reason_object, comparison_candidate_mismatch)):
            with self.subTest(mutation=mutation.__name__):
                diagnostic_path.write_bytes(original_diagnostic)
                short_path.write_bytes(original_short)
                queue_path.write_bytes(original_queue)
                report = json.loads(original_diagnostic)
                mutation(report)
                diagnostic_path.write_text(json.dumps(report) + '\n')
                self.rebind_artifact(short, 'automated-review.json',
                                     'automated_review_sha256')
                with self.assertRaises(ValueError):
                    export_short_delivery(
                        queue.root, 'cycle-test', short,
                        self.base / f'blocked-nested-diagnostic-{index}')

    def test_complete_comparison_is_cross_bound_to_exact_candidate_signals(self):
        queue, short, _ = self.prepare()
        diagnostic_path = short / 'automated-review.json'
        original_diagnostic = diagnostic_path.read_bytes()
        original_short = (short / 'short.json').read_bytes()
        original_queue = (short / 'queue-short.json').read_bytes()

        report = json.loads(original_diagnostic)
        duration = report['media']['duration_seconds']
        candidate = {
            'duration_seconds': duration,
            'black_fraction': report['watcher']['black_seconds'] / duration,
            'frozen_fraction': report['watcher']['frozen_seconds'] / duration,
            'silence_fraction': report['listener']['silence_seconds'] / duration,
            'peak_dbfs': report['listener']['peak_dbfs'],
            'mean_dbfs': report['listener']['mean_dbfs'],
        }
        reference_files = []
        for index, duration_seconds in enumerate((2, 3), start=1):
            reference = self.base / f'reference-{index}.mp4'
            synthetic_picture_mp4(reference, duration_seconds,
                                  audio_seconds=duration_seconds)
            reference_files.append(reference)
        manifest_rows = []
        rows = []
        for index, reference_file in enumerate(reference_files, start=1):
            reference = delivery.benchmarks._signals(delivery.scan_media(
                reference_file, deadline=time.monotonic() + 30))
            manifest_row = {
                'url': f'https://example.com/videos/reference-{index}',
                'path': reference_file.name,
                'sha256': digest(reference_file),
                'authorized': True,
                'selection_rationale': 'Exact retained portrait benchmark.',
                'selection_evidence_url':
                    f'https://example.com/evidence/reference-{index}',
                'selected_at': report['created_at'],
            }
            manifest_rows.append(manifest_row)
            projected = {
                key: manifest_row[key] for key in (
                    'url', 'sha256', 'selection_rationale',
                    'selection_evidence_url', 'selected_at')
            }
            projected.update({
                'reference_signals': reference,
                'candidate_minus_reference': {
                    key: candidate[key] - reference[key] for key in candidate
                },
            })
            rows.append(projected)
        manifest = self.base / 'benchmarks.json'
        manifest.write_text(json.dumps({
            'schema_version': 1, 'references': manifest_rows,
        }) + '\n')
        report['competitor_comparison'] = {
            'status': 'TECHNICAL_COMPARISON_COMPLETE',
            'candidate_sha256': report['candidate_sha256'],
            'comparisons': rows,
            'reason': None,
            'publication_enabled': False,
            'paid_generation_enabled': False,
            'full_av_review': False,
            'reference_selection_independently_verified': False,
            'scope': ('Technical signal differences only. Creative perception '
                      'and competitor rank are unverified.'),
            'reference_format': 'portrait',
            'manifest_sha256': digest(manifest),
        }
        diagnostic_path.write_text(json.dumps(report) + '\n')
        self.rebind_review_and_preview(short)
        valid_output = self.base / 'valid-comparison'
        with patch.dict(os.environ, {'CYZOR_REVIEW_BENCHMARKS': str(manifest)}):
            valid = export_short_delivery(queue.root, 'cycle-test', short, valid_output)
        self.assertEqual(verify_short_delivery(
            valid_output, valid['delivery_identity_sha256'])['status'], 'PASS')

        def wrong_delta(value):
            value['competitor_comparison']['comparisons'][0][
                'candidate_minus_reference']['duration_seconds'] += 1

        def wrong_orientation(value):
            value['competitor_comparison']['comparisons'][0][
                'reference_signals']['orientation'] = 'landscape'

        def duplicate_reference(value):
            value['competitor_comparison']['comparisons'][1]['sha256'] = (
                value['competitor_comparison']['comparisons'][0]['sha256'])

        def candidate_as_reference(value):
            value['competitor_comparison']['comparisons'][0]['sha256'] = (
                value['candidate_sha256'])

        def insecure_evidence(value):
            value['competitor_comparison']['comparisons'][0][
                'selection_evidence_url'] = 'http://example.com/evidence'

        valid_diagnostic = diagnostic_path.read_bytes()
        valid_short = (short / 'short.json').read_bytes()
        valid_queue = (short / 'queue-short.json').read_bytes()
        for index, mutation in enumerate((
                wrong_delta, wrong_orientation, duplicate_reference,
                candidate_as_reference, insecure_evidence)):
            with self.subTest(mutation=mutation.__name__):
                diagnostic_path.write_bytes(valid_diagnostic)
                (short / 'short.json').write_bytes(valid_short)
                (short / 'queue-short.json').write_bytes(valid_queue)
                changed = json.loads(valid_diagnostic)
                mutation(changed)
                diagnostic_path.write_text(json.dumps(changed) + '\n')
                self.rebind_review_and_preview(short)
                with patch.dict(os.environ, {
                        'CYZOR_REVIEW_BENCHMARKS': str(manifest)}), \
                        self.assertRaises(ValueError):
                    export_short_delivery(queue.root, 'cycle-test', short,
                                          self.base / f'blocked-comparison-{index}')

        diagnostic_path.write_bytes(original_diagnostic)
        (short / 'short.json').write_bytes(original_short)
        (short / 'queue-short.json').write_bytes(original_queue)

    def test_scan_failure_minimal_comparison_remains_honestly_blocked(self):
        queue, short, _ = self.prepare()
        path = short / 'automated-review.json'
        report = json.loads(path.read_text())
        report.pop('media')
        report['watcher'] = {'status': 'BLOCKED'}
        report['listener'] = {'status': 'BLOCKED'}
        report['analysis'] = {
            'status': 'BLOCKED',
            'intervals_to_review': [],
            'scan_failure_code': 'CANDIDATE_SCAN_PROCESS_FAILED',
        }
        report['competitor_comparison'] = {
            'status': 'BLOCKED',
            'reason': 'Candidate signal scan unavailable',
        }
        path.write_text(json.dumps(report) + '\n')
        self.rebind_review_and_preview(short)
        output = self.base / 'scan-failure-delivery'
        result = export_short_delivery(queue.root, 'cycle-test', short, output)
        self.assertEqual(verify_short_delivery(
            output, result['delivery_identity_sha256'])['status'], 'PASS')

    def test_caption_mode_cannot_claim_burned_without_exact_overlay(self):
        queue, short, _ = self.prepare()
        short_path = short / 'short.json'
        queue_path = short / 'queue-short.json'
        short_receipt = json.loads(short_path.read_text())
        queue_receipt = json.loads(queue_path.read_text())
        self.assertNotIn('caption_overlay', short_receipt)
        self.assertEqual(short_receipt['preview_caption_mode'], 'sidecar')
        short_receipt['preview_caption_mode'] = 'burned'
        short_path.write_text(json.dumps(short_receipt) + '\n')
        queue_receipt['artifacts_sha256']['short.json'] = digest(short_path)
        queue_path.write_text(json.dumps(queue_receipt) + '\n')
        with self.assertRaisesRegex(ValueError, 'caption mode'):
            export_short_delivery(
                queue.root, 'cycle-test', short,
                self.base / 'blocked-false-burned-caption')

    def test_caption_overlay_cannot_replace_an_actual_burned_pixel_replay(self):
        queue, short, _ = self.prepare()
        short_path = short / 'short.json'
        queue_path = short / 'queue-short.json'
        short_receipt = json.loads(short_path.read_text())
        overlay = {
            'style': delivery.COMPACT_STYLE,
            'audio_mode': 'stream_copy_from_excerpt',
            'scope': 'Burned rebased sidecar into a private phone-size review derivative.',
        }
        short_receipt['preview_caption_mode'] = 'burned'
        short_receipt['caption_overlay'] = overlay
        short_path.write_text(json.dumps(short_receipt) + '\n')
        (short / 'index.html').write_text(delivery._preview_html(
            short_receipt, burned_captions=True))
        self.rebind_artifact(short, 'index.html', 'preview_sha256')
        queue_receipt = json.loads(queue_path.read_text())
        queue_receipt['caption_overlay'] = overlay
        queue_path.write_text(json.dumps(queue_receipt) + '\n')
        with self.assertRaisesRegex(ValueError, 'deterministic exporter replay'):
            export_short_delivery(
                queue.root, 'cycle-test', short,
                self.base / 'blocked-metadata-only-burn')

    def test_coherently_rebound_preview_must_reconstruct_from_receipts(self):
        queue, short, _ = self.prepare()
        path = short / 'index.html'
        path.write_text(path.read_text() + '<p>coherent but unbound rewrite</p>')
        self.rebind_artifact(short, 'index.html', 'preview_sha256')
        with self.assertRaisesRegex(ValueError, 'does not reconstruct'):
            export_short_delivery(
                queue.root, 'cycle-test', short, self.base / 'blocked-preview')

    def test_symlink_source_child_fails_closed(self):
        queue, short, _ = self.prepare()
        source = short / 'automated-review.json'
        retained = self.base / 'same-review.json'
        retained.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(retained)
        with self.assertRaises(ValueError):
            export_short_delivery(
                queue.root, 'cycle-test', short, self.base / 'blocked-symlink')

    def test_special_copied_child_fails_closed(self):
        queue, short, _ = self.prepare()
        output = self.base / 'short-delivery-special'
        report = export_short_delivery(queue.root, 'cycle-test', short, output)
        video = output / 'review/video.mp4'
        video.unlink()
        os.mkfifo(video)
        with self.assertRaisesRegex(ValueError, 'symlink or special'):
            verify_short_delivery(output, report['delivery_identity_sha256'])

    def test_source_swap_after_descriptor_copy_fails_closed(self):
        queue, short, _ = self.prepare()
        real_copy = delivery._copy_regular
        changed = False

        def swap_after_open(source_path, target, *args, **kwargs):
            nonlocal changed
            value = real_copy(source_path, target, *args, **kwargs)
            if not changed:
                changed = True
                with (short / 'video.mp4').open('ab') as stream:
                    stream.write(b'replaced after descriptor copy')
            return value

        with patch.object(delivery, '_copy_regular', side_effect=swap_after_open), \
                self.assertRaises(ValueError):
            export_short_delivery(
                queue.root, 'cycle-test', short, self.base / 'blocked-source-swap')


if __name__ == '__main__':
    unittest.main()
