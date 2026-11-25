"""Derivative thumbnail binding tests; not creative or audience acceptance."""
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

from integrations.content_control.cycle_queue_short import consume_short, _source
from integrations.content_control.cycle_queue_short_selection import (
    record_short_selection, verify_short_selection,
)
from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control.test_cycle_queue_delivery import CycleDeliveryTests
from integrations.content_control.review_package import digest


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'Media tools unavailable')
class QueueShortSelectionTests(unittest.TestCase):
    setUp = CycleDeliveryTests.setUp
    tearDown = CycleDeliveryTests.tearDown
    queue_review = CycleDeliveryTests.queue_review

    def prepare(self, *, safe_area=True):
        media = self.base / ('safe-parent.mp4' if safe_area else 'ordinary-parent.mp4')
        subprocess.run([
            'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
            'color=c=black:s=720x1280:r=24:d=2', '-f', 'lavfi', '-i',
            'anullsrc=r=24000:cl=mono:d=2', '-c:v', 'libx264', '-threads', '1',
            '-c:a', 'aac', str(media),
        ], check=True, timeout=30)
        captions = ('WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\n'
                    'Queue-bound words.\n')
        for directory in (self.delivery, self.render):
            (directory / 'captions.vtt').write_text(captions)
            render_path = directory / 'render.json'
            render = json.loads(render_path.read_text())
            render['caption_sha256'] = digest(directory / 'captions.vtt')
            render_path.write_text(json.dumps(render) + '\n')
        package_path = self.delivery / 'package.json'
        package = json.loads(package_path.read_text())
        package['caption_sha256'] = digest(self.delivery / 'captions.vtt')
        package['render_receipt_sha256'] = digest(self.delivery / 'render.json')
        package['files_sha256']['captions.vtt'] = package['caption_sha256']
        package['files_sha256']['render.json'] = package['render_receipt_sha256']
        package_path.write_text(json.dumps(package) + '\n')
        queue, _, _ = self.queue_review(media=media)
        short = self.base / ('safe-short' if safe_area else 'ordinary-short')
        if safe_area:
            with patch('integrations.content_control.cycle_short.diagram_thumbnail_crop',
                       return_value=(45, 300, 675, 870)):
                receipt = consume_short(queue.root, 'cycle-test', short,
                                        start=0, end=1, timeout=30,
                                        compact_captions=True, caption_safe_area=True)
        else:
            receipt = consume_short(queue.root, 'cycle-test', short,
                                    start=0, end=1, timeout=30)
        self.assertEqual(receipt['status'], 'AWAITING_REVIEW', receipt)
        cycle, _ = _source(queue.root, 'cycle-test')
        snapshot = inspect_cycle(cycle)
        copy = snapshot['editorial'].get(
            'thumbnail_copy', ' '.join(snapshot['editorial']['title'].split()))
        selection = {
            'schema_version': 1,
            'short_candidate_sha256': receipt['candidate_sha256'],
            'parent_candidate_sha256': snapshot['candidate_sha256'],
            'parent_package_sha256': snapshot['files_sha256']['delivery/package.json'],
            'title': snapshot['editorial']['title'],
            'thumbnail_copy': copy,
            'frame_timestamp_seconds': .5,
            'thumbnail_variant': 1,
            'reviewer': 'Fixture editorial operator',
            'reviewed_at': receipt['finished_at'],
            'rationale': ('Synthetic frame and treatment choice for binding tests; '
                          'not an actual visual approval.'),
            'next_idea_hypotheses': [
                'Test a shorter thumbnail phrase in a future unpublished candidate.',
            ],
        }
        submitted = self.base / ('safe-selection.json' if safe_area
                                 else 'ordinary-selection.json')
        submitted.write_text(json.dumps(selection) + '\n')
        return queue, short, cycle, snapshot, submitted, selection

    def test_exact_derivative_thumbnail_replays_and_stays_unapproved(self):
        queue, short, _, snapshot, submitted, _ = self.prepare()
        output = self.base / 'derivative-selection'
        result = record_short_selection(
            queue.root, 'cycle-test', short, submitted, output)
        before = (output / 'thumbnail.png').read_bytes()
        verified, _ = verify_short_selection(
            queue.root, 'cycle-test', short, submitted, output)
        self.assertEqual(result, verified)
        self.assertEqual((output / 'thumbnail.png').read_bytes(), before)
        self.assertEqual(result['thumbnail_source_candidate_sha256'],
                         digest(short / 'video.mp4'))
        parent_thumbnails = {
            value for key, value in snapshot['files_sha256'].items()
            if key.startswith('delivery/thumbnail-')
        }
        self.assertNotIn(result['thumbnail_sha256'], parent_thumbnails)
        self.assertEqual(result['performance']['status'], 'UNAVAILABLE')
        self.assertFalse(result['performance']['audience_performance_verified'])
        self.assertFalse(result['performance']['winner_inferred'])
        self.assertFalse(result['exact_derivative_visual_review_verified'])
        for key in ('publication_enabled', 'paid_generation_enabled',
                    'production_approved', 'full_av_review', 'production_ready'):
            self.assertFalse(result[key])

    def test_non_safe_area_short_is_rejected(self):
        queue, short, _, _, submitted, _ = self.prepare(safe_area=False)
        output = self.base / 'invalid-derivative-selection'
        with self.assertRaisesRegex(ValueError, 'caption-safe-area'):
            record_short_selection(
                queue.root, 'cycle-test', short, submitted, output)
        self.assertFalse(output.exists())

    def test_media_receipt_choice_thumbnail_and_parent_tampering_fail_replay(self):
        queue, short, cycle, _, submitted, selection = self.prepare()
        output = self.base / 'tamper-selection'
        record_short_selection(queue.root, 'cycle-test', short, submitted, output)

        paths = {
            'video': short / 'video.mp4',
            'queue_receipt': short / 'queue-short.json',
            'thumbnail': output / 'thumbnail.png',
            'parent_package': cycle / 'delivery/package.json',
        }
        for label, path in paths.items():
            original = path.read_bytes()
            with self.subTest(label=label):
                path.write_bytes(original + b'\n')
                with self.assertRaises((ValueError, RuntimeError)):
                    verify_short_selection(
                        queue.root, 'cycle-test', short, submitted, output)
                path.write_bytes(original)

        for field, value in (
            ('title', 'Different title'),
            ('thumbnail_copy', 'Different copy'),
            ('frame_timestamp_seconds', .75),
            ('parent_candidate_sha256', '0' * 64),
        ):
            with self.subTest(field=field):
                changed = dict(selection, **{field: value})
                submitted.write_text(json.dumps(changed) + '\n')
                with self.assertRaises(ValueError):
                    verify_short_selection(
                        queue.root, 'cycle-test', short, submitted, output)
                submitted.write_text(json.dumps(selection) + '\n')

    def test_output_and_disabled_mode_guards(self):
        queue, short, _, _, submitted, _ = self.prepare()
        output = self.base / 'guarded-selection'
        record_short_selection(queue.root, 'cycle-test', short, submitted, output)
        original = (output / 'selection.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            record_short_selection(queue.root, 'cycle-test', short, submitted, output)
        self.assertEqual((output / 'selection.json').read_bytes(), original)
        with self.assertRaisesRegex(ValueError, 'separate'):
            record_short_selection(
                queue.root, 'cycle-test', short, submitted, short / 'selection')
        for key in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED'):
            with self.subTest(record_guard=key), \
                    patch.dict('os.environ', {key: 'true'}), \
                    self.assertRaisesRegex(ValueError, 'must remain disabled'):
                record_short_selection(
                    queue.root, 'cycle-test', short, submitted,
                    self.base / f'enabled-{key}')
            with self.subTest(verify_guard=key), \
                    patch.dict('os.environ', {key: 'true'}), \
                    self.assertRaisesRegex(ValueError, 'must remain disabled'):
                verify_short_selection(
                    queue.root, 'cycle-test', short, submitted, output)

    def test_post_read_output_mutation_is_rejected(self):
        queue, short, _, _, submitted, _ = self.prepare()
        output = self.base / 'racing-selection'
        record_short_selection(queue.root, 'cycle-test', short, submitted, output)
        from integrations.content_control import cycle_queue_short_selection as module
        original_unchanged = module._unchanged
        for name in ('thumbnail.png', 'selection.json'):
            target = output / name
            original = target.read_bytes()
            def mutate(*args, **kwargs):
                result = original_unchanged(*args, **kwargs)
                target.write_bytes(original + b'\n')
                return result
            with self.subTest(name=name), \
                    patch.object(module, '_unchanged', side_effect=mutate), \
                    self.assertRaisesRegex(ValueError, 'changed while verifying'):
                verify_short_selection(
                    queue.root, 'cycle-test', short, submitted, output)
            target.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
