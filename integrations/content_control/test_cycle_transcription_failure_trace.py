"""Diagnostic unit fixtures, not actual recognition or media acceptance."""
from contextlib import ExitStack
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from integrations.content_control import cycle_render as render


class TraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixed = render

    def fixture(self, module, end=1.1, second=False, expected_text=None, probability=.9):
        directory = tempfile.TemporaryDirectory(prefix='caption-unit-')
        self.addCleanup(directory.cleanup)
        out = Path(directory.name)
        (out / 'video.mp4').write_bytes(b'Explicit synthetic identity fixture, not playable video')
        (out / 'captions.vtt').write_bytes(b'original approximate captions sentinel')
        helper = out / 'scripts/free_transcription_qa.py'
        helper.parent.mkdir()
        helper.write_text('def decode_transcription_audio(video):return [],1.5\n'
                          'def spoken_number_suppression(tokenizer):return []\n'
                          'def norm(text):return text.lower()\n')
        words = [SimpleNamespace(word='hello', start=.2, end=end, probability=probability)]
        if second:
            words = [SimpleNamespace(word='hello', start=0, end=.5, probability=.9),
                     SimpleNamespace(word='world', start=.4, end=.8, probability=.8)]
        text = 'hello world' if second else 'hello'
        model = SimpleNamespace(hf_tokenizer=None, transcribe=lambda *a, **k:
                                ([SimpleNamespace(text=text, words=words)], None))
        contexts = [patch.object(module, 'pinned_asr_snapshot', return_value=(out, {})),
                    patch.object(module, 'encoded_media_duration', return_value=1.0),
                    patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=lambda *a, **k: model)}),
                    patch.object(socket.socket, 'connect', side_effect=AssertionError('Offline fixture attempted network'))]
        with ExitStack() as stack:
            for context in contexts:
                stack.enter_context(context)
            try:
                module.transcribe_encoded({'scenes': [{'narration': expected_text or text}]}, out, out)
                failure = None
            except ValueError as error:
                failure = error
        return out, failure

    def test_failure_preserves_raw_observation_and_sidecar(self):
        out, failure = self.fixture(self.fixed)
        self.assertRegex(str(failure), 'Invalid observed word timing')
        report = json.loads((out / 'transcription.json').read_text())
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['words'], [{'word': 'hello', 'start': .2, 'end': 1.1, 'probability': .9}])
        self.assertEqual(report['caption_validation_error']['word_index'], 0)
        self.assertEqual(report['caption_validation_error']['reason'], 'outside_encoded_bounds_or_reversed_interval')
        self.assertEqual((out / 'captions.vtt').read_bytes(), b'original approximate captions sentinel')
        self.assertFalse(report['production_approved'])
        self.assertNotIn('caption_sha256', report)

    def test_overlap_rejected_and_index_preserved(self):
        out, failure = self.fixture(self.fixed, second=True)
        self.assertIsNotNone(failure)
        report = json.loads((out / 'transcription.json').read_text())
        self.assertEqual(report['caption_validation_error']['word_index'], 1)
        self.assertEqual(report['caption_validation_error']['previous_end'], .5)
        self.assertEqual(report['words'][1]['start'], .4)

    def test_nonfinite_trace_remains_valid_json_and_rejected(self):
        out, failure = self.fixture(self.fixed, end=float('nan'))
        self.assertIsNotNone(failure)
        report = json.loads((out / 'transcription.json').read_text())
        self.assertEqual(report['words'][0]['end'], {'nonfinite_float': 'nan'})
        self.assertEqual(report['caption_validation_error']['reason'], 'nonfinite_time')
        self.assertEqual(report['status'], 'FAIL')

    def test_valid_observation_still_passes_without_approval(self):
        out, failure = self.fixture(self.fixed, end=.7)
        self.assertIsNone(failure)
        report = json.loads((out / 'transcription.json').read_text())
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['words'][0]['end'], .7)
        self.assertFalse(report['full_av_review'])
        self.assertFalse(report['production_approved'])

    def test_nonfinite_trace_survives_comparison_mismatch(self):
        out, failure = self.fixture(self.fixed, end=float('nan'), expected_text='different script')
        self.assertRegex(str(failure), 'speech comparison failed')
        report = json.loads((out / 'transcription.json').read_text())
        self.assertEqual(report['status'], 'FAIL')
        self.assertFalse(report['comparison']['passed'])
        self.assertEqual(report['words'][0]['end'], {'nonfinite_float': 'nan'})
        self.assertEqual((out / 'captions.vtt').read_bytes(), b'original approximate captions sentinel')

    def test_nonfinite_probability_with_valid_timing_cannot_pass(self):
        out, failure = self.fixture(self.fixed, end=.7, probability=float('nan'))
        self.assertRegex(str(failure), 'not JSON compliant')
        report = json.loads((out / 'transcription.json').read_text())
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['words'][0]['probability'], {'nonfinite_float': 'nan'})
        self.assertNotIn('caption_sha256', report)
        self.assertEqual((out / 'captions.vtt').read_bytes(), b'original approximate captions sentinel')

    def test_zero_duration_policy_is_unchanged(self):
        words = [{'word': 'Oh!', 'start': 0, 'end': 0}, {'word': 'Hello.', 'start': 0, 'end': .5}]
        self.assertIn('00:00:00.000 --> 00:00:00.500\nOh! Hello.', self.fixed.observed_captions(words, 1))
        with self.assertRaisesRegex(ValueError, 'Empty observed caption duration'):
            self.fixed.observed_captions(words[:1], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
