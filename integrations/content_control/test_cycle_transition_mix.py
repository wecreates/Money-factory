import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave

from integrations.content_control import cycle_transition_mix as mix


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'Media tools unavailable')
class TransitionMixTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.render = self.root / 'render'
        self.render.mkdir()
        subprocess.run([
            'ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
            'color=c=#333333:s=320x180:r=24:d=4', '-f', 'lavfi', '-i',
            'anullsrc=r=24000:cl=mono:d=4', '-c:v', 'libx264', '-pix_fmt',
            'yuv420p', '-c:a', 'aac', '-ar', '24000', '-ac', '1',
            str(self.render / 'video.mp4')], check=True)
        rows = []
        clips = []
        speakers = ('dave', 'points_monk')
        for index, speaker in enumerate(speakers):
            wav = self.render / f'voice-{index:02d}.wav'
            frames = round(1.72 * mix.RATE)
            samples = [round(.05 * 32767 * math.sin(2 * math.pi * 440 * i / mix.RATE))
                       for i in range(frames)]
            with wave.open(str(wav), 'wb') as output:
                output.setnchannels(1); output.setsampwidth(2)
                output.setframerate(mix.RATE)
                output.writeframes(struct.pack('<' + 'h' * len(samples), *samples))
            scene_id = f'scene-{index + 1}'
            rows.append({'scene_id': scene_id, 'start': index * 2.0,
                         'end': (index + 1) * 2.0,
                         'narration_end': index * 2.0 + 1.72})
            clips.append({'scene_id': scene_id, 'speaker': speaker,
                          'voice_id': mix.VOICE_ASSIGNMENTS[speaker],
                          'file': wav.name, 'audio_sha256': sha(wav)})
        write(self.render / 'timeline.json', {'publication_enabled': False,
              'duration_seconds': 4.0, 'scenes': rows})
        write(self.render / 'voice.json', {
            'status': 'GENERATED_PENDING_LISTENING_REVIEW', 'clips': clips,
            'voice_assignments': mix.VOICE_ASSIGNMENTS,
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_approved': False, 'full_av_review': False})
        write(self.render / 'render.json', {
            'status': 'AWAITING_REVIEW', 'technical_status': 'PASS',
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_approved': False, 'full_av_review': False,
            'candidate_sha256': sha(self.render / 'video.mp4'),
            'timeline_sha256': sha(self.render / 'timeline.json'),
            'voice_receipt_sha256': sha(self.render / 'voice.json')})

    def tearDown(self):
        self.temporary.cleanup()

    def run_mix(self, name='mix'):
        return mix.create_transition_mix(self.render, self.root / name)

    def test_creates_bound_unpublished_mix_without_mutating_source(self):
        source_before = sha(self.render / 'video.mp4')
        result = self.run_mix()
        self.assertEqual(result['technical_status'], 'PASS')
        self.assertEqual(result['status'], 'AWAITING_LISTENING_REVIEW')
        for field in ('publication_enabled', 'paid_generation_enabled',
                      'production_approved', 'full_av_review',
                      'production_ready', 'listening_verified'):
            self.assertIs(result[field], False)
        self.assertEqual(source_before, sha(self.render / 'video.mp4'))
        self.assertEqual(result['source_candidate_sha256'], source_before)
        self.assertEqual(len(result['cue_placements']), 1)
        self.assertGreater(result['cue_placements'][0]['mixed_rms'],
                           result['cue_placements'][0]['source_rms'] + .002)
        self.assertEqual([item['voice_id'] for item in result['preserved_voice_assets']],
                         ['am_fenrir', 'am_michael'])
        self.assertEqual(result['candidate_sha256'], sha(self.root / 'mix/video.mp4'))
        self.assertEqual(result['cue_asset']['sha256'],
                         sha(self.root / 'mix/transition-cue.wav'))
        self.assertEqual(result['stem_asset']['sha256'],
                         sha(self.root / 'mix/transition-stem.wav'))
        self.assertEqual(result['encoded_picture_stream_sha256'],
                         mix.encoded_stream_sha256(self.render / 'video.mp4', '0:v:0'))
        self.assertLessEqual(result['mixed_decoded_audio']['peak'], 1)
        self.assertGreater(result['mixed_decoded_audio']['rms'], 0)

    def test_rejects_forged_source_approval_or_paid_flags(self):
        for field in ('publication_enabled', 'paid_generation_enabled',
                      'production_approved', 'full_av_review'):
            with self.subTest(field=field):
                rendered = json.loads((self.render / 'render.json').read_text())
                rendered[field] = True
                write(self.render / 'render.json', rendered)
                with self.assertRaisesRegex(ValueError, 'unpublished renderer'):
                    mix.create_transition_mix(self.render, self.root / ('bad-' + field))
                rendered[field] = False
                write(self.render / 'render.json', rendered)

    def test_rejects_voice_asset_or_assignment_change(self):
        original = (self.render / 'voice-00.wav').read_bytes()
        (self.render / 'voice-00.wav').write_bytes(original + b'x')
        with self.assertRaisesRegex(ValueError, 'voice asset binding'):
            self.run_mix('mutated')
        (self.render / 'voice-00.wav').write_bytes(original)
        voice = json.loads((self.render / 'voice.json').read_text())
        voice['clips'][0]['voice_id'] = 'am_changed'
        write(self.render / 'voice.json', voice)
        rendered = json.loads((self.render / 'render.json').read_text())
        rendered['voice_receipt_sha256'] = sha(self.render / 'voice.json')
        write(self.render / 'render.json', rendered)
        with self.assertRaisesRegex(ValueError, 'voice asset binding'):
            self.run_mix('reassigned')

    def test_rejects_transition_that_would_overlap_narration(self):
        timeline = json.loads((self.render / 'timeline.json').read_text())
        timeline['scenes'][0]['narration_end'] = 1.80
        write(self.render / 'timeline.json', timeline)
        rendered = json.loads((self.render / 'render.json').read_text())
        rendered['timeline_sha256'] = sha(self.render / 'timeline.json')
        write(self.render / 'render.json', rendered)
        with self.assertRaisesRegex(ValueError, 'post-narration tail'):
            self.run_mix('overlap')

    def test_rejects_existing_output_and_symlinked_evidence(self):
        existing = self.root / 'existing'; existing.mkdir()
        with self.assertRaisesRegex(ValueError, 'must not already exist'):
            mix.create_transition_mix(self.render, existing)
        real = self.render / 'voice-00.wav'
        saved = real.read_bytes(); real.unlink(); real.symlink_to(self.root / 'voice-real.wav')
        (self.root / 'voice-real.wav').write_bytes(saved)
        with self.assertRaisesRegex(ValueError, 'voice asset binding'):
            self.run_mix('symlink')

    def test_output_is_deterministic_for_same_bound_source(self):
        first = self.run_mix('first')
        second = self.run_mix('second')
        self.assertEqual(first['cue_asset']['sha256'], second['cue_asset']['sha256'])
        self.assertEqual(first['stem_asset']['sha256'], second['stem_asset']['sha256'])
        self.assertEqual(first['cue_placements'], second['cue_placements'])


if __name__ == '__main__':
    unittest.main()
