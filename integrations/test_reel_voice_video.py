import copy
import io
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

from reel_media import digest, read_bytes, read_json
from voicestudio import reel_adapter as voice
from open_higgsfield import adapter as video

FLAGS = {'publication_enabled': False, 'paid_generation_enabled': False}


def narration():
    return {**FLAGS, 'ccsd': {'publication_enabled': False, 'scenes': [
        {'id': 'hook', 'start': 0, 'end': 3, 'audio': {'dialogue': [
            {'speaker': 'narrator', 'text': 'A small example for review.'}]}}]},
        'scene_id': 'hook', 'dialogue_index': 0, 'voice': 'expr-voice-2-f'}


def generation():
    return {**FLAGS, 'project_id': 'demo', 'scene_id': 'hook', 'model': 'kling-3-turbo',
            'prompt': 'A pencil sketch of a growing plant.'}


def wav(rate=24000, seconds=1, silent=False, clipped=False):
    stream = io.BytesIO()
    samples = [0 if silent else 32767 if clipped else int(3000 * math.sin(n / 10))
               for n in range(int(rate * seconds))]
    with wave.open(stream, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate)
        out.writeframes(struct.pack('<' + 'h' * len(samples), *samples))
    return stream.getvalue()


class VoiceVideoAdapters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def file(self, name, data):
        path = self.root / name
        path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
        return str(path)

    def voice_export(self, raw=None):
        prepared = voice.prepare_narration(narration())
        raw = wav() if raw is None else raw
        record = {**FLAGS, 'status': 'PASS', 'tool': 'voicestudio', 'operation': 'synthesize',
            'engine': 'kittentts', 'upstream_revision': voice.RUNTIME_REVISION,
            'model': voice.MODEL, 'model_revision': voice.MODEL_REVISION,
            'model_files_sha256': voice.MODEL_FILES,
            'text_sha256': digest(prepared['request']['text'].encode()),
            'voice': 'expr-voice-2-f', 'speed': 1.0, 'language': 'en',
            'output_sha256': digest(raw), 'synthetic': True, 'watermark_applied': False}
        return {**FLAGS, 'preparation': narration(), 'audio': self.file('a.wav', raw),
                'generation': self.file('generation.json', record)}

    def video_export(self):
        prep = generation()
        prepared = video.prepare_generation(prep)
        # Intentional header-only fixture, never described as decoded video.
        raw = b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42'
        return {**FLAGS, 'preparation': prep, 'export': {
            'path': self.file('export.mp4', raw), 'sha256': digest(raw),
            'request_sha256': prepared['request_sha256'], 'media_type': 'video/mp4'}}

    def test_voice_prepare_matches_existing_runner_request(self):
        data = narration(); before = copy.deepcopy(data)
        prepared = voice.prepare_narration(data)
        self.assertEqual(prepared['request'], {**FLAGS, 'text': 'A small example for review.',
            'voice': 'expr-voice-2-f', 'speed': 1.0, 'language': 'en'})
        self.assertEqual(data, before)
        self.assertFalse(prepared['voice_assignment_changed'])
        self.assertEqual(prepared['runtime_revision'], voice.RUNTIME_REVISION)
        self.assertNotEqual(prepared['runtime_revision'], prepared['reviewed_download_revision'])

    def test_voice_requires_explicit_preset(self):
        for invalid in (None, '', 'alloy', 'default', 'am_adam', 'omnivoice', [], True):
            with self.subTest(invalid=invalid):
                data = narration(); data['voice'] = invalid
                with self.assertRaises(ValueError): voice.prepare_narration(data)

    def test_nonverbal_role_stays_silent(self):
        data = narration(); data['ccsd']['scenes'][0]['audio']['dialogue'][0]['speaker'] = 'cashback_goblin'
        with self.assertRaises(ValueError): voice.prepare_narration(data)

    def test_duplicate_missing_scene_rejected(self):
        data = narration(); data['ccsd']['scenes'] *= 2
        with self.assertRaises(ValueError): voice.prepare_narration(data)
        data = narration(); data['scene_id'] = 'missing'
        with self.assertRaises(ValueError): voice.prepare_narration(data)

    def test_explicit_dialogue_index(self):
        for invalid in (None, True, -1, 1, '0'):
            data = narration(); data['dialogue_index'] = invalid
            with self.assertRaises(ValueError): voice.prepare_narration(data)

    def test_bad_timing_rejected(self):
        for start, end in ((0, 0), (-1, 3), (0, float('nan')), (True, 3), ('0', 3)):
            data = narration(); data['ccsd']['scenes'][0].update(start=start, end=end)
            with self.assertRaises(ValueError): voice.prepare_narration(data)

    def test_bad_speed_rejected(self):
        for speed in (0, 1.6, float('inf'), True, '1'):
            data = narration(); data['speed'] = speed
            with self.assertRaises(ValueError): voice.prepare_narration(data)

    def test_text_limits_rejected(self):
        for text in ('', '1234', 'x' * 1201, 42):
            data = narration(); data['ccsd']['scenes'][0]['audio']['dialogue'][0]['text'] = text
            with self.assertRaises(ValueError): voice.prepare_narration(data)

    def test_voice_export_real_pcm(self):
        result = voice.validate_export(self.voice_export())
        self.assertEqual(result['candidate']['duration_seconds'], 1)
        self.assertEqual(result['candidate']['state'], 'TECHNICAL_CANDIDATE_REQUIRES_REVIEW')
        self.assertFalse(result['commercial_rights_verified'])
        self.assertFalse(result['production_ready'])
        self.assertFalse(result['candidate']['watermark_independently_verified'])

    def test_silent_clipped_wrong_rate_and_long_audio_rejected(self):
        for raw in (wav(silent=True), wav(clipped=True), wav(rate=16000), wav(seconds=4)):
            with self.assertRaises(ValueError): voice.validate_export(self.voice_export(raw))

    def test_truncated_wave_rejected(self):
        with self.assertRaises(ValueError): voice.validate_export(self.voice_export(wav()[:-100]))

    def test_generation_mismatches_rejected(self):
        for field, value in (('voice', 'expr-voice-3-f'), ('text_sha256', '0' * 64),
            ('output_sha256', '0' * 64), ('model_revision', 'other'),
            ('upstream_revision', voice.REVIEWED_DOWNLOAD_REVISION), ('synthetic', False),
            ('speed', True), ('engine', 'omnivoice')):
            with self.subTest(field=field):
                data = self.voice_export(); record = read_json(data['generation']); record[field] = value
                self.file('generation.json', record)
                with self.assertRaises(ValueError): voice.validate_export(data)

    def test_model_file_provenance_must_match_existing_review(self):
        data = self.voice_export(); record = read_json(data['generation'])
        record['model_files_sha256'] = {}
        self.file('generation.json', record)
        with self.assertRaises(ValueError): voice.validate_export(data)

    def test_prepared_request_passes_existing_runner_validation(self):
        # Import only CYZOR's reviewed request validator, never upstream/model code.
        import importlib.util
        package = Path(__file__).parent / 'voicestudio'
        with patch.object(__import__('sys'), 'path', [str(package), *__import__('sys').path]):
            spec = importlib.util.spec_from_file_location('existing_voice_runner', package / 'runner.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        request = voice.prepare_narration(narration())['request']
        self.assertEqual(module.validate_request(request), (request['text'], request['voice'], request['speed']))

    def test_export_text_bound_to_ccsd(self):
        data = self.voice_export()
        data['preparation']['ccsd']['scenes'][0]['audio']['dialogue'][0]['text'] = 'Changed script.'
        with self.assertRaises(ValueError): voice.validate_export(data)

    def test_video_prepare_actual_plane_shape(self):
        data = generation(); before = copy.deepcopy(data)
        result = video.prepare_generation(data)
        self.assertEqual(result['handoff']['plane'], {'model': 'kling-3-turbo',
            'prompt': {'text': data['prompt']}, 'media': {},
            'settings': {'aspectRatio': '9:16', 'resolution': '720p', 'duration': 5}})
        self.assertEqual(data, before)
        self.assertEqual(result['provider_calls'], 0)

    def test_image_prepare_one_result(self):
        data = generation(); data['model'] = 'soul-2'
        result = video.prepare_generation(data)
        self.assertEqual(result['media_kind'], 'image')
        self.assertEqual(result['handoff']['plane']['settings']['batchSize'], '1')

    def test_unknown_models_and_paths_rejected(self):
        for model in ('unknown', '../soul-2', [], True):
            data = generation(); data['model'] = model
            with self.assertRaises(ValueError): video.prepare_generation(data)

    def test_generation_setting_matrix(self):
        for settings in ({'duration': True}, {'duration': 20}, {'duration': float('nan')},
            {'resolution': '4k'}, {'aspectRatio': 'wrong'}, {'endpoint': 'https://example.com'}, []):
            data = generation(); data['settings'] = settings
            with self.assertRaises(ValueError): video.prepare_generation(data)

    def test_image_batches_and_prompt_rewriting_rejected(self):
        for settings in ({'batchSize': '4'}, {'batchSize': 1}, {'enhancePrompt': True}, {'duration': 5}):
            data = generation(); data.update(model='soul-2', settings=settings)
            with self.assertRaises(ValueError): video.prepare_generation(data)

    def test_credentials_and_media_never_accepted(self):
        for field in ('api_key', 'key', 'credentials', 'media', 'url', 'upload'):
            data = generation(); data[field] = 'must-not-be-transmitted'
            with self.assertRaises(ValueError): video.prepare_generation(data)

    def test_unsafe_project_and_scene_ids_rejected(self):
        for field in ('scene_id', 'project_id'):
            for invalid in ('../etc', 'a/b', '', 'x' * 101, None):
                data = generation(); data[field] = invalid
                with self.assertRaises(ValueError): video.prepare_generation(data)

    def test_export_intake_never_claims_decode(self):
        result = video.validate_export(self.video_export())
        self.assertEqual(result['candidate']['state'], 'PENDING_MEDIA_DECODE_AND_REVIEW')
        self.assertFalse(result['candidate']['full_decode_verified'])
        self.assertFalse(result['candidate']['source_generation_verified'])
        self.assertFalse(result['commercial_rights_verified'])

    def test_export_different_request_rejected(self):
        data = self.video_export(); data['preparation']['prompt'] = 'Another prompt.'
        with self.assertRaises(ValueError): video.validate_export(data)

    def test_export_tampered_file_rejected(self):
        data = self.video_export(); self.file('export.mp4', b'tampered')
        with self.assertRaises(ValueError): video.validate_export(data)

    def test_export_invalid_mime_and_signature_rejected(self):
        data = self.video_export(); data['export']['media_type'] = 'image/png'
        with self.assertRaises(ValueError): video.validate_export(data)
        data = self.video_export(); raw = b'not video'; self.file('export.mp4', raw)
        data['export']['sha256'] = digest(raw)
        with self.assertRaises(ValueError): video.validate_export(data)

    def test_status_never_implies_runtime_available(self):
        for adapter, tool in ((voice, 'voicestudio'), (video, 'open-higgsfield')):
            result = adapter.dispatch({**FLAGS, 'tool': tool, 'operation': 'status'})
            self.assertEqual(result['status'], 'PASS')
            self.assertFalse(result['production_ready'])
            self.assertEqual(result['provider_calls'], 0)
            self.assertIn('blockers', result)

    def test_flags_must_be_literal_false(self):
        for adapter, data in ((voice.prepare_narration, narration), (video.prepare_generation, generation)):
            for key in FLAGS:
                for value in (None, 0, '', True, 'false'):
                    request = data(); request[key] = value
                    with self.assertRaises(ValueError): adapter(request)

    def test_unknown_operation_and_tool_rejected(self):
        for adapter, tool in ((voice, 'voicestudio'), (video, 'open-higgsfield')):
            for job in ({'tool': tool, 'operation': 'generate'}, {'tool': 'bad', 'operation': 'status'}):
                with self.assertRaises(ValueError): adapter.dispatch({**FLAGS, **job})

    def test_dispatch_reads_input_and_keeps_network_idle(self):
        with patch('socket.socket', side_effect=AssertionError('No network allowed')):
            for adapter, tool, op, data in ((voice, 'voicestudio', 'prepare-narration', narration()),
                (video, 'open-higgsfield', 'prepare-generation', generation())):
                result = adapter.dispatch({**FLAGS, 'tool': tool, 'operation': op,
                    'input': self.file('request.json', data)})
                self.assertEqual(result['status'], 'PASS')

    def test_symlink_and_directory_input_rejected(self):
        source = Path(self.file('input.json', generation())); link = self.root / 'link.json'; link.symlink_to(source)
        for path in (link, self.root):
            with self.assertRaises(ValueError): read_json(path)

    def test_parent_symlink_rejected(self):
        source = self.root / 'source'; source.mkdir(); (source / 'input.json').write_text('{}')
        linked = self.root / 'linked'; linked.symlink_to(source, target_is_directory=True)
        with self.assertRaises(ValueError): read_json(linked / 'input.json')

    def alias_parent_path(self, filename, checked_bytes, other_bytes):
        # abspath(a/link/../asset) resolves to a/asset, while the operating
        # system follows link -> b/sub then .. to b/asset. Never accept it.
        first, second = self.root / 'a', self.root / 'b'
        first.mkdir(); (second / 'sub').mkdir(parents=True)
        (first / 'link').symlink_to(second / 'sub', target_is_directory=True)
        (first / filename).write_bytes(checked_bytes)
        (second / filename).write_bytes(other_bytes)
        return str(first / 'link' / '..' / filename)

    def test_raw_parent_traversal_rejected_before_normalization(self):
        unsafe = self.alias_parent_path('asset', b'checked', b'other')
        self.assertEqual(Path(unsafe).read_bytes(), b'other')
        with self.assertRaisesRegex(ValueError, 'Parent traversal'):
            read_bytes(unsafe, 100)
        with self.assertRaisesRegex(ValueError, 'Parent traversal'):
            read_bytes(self.root / 'a' / '..' / 'a' / 'asset', 100)

    def test_voice_candidate_rejects_symlink_parent_alias(self):
        data = self.voice_export()
        data['audio'] = self.alias_parent_path('voice.wav', Path(data['audio']).read_bytes(), wav(silent=True))
        with self.assertRaisesRegex(ValueError, 'Parent traversal'):
            voice.validate_export(data)

    def test_video_candidate_rejects_symlink_parent_alias(self):
        data = self.video_export()
        data['export']['path'] = self.alias_parent_path('video.mp4',
            Path(data['export']['path']).read_bytes(), b'other bytes')
        with self.assertRaisesRegex(ValueError, 'Parent traversal'):
            video.validate_export(data)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO check')
    def test_fifo_rejected_without_blocking(self):
        fifo = self.root / 'fifo'; os.mkfifo(fifo)
        with self.assertRaises(ValueError): read_bytes(fifo, 1024)

    def test_empty_oversize_and_nonfinite_json_rejected(self):
        for raw, limit in ((b'', 4), (b'12345', 4)):
            with self.assertRaises(ValueError): read_bytes(self.file('raw', raw), limit)
        with self.assertRaises(ValueError): read_json(self.file('bad.json', b'{"x":NaN}'))


if __name__ == '__main__':
    unittest.main()
