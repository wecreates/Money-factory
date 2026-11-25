import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control import cycle_local_audio_listener as listener


class LocalAudioListenerTests(unittest.TestCase):
    def test_coverage_and_followups_stay_separate_from_acceptance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video, caption, output = (root / name for name in ('a.mp4', 'a.vtt', 'observations.jsonl'))
            video.write_bytes(b'video fixture')
            caption.write_bytes(b'WEBVTT')
            observations = [
                {'observation': 'VOICE: Clear\nSOUND: None audible\nMIX: Balanced', 'finish_reason': 'stop'},
                {'observation': 'VOICE: More', 'finish_reason': 'length'},
            ]
            with (patch.object(listener, 'WINDOW', 4),
                  patch.object(listener, 'decode_program', return_value=bytes(12)),
                  patch.object(listener, 'query_audio', side_effect=observations)):
                listener.record(video, caption, output, video_sha256=listener.digest(video),
                                caption_sha256=listener.digest(caption), model='local', port=8791)
            header, first, last, receipt = map(json.loads, output.read_text().splitlines())
            self.assertEqual([(item['start_sample'], item['end_sample']) for item in (first, last)],
                             [(0, 4), (4, 6)])
            self.assertEqual(first['wav_sha256'], hashlib.sha256(listener.wav_bytes(bytes(12))).hexdigest())
            self.assertFalse(first['format_followup_required'])
            self.assertTrue(last['format_followup_required'])
            self.assertEqual(receipt['format_followup_count'], 1)
            self.assertEqual(header['candidate_sha256'], receipt['candidate_sha256'])
            self.assertTrue(all(receipt[key] is False for key in listener.PENDING))

    def test_mismatched_caption_fails_before_decode_or_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video, caption, output = (root / name for name in ('a.mp4', 'a.vtt', 'observations.jsonl'))
            video.write_bytes(b'video fixture')
            caption.write_bytes(b'WEBVTT')
            with patch.object(listener, 'decode_program') as decoder:
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    listener.record(video, caption, output, video_sha256=listener.digest(video),
                                    caption_sha256='0' * 64, model='local', port=8791)
                decoder.assert_not_called()
            self.assertFalse(output.exists())

    def test_missing_sound_and_mix_fields_flag_followup(self):
        self.assertTrue(listener.needs_followup({'observation': 'Pause', 'finish_reason': 'stop'}))
