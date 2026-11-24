"""The durable queue consumer binds a real encoded Short to its exact parent."""
import json
import shutil
import unittest

from integrations.content_control.cycle_queue_short import consume_short, verify_consumed_short
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
