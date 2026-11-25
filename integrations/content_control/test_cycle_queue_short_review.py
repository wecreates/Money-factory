"""Durable Short repair review and caption-revision handoff tests."""
from contextlib import nullcontext
from datetime import datetime, timezone
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from integrations.content_control import cycle_queue_short_review as review_module
from integrations.content_control.cycle_queue_short import consume_short
from integrations.content_control.cycle_queue_short import verify_consumed_short
from integrations.content_control.cycle_queue_short_review import (
    prepare_caption_revision,
    record_short_review,
    verify_caption_revision,
    verify_recorded_short_review,
)
from integrations.content_control.review_package import digest
from integrations.content_control.test_cycle_job import synthetic_picture_mp4
from integrations.content_control.test_cycle_queue_delivery import CycleDeliveryTests


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'Media tools unavailable')
class QueueShortReviewTests(unittest.TestCase):
    setUp = CycleDeliveryTests.setUp
    tearDown = CycleDeliveryTests.tearDown
    queue_review = CycleDeliveryTests.queue_review

    def prepare(self, *, caption_safe_area=False):
        captions = ('WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n'
                    'Original caption line\n')
        for target in (self.render, self.delivery):
            (target / 'captions.vtt').write_text(captions)
        render = json.loads((self.delivery / 'render.json').read_text())
        render['caption_sha256'] = digest(self.delivery / 'captions.vtt')
        for target in (self.render, self.delivery):
            (target / 'render.json').write_text(json.dumps(render) + '\n')
        package_path = self.delivery / 'package.json'
        package = json.loads(package_path.read_text())
        package['caption_sha256'] = digest(self.delivery / 'captions.vtt')
        package['render_receipt_sha256'] = digest(self.delivery / 'render.json')
        package['files_sha256']['captions.vtt'] = package['caption_sha256']
        package['files_sha256']['render.json'] = package['render_receipt_sha256']
        package_path.write_text(json.dumps(package) + '\n')
        archive_path = self.delivery / 'review-package.zip'
        archive_path.unlink()
        with ZipFile(archive_path, 'w') as archive:
            for name in (*package['files_sha256'], 'package.json'):
                archive.write(self.delivery / name, name)
        cycle_path = self.root / 'cycle.json'
        cycle = json.loads(cycle_path.read_text())
        cycle['package_sha256'] = digest(package_path)
        cycle_path.write_text(json.dumps(cycle) + '\n')
        media = self.base / 'portrait-parent.mp4'
        if caption_safe_area:
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=black:s=720x1280:r=24:d=2', '-f', 'lavfi', '-i',
                            'anullsrc=r=24000:cl=mono:d=2', '-c:v', 'libx264', '-threads', '1',
                            '-c:a', 'aac', str(media)], check=True, timeout=30)
        else:
            synthetic_picture_mp4(media, 2, audio_seconds=2)
        queue, _, _ = self.queue_review(media=media)
        short = self.base / 'durable-short'
        # Synthetic fixture lacks the production visual specs; the actual
        # renderer layout guard is covered in test_cycle_short.
        layout = patch('integrations.content_control.cycle_short.diagram_thumbnail_crop',
                       return_value=(45, 300, 675, 870)) if caption_safe_area else nullcontext()
        with layout:
            receipt = consume_short(queue.root, 'cycle-test', short,
                                    start=0, end=1, timeout=30,
                                    compact_captions=caption_safe_area,
                                    caption_safe_area=caption_safe_area)
        self.assertEqual(receipt['status'], 'AWAITING_REVIEW')
        return queue, short, receipt

    def review_input(self, short, receipt, *, check='caption_accuracy'):
        short_receipt = json.loads((short / 'short.json').read_text())
        return {
            'candidate_sha256': receipt['candidate_sha256'],
            'caption_sha256': receipt['caption_sha256'],
            'queue_short_sha256': digest(short / 'queue-short.json'),
            'short_receipt_sha256': digest(short / 'short.json'),
            'preview_caption_mode': short_receipt['preview_caption_mode'],
            'reviewer': 'Short repair reviewer',
            'reviewed_at': datetime.now(timezone.utc).isoformat(),
            'basis': 'supplied_repair_findings_not_acceptance',
            'findings': [{
                'check': check,
                'evidence': 'The first sidecar cue contains an explicit wording defect.',
                'action': 'Correct that cue and replay the derivative review.',
            }],
        }

    def record(self, queue, short, receipt, *, check='caption_accuracy'):
        submitted = self.base / ('submitted-' + check + '.json')
        submitted.write_text(json.dumps(
            self.review_input(short, receipt, check=check)) + '\n')
        recorded = self.base / ('recorded-' + check + '.json')
        result = record_short_review(queue.root, 'cycle-test', short,
                                     submitted, recorded)
        return recorded, result

    def revision_input(self, short, receipt, recorded):
        lines = (short / 'captions.vtt').read_text().splitlines()
        timing = next(index for index, line in enumerate(lines) if ' --> ' in line)
        before = lines[timing + 1]
        return {
            'candidate_sha256': receipt['candidate_sha256'],
            'caption_sha256': receipt['caption_sha256'],
            'recorded_review_sha256': digest(recorded),
            'editor': 'Caption repair editor',
            'rationale': 'Apply the recorded cue correction without changing media or voices.',
            'caption_edits': [{
                'cue': 1,
                'line': 1,
                'before': before,
                'after': before + ' corrected',
            }],
        }

    def test_review_and_caption_revision_bind_exact_durable_derivative(self):
        queue, short, receipt = self.prepare()
        recorded, review, output, revision = self.review_and_revise(queue, short, receipt)
        self.assertEqual(review, verify_recorded_short_review(
            queue.root, 'cycle-test', short, recorded))
        self.assertEqual(revision, verify_caption_revision(
            queue.root, 'cycle-test', short, recorded, output))

    def review_and_revise(self, queue, short, receipt):
        recorded, review = self.record(queue, short, receipt)
        self.assertEqual(review['status'], 'REVISION_REQUIRED')
        self.assertFalse(review['human_av_acceptance_recorded'])
        self.assertFalse(review['phone_playback_verified'])

        submitted_revision = self.base / 'revision.json'
        submitted_revision.write_text(json.dumps(
            self.revision_input(short, receipt, recorded)) + '\n')
        output = self.base / 'caption-revision'
        revision = prepare_caption_revision(
            queue.root, 'cycle-test', short, recorded,
            submitted_revision, output)
        self.assertEqual(revision['status'], 'CAPTION_REVISION_HANDOFF_READY')
        self.assertEqual(revision['candidate_sha256'], receipt['candidate_sha256'])
        self.assertTrue(revision['candidate_media_unchanged'])
        self.assertTrue(revision['voice_audio_unchanged'])
        self.assertFalse(revision['listening_verified'])
        self.assertNotEqual(revision['revised_caption_sha256'],
                            receipt['caption_sha256'])
        return recorded, review, output, revision

    def test_retained_pre_upgrade_short_review_and_revision_replay(self):
        prior_consumer = '7d1273737a50aff80b49494df857e3866a2c40bc4fa7e5f1a6c6c4691374f592'
        prior_exporter = 'd2c21d9f9e1cefc2b9f153697372e9e30c6fea086e445e32274b172e2a0bc436'

        def historical_digest(module_name, identity):
            def calculate(path, *args, **kwargs):
                if path.name == module_name:
                    return identity
                return digest(path, *args, **kwargs)
            return calculate

        # Only the module self-identities are simulated. Queue verification,
        # encoding, receipt construction and both repair stages still run.
        with patch('integrations.content_control.cycle_queue_short.digest',
                   side_effect=historical_digest('cycle_queue_short.py', prior_consumer)), \
             patch('integrations.content_control.cycle_short.digest',
                   side_effect=historical_digest('cycle_short.py', prior_exporter)):
            queue, short, receipt = self.prepare()
            recorded, review, output, revision = self.review_and_revise(
                queue, short, receipt)
        self.assertEqual(receipt['consumer_tool_sha256'], prior_consumer)
        self.assertEqual(receipt['exporter_tool_sha256'], prior_exporter)
        self.assertEqual(receipt, verify_consumed_short(queue.root, 'cycle-test', short))
        self.assertEqual(review, verify_recorded_short_review(
            queue.root, 'cycle-test', short, recorded))
        self.assertEqual(revision, verify_caption_revision(
            queue.root, 'cycle-test', short, recorded, output))

    def test_pre_safe_area_sidecar_repair_and_revision_receipts_replay(self):
        queue, short, receipt = self.prepare()
        prior = review_module.PRE_SAFE_AREA_REVIEW_TOOL_SHA256

        def historical_digest(path, *args, **kwargs):
            return prior if path.name == 'cycle_queue_short_review.py' else digest(path, *args, **kwargs)

        # The historical tool emitted this exact shape for sidecar Shorts.
        with patch.object(review_module, 'digest', side_effect=historical_digest):
            recorded, review, output, revision = self.review_and_revise(queue, short, receipt)
        self.assertEqual(review['tool_sha256'], prior)
        self.assertEqual(revision['tool_sha256'], prior)
        self.assertEqual(review, verify_recorded_short_review(queue.root, 'cycle-test', short, recorded))
        self.assertEqual(revision, verify_caption_revision(queue.root, 'cycle-test', short, recorded, output))

    def test_review_or_handoff_tampering_fails_replay(self):
        queue, short, receipt = self.prepare()
        recorded, review = self.record(queue, short, receipt)
        changed = dict(review, full_av_review=True)
        recorded.write_text(json.dumps(changed) + '\n')
        with self.assertRaisesRegex(ValueError, 'scope or flags'):
            verify_recorded_short_review(
                queue.root, 'cycle-test', short, recorded)

        # Restore an independently regenerated valid record before revision.
        recorded.unlink()
        submitted = self.base / 'restored-submission.json'
        submitted.write_text(json.dumps(self.review_input(short, receipt)) + '\n')
        record_short_review(queue.root, 'cycle-test', short, submitted, recorded)
        revision_input = self.base / 'revision.json'
        revision_input.write_text(json.dumps(
            self.revision_input(short, receipt, recorded)) + '\n')
        output = self.base / 'caption-revision'
        prepare_caption_revision(queue.root, 'cycle-test', short, recorded,
                                 revision_input, output)
        (output / 'captions.vtt').write_bytes(
            (output / 'captions.vtt').read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'content or identity changed'):
            verify_caption_revision(
                queue.root, 'cycle-test', short, recorded, output)

    def test_caption_revision_requires_a_bound_caption_finding(self):
        queue, short, receipt = self.prepare()
        recorded, _ = self.record(queue, short, receipt, check='pacing')
        revision_input = self.base / 'revision.json'
        revision_input.write_text(json.dumps(
            self.revision_input(short, receipt, recorded)) + '\n')
        with self.assertRaisesRegex(ValueError, 'caption finding required'):
            prepare_caption_revision(
                queue.root, 'cycle-test', short, recorded,
                revision_input, self.base / 'caption-revision')

    def test_review_pins_caption_mode_and_both_short_receipts(self):
        queue, short, receipt = self.prepare()
        submitted = self.base / 'submitted-before-rewrite.json'
        submitted.write_text(json.dumps(self.review_input(short, receipt)) + '\n')

        short_path = short / 'short.json'
        rewritten = json.loads(short_path.read_text())
        rewritten['preview_caption_mode'] = 'burned'
        rewritten['caption_overlay'] = {
            'style': review_module.COMPACT_STYLE,
            'audio_mode': 'stream_copy_from_excerpt',
            'scope': 'Burned rebased sidecar into a private phone-size review derivative.',
        }
        short_path.write_text(json.dumps(rewritten) + '\n')
        queue_path = short / 'queue-short.json'
        queue_receipt = json.loads(queue_path.read_text())
        queue_receipt['caption_overlay'] = rewritten['caption_overlay']
        queue_receipt['artifacts_sha256']['short.json'] = digest(short_path)
        queue_path.write_text(json.dumps(queue_receipt) + '\n')
        # The pre-existing consumer accepts this coherent self-contained rewrite;
        # the reviewer-bound hashes and caption mode must not.
        verify_consumed_short(queue.root, 'cycle-test', short)
        with self.assertRaisesRegex(ValueError, 'different derivative identities'):
            record_short_review(
                queue.root, 'cycle-test', short, submitted,
                self.base / 'must-not-record.json')

    def test_mutation_after_consumer_verification_cannot_make_mixed_snapshot(self):
        queue, short, receipt = self.prepare()
        submitted = self.base / 'submitted-before-race.json'
        submitted.write_text(json.dumps(self.review_input(short, receipt)) + '\n')
        real_verify = review_module.verify_consumed_short
        changed = False

        def mutate_after_verify(*args):
            nonlocal changed
            value = real_verify(*args)
            if not changed:
                changed = True
                short_path = short / 'short.json'
                rewritten = json.loads(short_path.read_text())
                rewritten['preview_caption_mode'] = 'burned'
                rewritten['caption_overlay'] = {
                    'style': review_module.COMPACT_STYLE,
                    'audio_mode': 'stream_copy_from_excerpt',
                    'scope': 'Burned rebased sidecar into a private phone-size review derivative.',
                }
                short_path.write_text(json.dumps(rewritten) + '\n')
                queue_path = short / 'queue-short.json'
                queue_receipt = json.loads(queue_path.read_text())
                queue_receipt['artifacts_sha256']['short.json'] = digest(short_path)
                queue_path.write_text(json.dumps(queue_receipt) + '\n')
            return value

        with patch.object(review_module, 'verify_consumed_short',
                          side_effect=mutate_after_verify), \
                self.assertRaisesRegex(ValueError,
                                       'receipt changed after verification'):
            record_short_review(
                queue.root, 'cycle-test', short, submitted,
                self.base / 'must-not-record-race.json')


if __name__ == '__main__':
    unittest.main()
