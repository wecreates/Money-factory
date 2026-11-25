"""The durable queue consumer binds a real encoded Short to its exact parent."""
import io
import json
import shutil
import subprocess
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import patch

from integrations.content_control.cycle_queue_short import (
    PRE_CAPTION_SAFE_AREA_TOOL_PAIR, PRE_COMPACT_QUOTE_TOOL_PAIR,
    PRE_RETAINED_CYCLE_TOOL_PAIR,
    consume_short, main, verify_consumed_short,
)
from integrations.content_control.cycle_queue_short_review import (
    PRE_SAFE_AREA_REVIEW_TOOL_SHA256, record_short_review, verify_caption_revision,
    verify_recorded_short_review,
)
from integrations.content_control.test_cycle_job import synthetic_picture_mp4
from integrations.content_control.test_cycle_queue_delivery import CycleDeliveryTests
from integrations.content_control.review_package import digest


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'Media tools unavailable')
class QueueShortTests(unittest.TestCase):
    setUp = CycleDeliveryTests.setUp
    tearDown = CycleDeliveryTests.tearDown
    queue_review = CycleDeliveryTests.queue_review

    def prepare(self):
        media = self.base / 'portrait-parent.mp4'
        synthetic_picture_mp4(media, 2, audio_seconds=2)
        queue, _, _ = self.queue_review(media=media)
        return queue

    def prepare_with_scene_timeline(self, rows=None):
        rows = rows or [
            {'scene_id': 'hook', 'start': 0, 'end': .5},
            {'scene_id': 'example', 'start': .5, 'end': 1},
            {'scene_id': 'takeaway', 'start': 1, 'end': 1.5},
        ]
        for path in (self.delivery / 'render.json', self.render / 'render.json'):
            receipt = json.loads(path.read_text())
            receipt['scenes'] = rows
            path.write_text(json.dumps(receipt) + '\n')
        return self.prepare()

    def test_real_consumer_replays_queue_and_exact_media_identities(self):
        queue = self.prepare()
        output = self.base / 'durable-short'
        result = consume_short(queue.root, 'cycle-test', output,
                               start=0, end=1, timeout=30)
        self.assertEqual(result['status'], 'AWAITING_REVIEW')
        self.assertFalse(result['publication_enabled'])
        self.assertFalse(result['paid_generation_enabled'])
        self.assertEqual(result['source_provenance']['job_id'], 'cycle-test')
        self.assertEqual(result['source_provenance']['candidate_sha256'],
                         json.loads((output / 'short.json').read_text())['parent_candidate_sha256'])
        self.assertEqual(result, verify_consumed_short(queue.root, 'cycle-test', output))

    def safe_area_short(self):
        media = self.base / 'portrait-parent-large.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
                        'color=c=black:s=720x1280:r=24:d=2','-f','lavfi','-i',
                        'anullsrc=r=24000:cl=mono:d=2','-c:v','libx264','-threads','1',
                        '-c:a','aac',str(media)],check=True,timeout=30)
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
        output = self.base / 'safe-caption-short'
        # The shared queue fixture predates visual_spec/render-layout evidence;
        # the exporter's real-layout guard is covered by test_cycle_short.
        with patch('integrations.content_control.cycle_short.diagram_thumbnail_crop',
                   return_value=(45, 300, 675, 870)):
            result = consume_short(queue.root, 'cycle-test', output,
                                   start=0, end=1, timeout=30,
                                   compact_captions=True, caption_safe_area=True)
        self.assertEqual(result['status'], 'AWAITING_REVIEW', result)
        return queue, output, result

    def test_caption_safe_area_is_bound_and_overlay_tampering_fails_replay(self):
        queue, output, result = self.safe_area_short()
        short = json.loads((output / 'short.json').read_text())
        self.assertEqual(result['caption_overlay'], short['caption_overlay'])
        self.assertEqual(result['caption_overlay']['picture_layout']['mode'],
                         'scaled_picture_safe_caption_area_v1')
        self.assertEqual(result, verify_consumed_short(queue.root, 'cycle-test', output))

        receipt_path = output / 'queue-short.json'
        changed = dict(result)
        changed['caption_overlay'] = dict(result['caption_overlay'], style='changed')
        receipt_path.write_text(json.dumps(changed) + '\n')
        with self.assertRaisesRegex(ValueError, 'do not bind'):
            verify_consumed_short(queue.root, 'cycle-test', output)

    def test_safe_area_repair_review_accepts_current_but_not_legacy_tool_identity(self):
        queue, short, result = self.safe_area_short()
        submission = self.base / 'safe-repair-fixture.json'
        submission.write_text(json.dumps({
            'candidate_sha256': result['candidate_sha256'],
            'caption_sha256': result['caption_sha256'],
            'queue_short_sha256': digest(short / 'queue-short.json'),
            'short_receipt_sha256': digest(short / 'short.json'),
            'preview_caption_mode': 'burned',
            'reviewer': 'Synthetic test fixture',
            'reviewed_at': datetime.now(timezone.utc).isoformat(),
            'basis': 'supplied_repair_findings_not_acceptance',
            'findings': [{'check': 'caption_readability',
                          'evidence': 'Synthetic fixture observation at 00:00.250.',
                          'action': 'Test caption readability against safe area.'}],
        }))
        output = self.base / 'safe-repair-result.json'
        recorded = record_short_review(queue.root, 'cycle-test', short, submission, output)
        self.assertEqual(recorded, verify_recorded_short_review(queue.root, 'cycle-test', short, output))
        self.assertEqual(recorded['status'], 'REVISION_REQUIRED')
        self.assertFalse(recorded['full_av_review'])
        self.assertFalse(recorded['publication_enabled'])
        self.assertFalse(recorded['paid_generation_enabled'])

        revision = self.base / 'safe-caption-revision-fixture'
        revision.mkdir()
        (revision / 'captions.vtt').write_bytes((short / 'captions.vtt').read_bytes())
        (revision / 'short-caption-revision.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'requires a sidecar Short'):
            verify_caption_revision(queue.root, 'cycle-test', short, output, revision)

        recorded['tool_sha256'] = PRE_SAFE_AREA_REVIEW_TOOL_SHA256
        output.write_text(json.dumps(recorded))
        with self.assertRaisesRegex(ValueError, 'scope or flags'):
            verify_recorded_short_review(queue.root, 'cycle-test', short, output)

    def test_pre_safe_area_tool_pair_remains_an_exact_historical_pair(self):
        self.assertEqual(PRE_CAPTION_SAFE_AREA_TOOL_PAIR, (
            'e60e6a677f9a4fdb6e9d23af8a680388bb23b54e282ef4ea682b6c288bab10d3',
            'b180215c13c38d2a73f7adc856e45a1ad3efee516ec02dba173949cb75890918',
        ))

    def test_pre_compact_quote_receipt_without_queue_overlay_replays(self):
        prior_consumer, prior_exporter = PRE_COMPACT_QUOTE_TOOL_PAIR

        def historical_digest(module_name, identity):
            def calculate(path, *args, **kwargs):
                if path.name == module_name:
                    return identity
                return digest(path, *args, **kwargs)
            return calculate

        with patch('integrations.content_control.cycle_queue_short.digest',
                   side_effect=historical_digest('cycle_queue_short.py', prior_consumer)), \
             patch('integrations.content_control.cycle_short.digest',
                   side_effect=historical_digest('cycle_short.py', prior_exporter)):
            queue = self.prepare_with_scene_timeline()
            output = self.base / 'pre-compact-short'
            result = consume_short(queue.root, 'cycle-test', output,
                                   scene_ids=['hook', 'example'], timeout=30)

        receipt_path = output / 'queue-short.json'
        receipt = json.loads(receipt_path.read_text())
        self.assertNotIn('caption_overlay', receipt)
        short_path = output / 'short.json'
        short = json.loads(short_path.read_text())
        short['caption_overlay'] = {
            'audio_mode': 'stream_copy_from_excerpt',
            'scope': 'Burned rebased sidecar into a private phone-size review derivative.',
            'style': 'FontName=DejaVu Sans,FontSize=10,MarginV=4,Outline=1.1,Shadow=0,Alignment=2',
        }
        short_path.write_text(json.dumps(short) + '\n')
        receipt['artifacts_sha256']['short.json'] = digest(short_path)
        receipt_path.write_text(json.dumps(receipt) + '\n')
        self.assertEqual(receipt, verify_consumed_short(
            queue.root, 'cycle-test', output))

    def test_pre_retained_cycle_receipt_without_queue_overlay_replays(self):
        prior_consumer, prior_exporter = PRE_RETAINED_CYCLE_TOOL_PAIR

        def historical_digest(module_name, identity):
            def calculate(path, *args, **kwargs):
                if path.name == module_name:
                    return identity
                return digest(path, *args, **kwargs)
            return calculate

        with patch('integrations.content_control.cycle_queue_short.digest',
                   side_effect=historical_digest('cycle_queue_short.py', prior_consumer)), \
             patch('integrations.content_control.cycle_short.digest',
                   side_effect=historical_digest('cycle_short.py', prior_exporter)):
            queue = self.prepare_with_scene_timeline()
            output = self.base / 'pre-retained-cycle-short'
            consume_short(queue.root, 'cycle-test', output,
                          scene_ids=['hook', 'example'], timeout=30)

        receipt_path = output / 'queue-short.json'
        receipt = json.loads(receipt_path.read_text())
        self.assertNotIn('caption_overlay', receipt)
        short_path = output / 'short.json'
        short = json.loads(short_path.read_text())
        short['caption_overlay'] = {
            'audio_mode': 'stream_copy_from_excerpt',
            'scope': 'Burned rebased sidecar into a private phone-size review derivative.',
            'style': 'FontName=DejaVu Sans,FontSize=10,MarginV=4,Outline=1.1,Shadow=0,Alignment=2',
        }
        short_path.write_text(json.dumps(short) + '\n')
        receipt['artifacts_sha256']['short.json'] = digest(short_path)
        receipt_path.write_text(json.dumps(receipt) + '\n')
        self.assertEqual(receipt, verify_consumed_short(
            queue.root, 'cycle-test', output))

    def test_authored_scene_span_resolves_bound_parent_timeline(self):
        queue = self.prepare_with_scene_timeline()
        output = self.base / 'scene-short'
        result = consume_short(queue.root, 'cycle-test', output,
                               scene_ids=['hook', 'example'], timeout=30)
        selection = result['selection']
        self.assertEqual(selection['method'], 'authored_contiguous_scene_span_v1')
        self.assertEqual(selection['scene_ids'], ['hook', 'example'])
        self.assertEqual((selection['start_seconds'], selection['end_seconds']), (0, 1))
        self.assertFalse(selection['editorial_selection_verified'])
        self.assertEqual(result, verify_consumed_short(queue.root, 'cycle-test', output))

        receipt_path = output / 'queue-short.json'
        changed = dict(result)
        changed['selection'] = dict(selection, scene_ids=['example'])
        receipt_path.write_text(json.dumps(changed) + '\n')
        with self.assertRaisesRegex(ValueError, 'selection no longer matches'):
            verify_consumed_short(queue.root, 'cycle-test', output)

    def test_frame_fraction_scene_bounds_use_exporter_millisecond_contract(self):
        frame = 1 / 24
        queue = self.prepare_with_scene_timeline([
            {'scene_id': 'hook', 'start': 0, 'end': 10 * frame},
            {'scene_id': 'example', 'start': 10 * frame, 'end': 25 * frame},
            {'scene_id': 'takeaway', 'start': 25 * frame, 'end': 36 * frame},
        ])
        output = self.base / 'frame-fraction-short'
        result = consume_short(queue.root, 'cycle-test', output,
                               scene_ids=['hook', 'example'], timeout=30)
        self.assertEqual(result['status'], 'AWAITING_REVIEW')
        self.assertEqual(result['selection']['end_seconds'], 1.042)
        self.assertEqual(result['selection']['end_seconds'], result['end_seconds'])
        self.assertEqual(result, verify_consumed_short(queue.root, 'cycle-test', output))

    def test_post_verification_failure_is_blocked_and_cli_nonzero(self):
        queue = self.prepare()
        output = self.base / 'late-failure-short'
        with patch('integrations.content_control.cycle_queue_short._verify_payload',
                   side_effect=ValueError('injected late verification failure')):
            result = consume_short(queue.root, 'cycle-test', output,
                                   start=0, end=1, timeout=30)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['technical_status'], 'FAIL')
        self.assertIn('injected late verification failure', result['reason'])
        with self.assertRaisesRegex(ValueError, 'not an unpublished PASS'):
            verify_consumed_short(queue.root, 'cycle-test', output)

        cli_output = self.base / 'late-failure-cli-short'
        argv = ['cycle_queue_short', '--queue-root', str(queue.root),
                '--job-id', 'cycle-test', '--output', str(cli_output),
                '--start', '0', '--end', '1', '--timeout', '30']
        with patch('integrations.content_control.cycle_queue_short._verify_payload',
                   side_effect=ValueError('injected CLI verification failure')), \
                patch('sys.argv', argv), redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 2)
        cli_receipt = json.loads((cli_output / 'queue-short.json').read_text())
        self.assertEqual((cli_receipt['status'], cli_receipt['technical_status']),
                         ('BLOCKED', 'FAIL'))

    def test_scene_selection_rejects_missing_noncontiguous_or_mixed_bounds(self):
        queue = self.prepare_with_scene_timeline()
        cases = [
            {'scene_ids': ['missing']},
            {'scene_ids': ['hook', 'takeaway']},
            {'scene_ids': ['hook'], 'start': 0, 'end': .5},
        ]
        for index, values in enumerate(cases):
            output = self.base / f'blocked-scene-short-{index}'
            with self.subTest(values=values), self.assertRaises(ValueError):
                consume_short(queue.root, 'cycle-test', output, timeout=30, **values)
            self.assertFalse(output.exists())

    def test_output_or_durable_queue_mutation_fails_replay(self):
        queue = self.prepare()
        output = self.base / 'durable-short'
        consume_short(queue.root, 'cycle-test', output, start=0, end=1, timeout=30)
        original = (output / 'captions.vtt').read_bytes()
        (output / 'captions.vtt').write_bytes(original + b'\n')
        with self.assertRaisesRegex(ValueError, 'artifact identity changed'):
            verify_consumed_short(queue.root, 'cycle-test', output)
        (output / 'captions.vtt').write_bytes(original)
        queue.db.execute("UPDATE jobs SET state='interrupted' WHERE id='cycle-test'")
        with self.assertRaisesRegex(ValueError, 'durably succeeded'):
            verify_consumed_short(queue.root, 'cycle-test', output)

    def test_consumer_and_exporter_receipt_mutations_fail_closed(self):
        queue = self.prepare()
        output = self.base / 'durable-short'
        original = consume_short(queue.root, 'cycle-test', output,
                                 start=0, end=1, timeout=30)
        receipt_path = output / 'queue-short.json'
        mutations = {
            'schema_version': 2, 'status': 'PASS', 'technical_status': 'BLOCKED',
            'publication_enabled': True, 'paid_generation_enabled': True,
            'production_approved': True, 'full_av_review': True,
            'production_ready': True, 'start_seconds': .25,
            'end_seconds': .75, 'source_caption_sha256': '0' * 64,
            'preview_sha256': '1' * 64, 'automated_review_sha256': '2' * 64,
            'candidate_sha256': '3' * 64, 'caption_sha256': '4' * 64,
            'decoded_picture_sha256': '7' * 64,
            'encoded_streams_sha256': {'video': '8' * 64, 'audio': '9' * 64},
            'parent_candidate_sha256': '5' * 64,
            'parent_cycle_sha256': '6' * 64,
            'media': {'width': 1, 'height': 1, 'duration_seconds': 1},
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                changed = dict(original); changed[field] = value
                receipt_path.write_text(json.dumps(changed) + '\n')
                with self.assertRaises(ValueError):
                    verify_consumed_short(queue.root, 'cycle-test', output)
        receipt_path.write_text(json.dumps(original) + '\n')

        prior_consumer, prior_exporter = PRE_COMPACT_QUOTE_TOOL_PAIR
        for changes in ({'consumer_tool_sha256': prior_consumer},
                        {'exporter_tool_sha256': prior_exporter},
                        {'consumer_tool_sha256': '0' * 64},
                        {'exporter_tool_sha256': []}):
            with self.subTest(tool_identities=changes):
                receipt_path.write_text(json.dumps(dict(original, **changes)) + '\n')
                with self.assertRaisesRegex(ValueError, 'not an unpublished PASS'):
                    verify_consumed_short(queue.root, 'cycle-test', output)
        # A historical consumer pair still has to match the exporter receipt.
        changed = dict(original, consumer_tool_sha256=prior_consumer,
                       exporter_tool_sha256=prior_exporter)
        receipt_path.write_text(json.dumps(changed) + '\n')
        with self.assertRaisesRegex(ValueError, 'does not bind'):
            verify_consumed_short(queue.root, 'cycle-test', output)
        receipt_path.write_text(json.dumps(original) + '\n')

        # Even a matching rewritten artifact map cannot turn an invalid
        # exporter receipt into a valid queue consumer result.
        short_path = output / 'short.json'
        short = json.loads(short_path.read_text()); short['status'] = 'PASS'
        short_path.write_text(json.dumps(short) + '\n')
        changed = dict(original); changed['artifacts_sha256'] = dict(original['artifacts_sha256'])
        changed['artifacts_sha256']['short.json'] = digest(short_path)
        receipt_path.write_text(json.dumps(changed) + '\n')
        with self.assertRaisesRegex(ValueError, 'do not bind'):
            verify_consumed_short(queue.root, 'cycle-test', output)

    def test_invalid_interval_never_creates_a_consumer_pass(self):
        queue = self.prepare()
        output = self.base / 'blocked-short'
        with self.assertRaisesRegex(ValueError, 'exceeds source media'):
            consume_short(queue.root, 'cycle-test', output,
                          start=0, end=3, timeout=30)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
