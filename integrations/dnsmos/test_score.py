import io
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import unittest
import wave
from unittest.mock import patch

from integrations.dnsmos import score


def wav_bytes(seconds=10, *, rate=16000, channels=1, amplitude=1000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        samples = [int(amplitude * math.sin(2 * math.pi * 220 * i / rate))
                   for i in range(int(seconds * rate))]
        wav.writeframes(b''.join(struct.pack('<h', value) * channels for value in samples))
    return output.getvalue()


class InputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'input.wav'

    def write(self, **kwargs):
        self.path.write_bytes(wav_bytes(**kwargs))
        return self.path

    def test_explicit_speech_assertion_required_before_model_or_audio(self):
        with patch.object(score, 'model_input', side_effect=AssertionError('must not load')):
            report = score.score_file(self.path, 'absent.onnx')
        self.assertEqual(report['blocker'], 'explicit_isolated_speech_assertion_required')
        self.assertFalse(report['production_approved'])
        self.assertFalse(report['publication_enabled'])

    def test_stereo_and_other_rates_rejected(self):
        for kwargs in ({'channels': 2}, {'rate': 48000}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, '16khz_mono'):
                score.audio_input(self.write(**kwargs), isolated_speech=True)

    def test_empty_short_and_oversized_rejected(self):
        for duration in (0, 9):
            with self.subTest(duration=duration), self.assertRaisesRegex(ValueError, '9_01_to_120'):
                score.audio_input(self.write(seconds=duration), isolated_speech=True)
        self.path.write_bytes(b'x' * (120 * 16000 * 2 + 65537))
        with self.assertRaisesRegex(ValueError, 'input_size_limit'):
            score.audio_input(self.path, isolated_speech=True)

    def test_truncated_pcm_rejected(self):
        self.path.write_bytes(wav_bytes()[:-2])
        with self.assertRaisesRegex(ValueError, 'truncated_audio'):
            score.audio_input(self.path, isolated_speech=True)

    def test_exact_window_and_full_input_identity(self):
        data, pcm, count = score.audio_input(self.write(seconds=9.01), isolated_speech=True)
        self.assertEqual(count, score.WINDOW_SAMPLES)
        self.assertEqual(len(pcm), 2 * count)
        self.assertEqual(data, self.path.read_bytes())

    def test_modified_model_rejected_before_runtime_import(self):
        model = Path(self.tmp.name) / 'wrong.onnx'
        model.write_bytes(b'wrong model')
        report = score.score_file(self.write(), model, isolated_speech=True)
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertEqual(report['blocker'], 'pinned_model_identity_mismatch')

    def test_calibration_matches_upstream_regular_coefficients_and_rejects_nan(self):
        result = score.calibrated([3.0, 2.0, 4.0])
        self.assertAlmostEqual(result['SIG'], 2.91200747)
        self.assertAlmostEqual(result['BAK'], 2.29558930)
        self.assertAlmostEqual(result['OVRL'], 3.42527879)
        with self.assertRaisesRegex(ValueError, 'nonfinite_model_output'):
            score.calibrated([float('nan'), 2, 3])

    @unittest.skipUnless(os.environ.get('CYZOR_DNSMOS_TEST_MODEL'), 'pinned local model not supplied')
    def test_runtime_failure_is_blocked_json_but_cancellation_propagates(self):
        import onnxruntime as ort
        model = os.environ['CYZOR_DNSMOS_TEST_MODEL']
        path = self.write()
        failure = ort.capi.onnxruntime_pybind11_state.RuntimeException('private diagnostic details')
        with patch.object(ort, 'InferenceSession', side_effect=failure):
            result = score.score_file(path, model, isolated_speech=True)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['blocker'], 'onnxruntime_RuntimeException')
        self.assertNotIn('private diagnostic details', json.dumps(result))
        with patch.object(ort, 'InferenceSession', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                score.score_file(path, model, isolated_speech=True)

    @unittest.skipUnless(os.environ.get('CYZOR_DNSMOS_TEST_MODEL'), 'pinned local model not supplied')
    def test_real_pinned_cpu_inference_is_diagnostic_only_and_silence_is_blocked(self):
        model = os.environ['CYZOR_DNSMOS_TEST_MODEL']
        report = score.score_file(self.write(), model, isolated_speech=True)
        self.assertEqual(report['status'], 'DIAGNOSTIC_COMPLETE', report)
        self.assertEqual(report['providers'], ['CPUExecutionProvider'])
        self.assertEqual(report['window_count'], 1)
        self.assertEqual(report['onnx_intra_op_threads'], 1)
        self.assertEqual(report['onnx_inter_op_threads'], 1)
        self.assertFalse(report['full_av_review'])
        self.assertNotIn('quality_pass', report)
        self.assertTrue(all(math.isfinite(value) for value in report['scores'].values()))
        json.dumps(report, allow_nan=False)
        silent = score.score_file(self.write(amplitude=0), model, isolated_speech=True)
        self.assertEqual(silent['blocker'], 'silent_input_not_speech_quality_evidence')


if __name__ == '__main__':
    unittest.main()
