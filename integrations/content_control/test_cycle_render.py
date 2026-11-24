import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from integrations.content_control import cycle_render as render


def brief():
    return {'publication_enabled':False,'paid_generation_enabled':False,'production_approved':False,'full_av_review':False,'title':'Real cost',
            'scenes':[{'id':'s1','narration':'A credit is not free money.','visual':'Dave examines a receipt.',
                       'speaker':'dave','visual_spec':{'kind':'receipt','headline':'Check the math',
                                                     'values':['$80 - $20','$60']}}]}


def normalized_voice_fixture(root, scene=None, *, channels=1, sample_width=2):
    """Write a normalized fixture plus its child receipt for parent validation."""
    root = Path(root)
    scene = scene or brief()['scenes'][0]
    source = [.04, -.04] * 240
    normalized, evidence = render.normalize_voice_samples(source)
    wav = root / 'voice-00.wav'
    with wave.open(str(wav), 'wb') as stream:
        stream.setparams((channels, sample_width, 24000, 0, 'NONE', 'not compressed'))
        if sample_width == 2:
            payload = [round(value * 32767) for value in normalized]
            if channels == 2:
                payload = [value for sample in payload for value in (sample, sample)]
            stream.writeframes(struct.pack('<' + 'h' * len(payload), *payload))
        else:
            payload = [max(0, min(255, round(value * 127 + 128))) for value in normalized]
            if channels == 2:
                payload = [value for sample in payload for value in (sample, sample)]
            stream.writeframes(bytes(payload))
    if channels == 1 and sample_width == 2:
        actual = render.wave_pcm_stats(wav)
        evidence.update(output_rms=actual['rms'], output_peak=actual['peak'])
        rms = actual['rms']
    else:
        rms = evidence['output_rms']
    speaker = scene.get('speaker', 'narrator')
    clip = {'scene_id': scene['id'], 'speaker': speaker,
            'voice_id': render.VOICE_ASSIGNMENTS[speaker], 'file': wav.name,
            'audio_sha256': render.digest(wav),
            'text_sha256': hashlib.sha256(scene['narration'].encode()).hexdigest(),
            'duration_seconds': len(normalized) / 24000,
            'rms': rms, 'level_normalization': evidence}
    return wav, clip


def voice_receipt(clips):
    return {'status': 'GENERATED_PENDING_LISTENING_REVIEW',
            'voice_assignments': render.VOICE_ASSIGNMENTS,
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_approved': False, 'full_av_review': False,
            'clips': clips}


class RenderValidationTests(unittest.TestCase):
    def test_voice_level_normalization_matches_target_and_retains_listening_gate(self):
        normalized, evidence = render.normalize_voice_samples([.1, -.1, .1, -.1])
        self.assertTrue(all(math.isclose(abs(value), .075) for value in normalized))
        self.assertTrue(math.isclose(evidence['source_rms'], .1))
        self.assertTrue(math.isclose(evidence['output_rms'], render.VOICE_TARGET_RMS))
        self.assertTrue(math.isclose(evidence['applied_gain'], .75))
        self.assertLessEqual(evidence['output_peak'], render.VOICE_MAX_PEAK)
        self.assertFalse(evidence['listening_verified'])
        self.assertIn('direct full-mix listening', evidence['scope'])

    def test_voice_level_normalization_bounds_boost_and_peak(self):
        monk_level, monk_evidence = render.normalize_voice_samples([.04, -.04])
        self.assertTrue(math.isclose(monk_evidence['applied_gain'], 1.875))
        self.assertTrue(math.isclose(monk_evidence['output_rms'], render.VOICE_TARGET_RMS))
        self.assertTrue(all(math.isclose(abs(value), render.VOICE_TARGET_RMS)
                            for value in monk_level))

        quiet, quiet_evidence = render.normalize_voice_samples([.03, -.03])
        self.assertTrue(math.isclose(quiet_evidence['applied_gain'], render.VOICE_MAX_GAIN))
        self.assertTrue(math.isclose(quiet_evidence['output_rms'], .057))
        self.assertTrue(all(math.isclose(abs(value), .057) for value in quiet))

        peaked, peak_evidence = render.normalize_voice_samples([.9] + [0] * 323)
        self.assertTrue(math.isclose(peak_evidence['source_rms'], .05))
        self.assertTrue(math.isclose(peak_evidence['applied_gain'], render.VOICE_MAX_PEAK / .9))
        self.assertTrue(math.isclose(peak_evidence['output_peak'], render.VOICE_MAX_PEAK))
        self.assertLess(peak_evidence['output_rms'], render.VOICE_TARGET_RMS)

    def test_voice_level_normalization_rejects_invalid_or_silent_samples(self):
        for samples in ([], [0, 0], [float('nan')], [1.01]):
            with self.assertRaises(ValueError):
                render.normalize_voice_samples(samples)
        for kwargs in ({'target_rms': 0}, {'peak_ceiling': 1.01}, {'max_gain': .9}):
            with self.assertRaises(ValueError):
                render.normalize_voice_samples([.1], **kwargs)

    def test_synthesis_receipt_binds_bounded_level_normalization(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            voice_root = root / 'voice-root'
            generator = voice_root / 'scripts' / 'v2_free_voice.py'
            generator.parent.mkdir(parents=True)
            generator.write_text('# immutable fixture\n')
            output = root / 'out'
            output.mkdir()

            fake_torch = SimpleNamespace(set_num_threads=lambda value: None,
                                         set_num_interop_threads=lambda value: None)
            fake_module = SimpleNamespace(
                VOICE_ASSIGNMENTS=render.VOICE_ASSIGNMENTS,
                local_synthesizer=lambda: (lambda text, voice, speed: ([.04, -.04] * 240, 24000)),
                model_identity=lambda: {'model_revision': 'fixture-model'},
            )
            fake_spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None))
            with patch.dict(sys.modules, {'torch': fake_torch}), \
                    patch.object(render.importlib.util, 'spec_from_file_location', return_value=fake_spec), \
                    patch.object(render.importlib.util, 'module_from_spec', return_value=fake_module):
                render.synthesize(brief(), output, voice_root)

            receipt = json.loads((output / 'voice.json').read_text())
            clip = receipt['clips'][0]
            self.assertEqual(clip['speaker'], 'dave')
            self.assertEqual(clip['voice_id'], render.VOICE_ASSIGNMENTS['dave'])
            self.assertTrue(math.isclose(clip['rms'], render.VOICE_TARGET_RMS,
                                         abs_tol=render.PCM_QUANTIZATION_TOLERANCE))
            self.assertTrue(math.isclose(clip['level_normalization']['applied_gain'], 1.875))
            self.assertEqual(clip['level_normalization']['algorithm'],
                             render.VOICE_LEVEL_ALGORITHM)
            self.assertFalse(clip['level_normalization']['listening_verified'])
            self.assertEqual(clip['audio_sha256'], render.digest(output / clip['file']))
            stats = render.wave_pcm_stats(output / clip['file'])
            self.assertEqual(clip['rms'], stats['rms'])
            self.assertEqual(clip['level_normalization']['output_peak'], stats['peak'])

    def test_parent_rejects_forged_voice_normalization_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, clip = normalized_voice_fixture(root)
            self.assertEqual(render.measured_clip_frames(
                brief()['scenes'], voice_receipt([clip]), root), [8])
            for field, value in (('algorithm', 'forged'), ('output_rms', .2),
                                 ('listening_verified', True), ('target_rms', .1)):
                forged = copy.deepcopy(clip)
                forged['level_normalization'][field] = value
                with self.assertRaisesRegex(ValueError, 'normalization'):
                    render.measured_clip_frames(
                        brief()['scenes'], voice_receipt([forged]), root)
            forged = copy.deepcopy(clip)
            forged['rms'] = .2
            with self.assertRaisesRegex(ValueError, 'bound WAV'):
                render.measured_clip_frames(
                    brief()['scenes'], voice_receipt([forged]), root)

    def test_parent_rejects_invalid_voice_wav_format(self):
        for channels, sample_width in ((2, 2), (1, 1)):
            with self.subTest(channels=channels, sample_width=sample_width), \
                    tempfile.TemporaryDirectory() as td:
                root = Path(td)
                _, clip = normalized_voice_fixture(root, channels=channels,
                                                   sample_width=sample_width)
                with self.assertRaisesRegex(ValueError, 'mono 16-bit 24kHz'):
                    render.measured_clip_frames(
                        brief()['scenes'], voice_receipt([clip]), root)

    def test_parent_rejects_inconsistent_voice_gain_math(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, clip = normalized_voice_fixture(root)
            forged = copy.deepcopy(clip)
            forged['level_normalization']['source_rms'] = .05
            forged['level_normalization']['source_peak'] = .06
            with self.assertRaisesRegex(ValueError, 'gain is inconsistent'):
                render.measured_clip_frames(
                    brief()['scenes'], voice_receipt([forged]), root)

    def test_parent_replays_legacy_gain_receipt_but_rejects_mixed_versions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = [.04, -.04] * 240
            normalized, evidence = render.normalize_voice_samples(
                source, max_gain=render.VOICE_LEGACY_MAX_GAIN)
            evidence['algorithm'] = render.VOICE_LEGACY_LEVEL_ALGORITHM
            wav = root / 'voice-00.wav'
            with wave.open(str(wav), 'wb') as stream:
                stream.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                stream.writeframes(struct.pack(
                    '<' + 'h' * len(normalized),
                    *[round(value * 32767) for value in normalized]))
            actual = render.wave_pcm_stats(wav)
            evidence.update(output_rms=actual['rms'], output_peak=actual['peak'])
            scene = brief()['scenes'][0]
            clip = {'scene_id': scene['id'], 'speaker': 'dave',
                    'voice_id': render.VOICE_ASSIGNMENTS['dave'], 'file': wav.name,
                    'audio_sha256': render.digest(wav),
                    'text_sha256': hashlib.sha256(scene['narration'].encode()).hexdigest(),
                    'duration_seconds': actual['duration_seconds'], 'rms': actual['rms'],
                    'level_normalization': evidence}
            self.assertEqual(render.measured_clip_frames(
                [scene], voice_receipt([clip]), root), [8])

            forged = copy.deepcopy(clip)
            forged['level_normalization']['maximum_gain'] = render.VOICE_MAX_GAIN
            with self.assertRaisesRegex(ValueError, 'algorithm or scope changed'):
                render.measured_clip_frames([scene], voice_receipt([forged]), root)

    def test_parent_rejects_internally_consistent_subthreshold_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wav = root / 'voice-00.wav'
            samples = [29, -29] * 240
            with wave.open(str(wav), 'wb') as stream:
                stream.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                stream.writeframes(struct.pack('<' + 'h' * len(samples), *samples))
            actual = render.wave_pcm_stats(wav)
            source = actual['rms'] / render.VOICE_MAX_GAIN
            scene = brief()['scenes'][0]
            normalization = {'algorithm': render.VOICE_LEVEL_ALGORITHM,
                'target_rms': render.VOICE_TARGET_RMS,
                'peak_ceiling': render.VOICE_MAX_PEAK,
                'maximum_gain': render.VOICE_MAX_GAIN,
                'source_rms': source, 'source_peak': source,
                'applied_gain': render.VOICE_MAX_GAIN,
                'output_rms': actual['rms'], 'output_peak': actual['peak'],
                'listening_verified': False, 'scope': render.VOICE_LEVEL_SCOPE}
            clip = {'scene_id': scene['id'], 'speaker': 'dave',
                    'voice_id': render.VOICE_ASSIGNMENTS['dave'], 'file': wav.name,
                    'audio_sha256': render.digest(wav),
                    'text_sha256': hashlib.sha256(scene['narration'].encode()).hexdigest(),
                    'duration_seconds': actual['duration_seconds'], 'rms': actual['rms'],
                    'level_normalization': normalization}
            with self.assertRaisesRegex(ValueError, 'accepted domain'):
                render.measured_clip_frames(
                    [scene], voice_receipt([clip]), root)

    def test_parent_binds_scene_speaker_voice_and_indexed_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, clip = normalized_voice_fixture(root)
            for field, value in (('scene_id', 'wrong'), ('speaker', 'narrator'),
                                 ('voice_id', 'am_adam'), ('file', 'wrong.wav')):
                forged = copy.deepcopy(clip)
                forged[field] = value
                with self.subTest(field=field), self.assertRaisesRegex(
                        ValueError, 'Narration binding mismatch'):
                    render.measured_clip_frames(
                        brief()['scenes'], voice_receipt([forged]), root)

    def test_parent_requires_pending_listening_top_level_voice_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, clip = normalized_voice_fixture(root)
            valid = voice_receipt([clip])
            cases = [('status', 'PASS'), ('voice_assignments', {'dave': 'wrong'}),
                     ('publication_enabled', True), ('paid_generation_enabled', True),
                     ('production_approved', True), ('full_av_review', True)]
            for field, value in cases:
                forged = copy.deepcopy(valid)
                forged[field] = value
                with self.subTest(field=field), self.assertRaisesRegex(
                        ValueError, 'pending-listening voice receipt'):
                    render.measured_clip_frames(brief()['scenes'], forged, root)

    def test_no_publication_or_paid_modes(self):
        for key in ['publication_enabled','paid_generation_enabled']:
            data=brief();data[key]=True
            with self.assertRaises(ValueError):render.validate(data)

    def test_unique_scene_ids_and_voice_assignments(self):
        data=brief();data['scenes']*=2
        with self.assertRaises(ValueError):render.validate(data)
        data=brief();data['scenes'][0]['speaker']='cloned_person'
        with self.assertRaises(ValueError):render.validate(data)

    def test_oversized_and_invalid_visual_data_rejected(self):
        for field,value in [('kind','arbitrary_code'),('labels',['a']*5),('values',['a'*31]),('headline','x'*61)]:
            data=brief();data['scenes'][0]['visual_spec'][field]=value
            with self.assertRaises(ValueError):render.validate(data)

    def test_editorial_digest_is_stable_and_binds_all_fields(self):
        data=brief();original=render.editorial_digest(data)
        self.assertEqual(original,render.editorial_digest(dict(reversed(list(data.items())))))
        data['scenes'][0]['narration']='Different script.'
        self.assertNotEqual(original,render.editorial_digest(data))

    def test_timestamp_rounding(self):
        self.assertEqual(render.timestamp(59.9996),'00:01:00.000')

    def test_fresh_output_does_not_overwrite_existing(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileExistsError):
                render.render_cycle(brief(),td,voice_python=sys.executable,voice_root=td)

    def test_invalid_timeout_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as td:
            for timeout in (True,float('nan'),0,1801):
                with self.assertRaises(ValueError):
                    render.render_cycle(brief(),Path(td)/'new',voice_python=sys.executable,voice_root=td,timeout=timeout)
                self.assertFalse((Path(td)/'new').exists())

    def test_subprocess_failure_retains_blocked_receipt(self):
        with tempfile.TemporaryDirectory() as td,patch.object(render,'run',side_effect=RuntimeError('fixture failure')):
            out=Path(td)/'run';result=render.render_cycle(brief(),out,voice_python=sys.executable,voice_root=td)
            self.assertEqual(result['status'],'BLOCKED');self.assertNotIn('candidate_sha256',result)
            self.assertFalse(json.loads((out/'render.json').read_text())['production_approved'])

    def test_transcription_rejects_changed_number_and_negation(self):
        normalize=lambda x:x.lower()
        self.assertTrue(render.compare_transcription('Pay sixty dollars now','Pay sixty dollars now',normalize)['passed'])
        self.assertFalse(render.compare_transcription('Pay sixty dollars now','Pay seventy dollars now',normalize)['passed'])
        self.assertFalse(render.compare_transcription('Do not pay sixty dollars','Do pay sixty dollars',normalize)['passed'])
        self.assertFalse(render.compare_transcription(' '.join(['word']*100)+' not',' '.join(['word']*100),normalize)['passed'])

    def test_transcription_rejects_swapped_amounts_in_long_matching_script(self):
        normalize=lambda x:x.lower()
        prefix=' '.join(['matching context']*50)
        expected=prefix+' fee ten dollars reward twenty dollars'
        swapped=prefix+' fee twenty dollars reward ten dollars'
        result=render.compare_transcription(expected,swapped,normalize)
        self.assertGreater(result['ordered_word_similarity'],.96)
        self.assertFalse(result['critical_numeric_and_negation_tokens_match'])
        self.assertFalse(result['passed'])
        expected=prefix+' fee 10 dollars reward 20 dollars'
        swapped=prefix+' fee 20 dollars reward 10 dollars'
        self.assertFalse(render.compare_transcription(expected,swapped,normalize)['passed'])

    def test_observed_captions_use_recognized_words_and_timing(self):
        words=[{'word':'Hello','start':.2,'end':.5},{'word':'<world>','start':.6,'end':.9}]
        vtt=render.observed_captions(words,1)
        self.assertIn('00:00:00.200 --> 00:00:00.900',vtt)
        self.assertIn('Hello &lt;world&gt;',vtt)
        words[1]['start']=.1
        with self.assertRaises(ValueError):render.observed_captions(words,1)

    def test_caption_display_rejoins_only_source_adjacent_compounds(self):
        words=[{'word':'three','start':0,'end':.2,'probability':.9},
               {'word':'-year','start':.2,'end':.4,'probability':.8},
               {'word':'and','start':.4,'end':.6,'probability':.9},
               {'word':'non','start':.6,'end':.8,'probability':.9},
               {'word':'-negotiable.','start':.8,'end':1.0,'probability':.8}]
        original=[dict(word) for word in words]
        display,joins=render.caption_display_words(
            words,'three-year and non-negotiable.')
        self.assertEqual([word['word'] for word in display],
                         ['three-year','and','non-negotiable.'])
        self.assertEqual((display[0]['start'],display[0]['end']),(0,.4))
        self.assertEqual([join['display'] for join in joins],
                         ['three-year','non-negotiable.'])
        self.assertEqual(words,original)
        self.assertIn('three-year and non-negotiable.',
                      render.observed_captions(display,1))
        capped=[{'word':word,'start':index*.1,'end':(index+1)*.1}
                for index,word in enumerate(
                    ['When','your','statement','shows','the','full','three','-year','comparison.'])]
        capped_display,_=render.caption_display_words(
            capped,'When your statement shows the full three-year comparison.')
        cues=render.observed_captions(capped_display,1).strip().split('\n\n')[1:]
        self.assertEqual([cue.splitlines()[1] for cue in cues],
                         ['When your statement shows the full','three-year comparison.'])
        self.assertNotIn('\n-year',render.observed_captions(capped_display,1))
        joined=[{'word':'three-year','start':0,'end':.4}]
        self.assertEqual(render.caption_display_words(joined,'three-year'),(joined,[]))

    def test_caption_display_does_not_invent_hyphen_compounds(self):
        words=[{'word':'three','start':0,'end':.2},
               {'word':'-year','start':.2,'end':.4},
               {'word':'cost','start':.4,'end':.6},
               {'word':'-10','start':.6,'end':.8}]
        for text in ('three -year cost-10','three year cost-10','unrelated'):
            with self.subTest(text=text):
                display,joins=render.caption_display_words(words,text)
                self.assertEqual([word['word'] for word in display],
                                 ['three','-year','cost','-10'])
                self.assertEqual(joins,[])
        delayed=[dict(word) for word in words]
        delayed[1]['start']=.23
        self.assertEqual(render.caption_display_words(
            delayed,'three-year cost-10')[1],[])
        self.assertEqual(render.caption_display_words(
            words,'three-year cost-10',scene_boundaries=(.3,))[1],[])
        multiword=[{'word':'two or three','start':0,'end':.3},
                   {'word':'-year','start':.3,'end':.5}]
        self.assertEqual(render.caption_display_words(
            multiword,'two or three-year'),(multiword,[]))
        multiword=[{'word':'three','start':0,'end':.3},
                   {'word':'-year comparison','start':.3,'end':.5}]
        self.assertEqual(render.caption_display_words(
            multiword,'three-year comparison'),(multiword,[]))
        contained=[{'word':'three','start':.05,'end':.12},
                   {'word':'-year','start':.102,'end':.108},
                   {'word':'comparison','start':.09,'end':.15}]
        self.assertEqual(render.caption_display_words(
            contained,'three-year comparison'),(contained,[]))
        with self.assertRaisesRegex(ValueError,'Recognized caption text'):
            render.caption_display_words(words,None)

    def test_caption_groups_break_sentences_and_preserve_timestamps(self):
        words=[{'word':w,'start':i*.2,'end':(i+1)*.2}
               for i,w in enumerate(['Interest','disappears.', 'Paying','more','helps!', 'Really?”', 'Yes.'])]
        cues=render.observed_captions(words,2).strip().split('\n\n')[1:]
        self.assertEqual([c.splitlines()[1] for c in cues],
                         ['Interest disappears.', 'Paying more helps!', 'Really?”', 'Yes.'])
        self.assertTrue(cues[1].startswith('00:00:00.400 --> 00:00:01.000'))

    def test_caption_groups_keep_decimals_and_common_abbreviations(self):
        words=[{'word':w,'start':i*.2,'end':(i+1)*.2}
               for i,w in enumerate(['Dr.', 'A.', 'Smith', 'paid', '$3.14', 'in', 'U.S.', 'fees.'])]
        cues=render.observed_captions(words,2).strip().split('\n\n')[1:]
        self.assertEqual([c.splitlines()[1] for c in cues],
                         ['Dr. A. Smith paid $3.14 in', 'U.S. fees.'])
        self.assertTrue(render._caption_sentence_end('$3.14.'))

    def test_caption_tail_rebalancing_preserves_scene_boundary(self):
        words = [{'word': str(i), 'start': i / 4, 'end': (i + 1) / 4} for i in range(8)]
        self.assertIn('00:00:01.500 --> 00:00:02.000\n6 7',
                      render.observed_captions(words, 2))
        self.assertIn('00:00:01.750 --> 00:00:02.000\n7',
                      render.observed_captions(words, 2, scene_boundaries=(1.75,)))

    def test_caption_groups_break_at_half_second_pause(self):
        words=[{'word':'before','start':0,'end':.5},
               {'word':'after','start':1,'end':1.4}]
        cues=render.observed_captions(words,2).strip().split('\n\n')[1:]
        self.assertEqual(len(cues),2)
        self.assertIn('00:00:00.000 --> 00:00:00.500\nbefore',cues[0])
        self.assertIn('00:00:01.000 --> 00:00:01.400\nafter',cues[1])
        words[1]['start']=.99
        self.assertEqual(len(render.observed_captions(words,2).strip().split('\n\n')[1:]),1)

    def test_caption_zero_duration_tokens_do_not_get_invented_time(self):
        words=[{'word':'Oh!','start':0,'end':0},{'word':'Hello.','start':0,'end':.5}]
        self.assertIn('00:00:00.000 --> 00:00:00.500\nOh! Hello.',render.observed_captions(words,1))
        with self.assertRaisesRegex(ValueError,'Empty observed caption duration'):
            render.observed_captions([{'word':'Oh!','start':0,'end':0}],1)

    def test_observed_captions_reject_invalid_or_padded_duration_bounds(self):
        words=[{'word':'final','start':35.8,'end':36.0}]
        # A padded ASR decode can accept words beyond the actual video end.
        self.assertIn('00:00:36.000',render.observed_captions(words,36.2666875))
        with self.assertRaisesRegex(ValueError,'word timing'):
            render.observed_captions(words,35.918667)
        for duration in (True,0,-1,float('nan'),float('inf'),'36'):
            with self.subTest(duration=duration),self.assertRaisesRegex(ValueError,'media duration'):
                render.observed_captions(words,duration)
        # No hidden grace interval may place the cue outside playable media.
        with self.assertRaises(ValueError):
            render.observed_captions([{'word':'end','start':.9,'end':1.01}],1)

    def test_encoded_duration_comes_from_video_and_rejects_nonfinite_values(self):
        with patch.object(render.subprocess,'check_output',return_value=b'{"format":{"duration":"35.918667"}}') as probe:
            self.assertEqual(render.encoded_media_duration(Path('/tmp/candidate.mp4')),35.918667)
            self.assertEqual(probe.call_args.args[0][-1],'/tmp/candidate.mp4')
            self.assertEqual(probe.call_args.kwargs['timeout'],20)
        for duration in ('nan','inf','0','-1'):
            with patch.object(render.subprocess,'check_output',return_value=json.dumps({'format':{'duration':duration}}).encode()):
                with self.assertRaisesRegex(ValueError,'media duration'):
                    render.encoded_media_duration(Path('/tmp/candidate.mp4'))

    def test_transcription_blocks_word_beyond_encoded_end_before_caption_write(self):
        word=SimpleNamespace(word='hello',start=.9,end=1.1,probability=1.0)
        model=SimpleNamespace(hf_tokenizer=None,transcribe=lambda *a,**k:([SimpleNamespace(text='hello',words=[word])],None))
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);(out/'video.mp4').write_bytes(b'explicit synthetic video fixture')
            (out/'captions.vtt').write_text('original captions')
            scripts=out/'scripts';scripts.mkdir()
            (scripts/'free_transcription_qa.py').write_text(
                "def decode_transcription_audio(video):return [],1.5\n"
                "def spoken_number_suppression(tokenizer):return []\n"
                "def norm(text):return text.lower()\n")
            with patch.object(render,'pinned_asr_snapshot',return_value=(out,{})), \
                 patch.object(render,'encoded_media_duration',return_value=1.0), \
                 patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=lambda *a,**k:model)}), \
                 patch.object(render.socket.socket,'connect'):
                with self.assertRaisesRegex(ValueError,'word timing'):
                    render.transcribe_encoded({'scenes':[{'narration':'hello'}]},out,out)
                self.assertEqual((out/'captions.vtt').read_text(),'original captions')
                word.end = 1.0
                render.transcribe_encoded({'scenes':[{'narration':'hello'}]},out,out)
            self.assertIn('00:00:00.900 --> 00:00:01.000\nhello', (out/'captions.vtt').read_text())
            self.assertIsNone(json.loads((out/'transcription.json').read_text())['timeline_sha256'])

    def test_parent_approval_claims_are_rejected(self):
        for key in ['production_approved','full_av_review']:
            data=brief();data[key]=True
            with self.assertRaises(ValueError):render.validate(data)
            del data[key]
            with self.assertRaises(ValueError):render.validate(data)

    def test_guardian_timeout_cleans_owned_worker(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                render.run([sys.executable,'-c','import time;time.sleep(30)'],Path(td)/'timeout.log',time.monotonic()+.2)

    @unittest.skipUnless(os.name=='posix' and Path('/proc').is_dir(),'POSIX process checks required')
    def test_guardian_cleans_worker_after_renderer_parent_death(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'worker.pid'
            worker="import os,time;from pathlib import Path;Path("+repr(str(target))+").write_text(str(os.getpid()));time.sleep(30)"
            bootstrap="from integrations.content_control.cycle_render import run;from pathlib import Path;import sys,time;run([sys.executable,'-c',"+repr(worker)+"],Path("+repr(str(Path(td)/'worker.log'))+"),time.monotonic()+20)"
            parent=subprocess.Popen([sys.executable,'-c',bootstrap])
            try:
                deadline=time.monotonic()+5
                while not target.exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(target.exists(),'owned worker did not start')
                worker_pid=int(target.read_text());parent.kill();parent.wait()
                def running():
                    try:return Path(f'/proc/{worker_pid}/stat').read_text().split()[2]!='Z'
                    except FileNotFoundError:return False
                deadline=time.monotonic()+5
                while running() and time.monotonic()<deadline:time.sleep(.02)
                self.assertFalse(running(),'owned worker escaped parent-death cleanup')
            finally:
                if parent.poll() is None:parent.kill()
                parent.wait()

    @unittest.skipUnless(Path(render.FONT).is_file(),'Font unavailable')
    def test_all_panel_kinds_create_distinct_readable_images(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow unavailable')
        with tempfile.TemporaryDirectory() as td:
            hashes=[]
            for kind in sorted(render.KINDS):
                scene=brief()['scenes'][0];scene['visual_spec'].update(kind=kind,labels=['Real cost','Annual fee'],values=['$60','$95'])
                if kind in ('balance','checklist'): scene['visual_spec']['values']=[]
                path=Path(td)/(kind+'.png');render.draw_panel(scene,path,0,1)
                with Image.open(path) as image:self.assertEqual(image.size,(720,1280))
                hashes.append(render.digest(path))
            self.assertEqual(len(set(hashes)),len(render.KINDS))

    def _panel_text(self, spec):
        from PIL import ImageDraw
        original = ImageDraw.ImageDraw.text
        calls = []
        def capture(draw, xy, text, *args, **kwargs):
            if 300 <= xy[1] < 800:
                calls.append((text, draw.textbbox(xy, text, font=kwargs['font'], anchor=kwargs.get('anchor'))))
            return original(draw, xy, text, *args, **kwargs)
        with tempfile.TemporaryDirectory() as td, patch.object(ImageDraw.ImageDraw, 'text', capture):
            scene = brief()['scenes'][0]
            scene['visual_spec'] = dict(spec, headline='Check the math')
            render.draw_panel(scene, Path(td)/'panel.png', 0, 1)
        return calls

    @unittest.skipUnless(Path(render.FONT).is_file(),'Font unavailable')
    def test_receipt_preserves_each_labeled_amount_in_its_own_row(self):
        calls = self._panel_text({'kind':'receipt',
            'labels':['STATEMENT AT CLOSE', 'NEW POSTED PURCHASE', 'CURRENT AFTER PURCHASE'],
            'values':['$500', '+$40', '$540']})
        self.assertEqual([text for text, _ in calls],
            ['STATEMENT AT CLOSE', '$500', 'NEW POSTED PURCHASE', '+$40', 'CURRENT AFTER PURCHASE', '$540'])
        for (_, a), (_, b) in zip(calls, calls[1:]):
            self.assertLessEqual(a[3], b[1], 'Semantic fields must not overlap')
        for _, box in calls:
            self.assertGreaterEqual(box[0],105); self.assertLessEqual(box[2],615)
            self.assertGreaterEqual(box[1],350); self.assertLessEqual(box[3],740)

    @unittest.skipUnless(Path(render.FONT).is_file(),'Font unavailable')
    def test_comparison_labels_stay_in_their_corresponding_cards(self):
        for values in ([], ['$500', '$540']):
            calls = self._panel_text({'kind':'comparison', 'labels':['STATEMENT AT CLOSE','CURRENT BALANCE'], 'values':values})
            left = [(text, box) for text, box in calls if box[2] < 360]
            right = [(text, box) for text, box in calls if box[0] > 360]
            self.assertEqual(len(left)+len(right),len(calls))
            self.assertEqual(' '.join(text for text,_ in left), 'STATEMENT AT CLOSE'+(' $500' if values else ''))
            self.assertEqual(' '.join(text for text,_ in right), 'CURRENT BALANCE'+(' $540' if values else ''))
            for items, x in ((left,60),(right,375)):
                for _, box in items:
                    self.assertGreaterEqual(box[0],x+16); self.assertLessEqual(box[2],x+269)
                    self.assertGreaterEqual(box[1],340); self.assertLessEqual(box[3],710)

    @unittest.skipUnless(Path(render.FONT).is_file(),'Font unavailable')
    def test_receipt_and_card_retain_four_fields_and_unpaired_labels(self):
        for kind in ('receipt', 'card'):
            calls = self._panel_text({'kind':kind,'labels':['ONE','TWO','THREE','FOUR'],'values':['1','2']})
            self.assertEqual([text for text,_ in calls], ['ONE','1','TWO','2','THREE','FOUR'])
            for _,box in calls:
                self.assertGreaterEqual(box[0],105); self.assertLessEqual(box[2],615)
                self.assertLessEqual(box[3],740)
        for kind in ('receipt', 'card'):
            calls = self._panel_text({'kind':kind,'labels':['ONE','TWO','THREE','FOUR'],'values':['1','2','3','4']})
            self.assertEqual([text for text,_ in calls], ['ONE','1','TWO','2','THREE','3','FOUR','4'])
        with self.assertRaisesRegex(ValueError,'at most two'):
            self._panel_text({'kind':'comparison','labels':['A','B','C']})
        with self.assertRaisesRegex(ValueError,'readable panel bounds'):
            self._panel_text({'kind':'comparison','labels':['W'*50,'B']})

    @unittest.skipUnless(Path(render.FONT).is_file(),'Font unavailable')
    def test_every_repository_example_scene_renders_with_bounded_fields(self):
        examples = Path(__file__).parent/'examples'
        with tempfile.TemporaryDirectory() as td:
            count = 0; rejected = []
            for source in sorted(examples.glob('*.json')):
                scenes = json.loads(source.read_text()).get('scenes', [])
                for index,scene in enumerate(scenes):
                    if source.name in ('rewards-card-brief.json','rewards-card-revision.json') and scene['id']=='balance':
                        with self.assertRaisesRegex(ValueError,'paired fields'):
                            render.draw_panel(scene,Path(td)/f'{source.stem}-{index}.png',index,len(scenes))
                        rejected.append(source.name)
                        continue
                    render.draw_panel(scene,Path(td)/f'{source.stem}-{index}.png',index,len(scenes))
                    count += 1
            self.assertGreaterEqual(count, 28)
            self.assertEqual(sorted(rejected),['rewards-card-brief.json','rewards-card-revision.json'])

    @unittest.skipUnless(Path(render.FONT).is_file(),'Font unavailable')
    def test_gesture_moves_character_and_loops_without_changing_information_layer(self):
        try:
            from PIL import Image, ImageChops
        except ImportError:
            self.skipTest('Pillow unavailable')
        with tempfile.TemporaryDirectory() as td:
            paths=[Path(td)/f'phase-{i}.png' for i in range(4)]
            scene=brief()['scenes'][0]
            for path,phase in zip(paths,(0,.25,.75,1)):
                render.draw_panel(scene,path,0,1,phase=phase)
            with Image.open(paths[0]) as start, Image.open(paths[1]) as peak, Image.open(paths[2]) as opposite, Image.open(paths[3]) as end:
                self.assertIsNone(ImageChops.difference(start,end).getbbox())
                bounds=ImageChops.difference(start,peak).getbbox()
                self.assertIsNotNone(bounds)
                self.assertGreaterEqual(bounds[0],280); self.assertLessEqual(bounds[2],460)
                self.assertGreaterEqual(bounds[1],850); self.assertLessEqual(bounds[3],1120)
                self.assertIsNotNone(ImageChops.difference(peak,opposite).getbbox())
                # Diagrams/headlines and the anchored speaker label stay identical.
                self.assertEqual(start.crop((0,0,720,850)).tobytes(),peak.crop((0,0,720,850)).tobytes())
                self.assertEqual(start.crop((0,1120,720,1280)).tobytes(),peak.crop((0,1120,720,1280)).tobytes())
                changed = ImageChops.difference(start, peak).convert('L').histogram()
                self.assertGreater(sum(changed[1:]), 1500)
            for phase in (True,float('nan'),float('inf'),'0'):
                with self.assertRaises(ValueError):render.draw_panel(scene,paths[0],0,1,phase=phase)

    @unittest.skipUnless(Path(render.FONT).is_file(),'Font unavailable')
    def test_authored_point_keeps_selected_direction_during_character_motion(self):
        from PIL import Image, ImageChops
        with tempfile.TemporaryDirectory() as td:
            paths = [Path(td)/f'point-{index}.png' for index in range(3)]
            scene = brief()['scenes'][0]
            for layout, x, top, bottom in ((None, 360, 850, 1030), ('landscape', 265, 230, 410)):
                for direction in ('point_left', 'point_right'):
                    scene['visual_spec'] = {'kind': 'comparison', 'gesture': direction}
                    for phase, path in zip((0, .25, 1), paths):
                        render.draw_panel(scene, path, 0, 1, phase=phase, layout=layout)
                    with Image.open(paths[0]) as start, Image.open(paths[1]) as peak, Image.open(paths[2]) as end:
                        self.assertIsNone(ImageChops.difference(start, end).getbbox())
                        left, upper, right, lower = ImageChops.difference(start, peak).getbbox()
                        self.assertGreaterEqual(upper, top)
                        self.assertLessEqual(lower, bottom + 90)
                        # Information and speaker-label layers do not move.
                        fixed_bottom = 220 if layout == 'landscape' else 850
                        self.assertIsNone(ImageChops.difference(start, peak).crop(
                            (0, 0, start.width, fixed_bottom)).getbbox())
                        label_top = 540 if layout == 'landscape' else 1120
                        self.assertIsNone(ImageChops.difference(start, peak).crop(
                            (0, label_top, start.width, start.height)).getbbox())
                        # The authored pointing hand remains on the requested side
                        # of the moving torso at both representative phases.
                        for frame, body_x in ((start, x), (peak, x + 18)):
                            ink = frame.convert('RGB')
                            if direction == 'point_left':
                                region = (body_x - 100, top, body_x - 39, bottom)
                            else:
                                region = (body_x + 39, top, body_x + 100, bottom)
                            histogram = ink.crop(region).convert('L').histogram()
                            dark = sum(histogram[:120])
                            self.assertGreater(dark, 20)

    def test_phrase_reveal_uses_measured_narration_position(self):
        scene = brief()['scenes'][0]
        scene['narration'] = 'First claim is due. But interest can remain on the balance.'
        scene['visual_spec'] = {'kind': 'comparison', 'labels': ['DUE', 'BALANCE'],
                                'values': ['PAY', 'INTEREST'],
                                'reveal_on_phrase': 'But interest can remain',
                                'gesture': 'point_right'}
        render.validate({'publication_enabled': False, 'production_approved': False,
                         'full_av_review': False, 'paid_generation_enabled': False,
                         'scenes': [scene]})
        _, reveal = render.picture_filters(scene, 240, narration_duration=9.0)
        expected = math.ceil(9.0 * scene['narration'].index('But interest') /
                             len(scene['narration']) * 24)
        self.assertEqual(reveal['first_visible_scene_frame'], expected)
        self.assertEqual(reveal['requested_phrase'], 'But interest can remain')
        self.assertEqual(reveal['alignment_method'], 'measured_duration_character_fraction')
        self.assertGreater(reveal['rendered_offset_seconds'], 2.5)

    def test_phrase_reveal_rejects_ambiguous_or_mixed_timing(self):
        scene = brief()['scenes'][0]
        scene['narration'] = 'Repeat cue. Repeat cue.'
        complete = {'kind': 'comparison', 'labels': ['A', 'B'], 'values': ['1', '2'],
                    'reveal_on_phrase': 'Repeat cue'}
        scene['visual_spec'] = complete
        editorial = {'publication_enabled': False, 'production_approved': False,
                     'full_av_review': False, 'paid_generation_enabled': False,
                     'scenes': [scene]}
        with self.assertRaisesRegex(ValueError, 'exactly once'):
            render.validate(editorial)
        scene['narration'] = 'Repeat cue once.'
        scene['visual_spec'] = dict(complete, reveal_after_seconds=1)
        with self.assertRaisesRegex(ValueError, 'exactly one timing method'):
            render.validate(editorial)

    @unittest.skipUnless(Path(render.FONT).is_file(),'Font unavailable')
    def test_long_checklist_label_wraps_inside_its_row_in_both_layouts(self):
        from PIL import Image, ImageChops
        labels = ['First', 'Second', 'Third', 'JUST VERIFY EVERY PAYMENT BEFORE THE NEXT BILLING']
        with tempfile.TemporaryDirectory() as td:
            path, baseline = (Path(td) / name for name in ('wrapped.png', 'baseline.png'))
            scene = dict(brief()['scenes'][0], visual_spec={'kind': 'checklist', 'labels': labels})
            prior = dict(scene, visual_spec={'kind': 'checklist', 'labels': labels[:3] + ['']})
            for layout, dx, dy in ((None, 0, 0), ('landscape', 515, -181)):
                with self.subTest(layout=layout):
                    render.draw_panel(prior, baseline, 0, 1, layout=layout)
                    render.draw_panel(scene, path, 0, 1, layout=layout)
                    with Image.open(baseline) as before, Image.open(path) as after:
                        delta = ImageChops.difference(before, after)
                        left, top, right, bottom = delta.getbbox()
                        self.assertGreaterEqual(left, 175 + dx)
                        self.assertLessEqual(right, 605 + dx)
                        self.assertGreaterEqual(top, 642 + dy)
                        self.assertLessEqual(bottom, 706 + dy)
                        rows = delta.crop((left, top, right, bottom)).convert('L')
                        ink = [rows.crop((0, y, rows.width, y+1)).getbbox() is not None
                               for y in range(rows.height)]
                        self.assertEqual(sum(value and (i == 0 or not ink[i-1])
                                             for i, value in enumerate(ink)), 2)

    @unittest.skipUnless(Path(render.FONT).is_file(),'Font unavailable')
    def test_above_speaker_label_changes_only_the_two_label_regions(self):
        from PIL import Image, ImageChops
        with tempfile.TemporaryDirectory() as td:
            original, changed = (Path(td)/name for name in ('original.png', 'above.png'))
            scene = dict(brief()['scenes'][0], speaker='points_monk', visual_spec={
                'kind': 'checklist', 'labels': ['One', 'Two', 'Three', 'Four']})
            render.draw_panel(scene, original, 0, 1)
            render.draw_panel(scene, changed, 0, 1, speaker_label_position='above')
            with Image.open(original) as first, Image.open(changed) as second:
                delta = ImageChops.difference(first, second)
                for upper, lower in ((0, 814), (835, 1130), (1151, 1280)):
                    self.assertIsNone(delta.crop((0, upper, 720, lower)).getbbox())
                self.assertIsNotNone(delta.crop((0, 814, 720, 835)).getbbox())
                self.assertIsNotNone(delta.crop((0, 1130, 720, 1151)).getbbox())
            with self.assertRaisesRegex(ValueError, 'speaker_label_position'):
                render.draw_panel(scene, changed, 0, 1, layout='landscape', speaker_label_position='above')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe') and Path(render.FONT).is_file(),'Media runtime unavailable')
    def test_actual_mux_and_decode_with_explicit_synthetic_voice_fixture(self):
        try:
            import PIL
        except ImportError:
            self.skipTest('Pillow unavailable')
        real_run=render.run
        def voice_fixture(command,log,deadline,env=None):
            if '--synthesize' not in command:
                real_run(command,log,deadline,env)
                if log.parent.name in ('mux-short', 'mux-long', 'container-long') and command[0] == 'ffprobe':
                    probe=json.loads(log.read_text())
                    video=next(stream for stream in probe['streams'] if stream['codec_type'] == 'video')
                    if log.parent.name == 'container-long':
                        video.update(duration_ts=48,time_base='1/24')
                        probe['format']['duration']='2.050000'
                    else:
                        video.update(duration_ts=23 if log.parent.name == 'mux-short' else 49,time_base='1/24')
                    render.write(log,probe)
                return
            out=Path(command[command.index('--output')+1]);data=json.loads((out/'editorial.json').read_text())
            text=data['scenes'][0]['narration'];wav=out/'voice-00.wav';rate=24000
            length=4 if 'reveal_after_seconds' in data['scenes'][0].get('visual_spec', {}) else 1
            if out.name == 'container-long':
                length=1.72
            source=[1000*math.sin(i*2*math.pi*220/rate)/32767 for i in range(round(rate*length))]
            normalized, normalization = render.normalize_voice_samples(source)
            samples=[round(value*32767) for value in normalized]
            with wave.open(str(wav),'wb') as stream:
                stream.setparams((1,2,rate,0,'NONE','not compressed'))
                stream.writeframes(struct.pack('<'+'h'*len(samples),*samples))
            actual = render.wave_pcm_stats(wav)
            normalization.update(output_rms=actual['rms'], output_peak=actual['peak'])
            render.write(out/'voice.json',{'model_revision':'synthetic-test-fixture',
                'status':'GENERATED_PENDING_LISTENING_REVIEW',
                'voice_assignments':render.VOICE_ASSIGNMENTS,
                'publication_enabled':False,'paid_generation_enabled':False,
                'production_approved':False,'full_av_review':False,'clips':[{
                'scene_id':data['scenes'][0]['id'],'speaker':data['scenes'][0].get('speaker','narrator'),
                'voice_id':render.VOICE_ASSIGNMENTS[data['scenes'][0].get('speaker','narrator')],
                'file':wav.name,'audio_sha256':render.digest(wav),
                'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
                'duration_seconds':float(length),'rms':actual['rms'],
                'level_normalization':normalization}]})
        with tempfile.TemporaryDirectory() as td,patch.object(render,'run',side_effect=voice_fixture):
            shortfall=Path(td)/'shortfall'
            blocked=render.render_cycle(brief(),shortfall,voice_python=sys.executable,voice_root=td,
                                        timeout=60,minimum_duration=2)
            self.assertEqual(blocked['status'],'BLOCKED')
            self.assertEqual(blocked['measured_narration_frame_budget'],31)
            self.assertIn('below 2s minimum',blocked['reason'])
            self.assertFalse(any(shortfall.glob('segment-*.mp4')))
            self.assertFalse((shortfall/'video.mp4').exists())
            mux_short=Path(td)/'mux-short'
            blocked=render.render_cycle(brief(),mux_short,voice_python=sys.executable,voice_root=td,
                                        timeout=60,minimum_duration=1,transcription_python=sys.executable)
            self.assertIn('Encoded picture duration',blocked['reason'])
            self.assertFalse((mux_short/'transcription.log').exists())
            self.assertEqual(blocked['encoded_picture_duration_seconds'],23/24)
            overflow=Path(td)/'overflow'
            blocked=render.render_cycle(brief(),overflow,voice_python=sys.executable,voice_root=td,
                                        timeout=60,maximum_duration=1)
            self.assertIn('above 1s maximum',blocked['reason'])
            self.assertEqual(blocked['measured_narration_frame_budget'],31)
            self.assertFalse(any(overflow.glob('segment-*.mp4')))
            mux_long=Path(td)/'mux-long'
            blocked=render.render_cycle(brief(),mux_long,voice_python=sys.executable,voice_root=td,
                                        timeout=60,maximum_duration=2,transcription_python=sys.executable)
            self.assertIn('Encoded picture or container exceeds 2s maximum',blocked['reason'])
            self.assertEqual(blocked['encoded_picture_duration_seconds'],49/24)
            self.assertLess(blocked['encoded_container_duration_seconds'],2)
            self.assertFalse((mux_long/'transcription.log').exists())
            container_long=Path(td)/'container-long'
            blocked=render.render_cycle(brief(),container_long,voice_python=sys.executable,voice_root=td,
                                        timeout=60,maximum_duration=2,transcription_python=sys.executable)
            self.assertIn('Encoded picture or container exceeds 2s maximum',blocked['reason'])
            self.assertEqual(blocked['encoded_picture_duration_seconds'],2)
            self.assertEqual(blocked['encoded_container_duration_seconds'],2.05)
            self.assertFalse((container_long/'transcription.log').exists())
            out=Path(td)/'run';result=render.render_cycle(brief(),out,voice_python=sys.executable,voice_root=td,timeout=60)
            self.assertEqual(result['status'],'AWAITING_REVIEW',result)
            self.assertEqual(result['candidate_sha256'],render.digest(out/'video.mp4'))
            self.assertEqual(result['caption_sha256'],render.digest(out/'captions.vtt'))
            self.assertEqual(result['editorial_sha256'],render.editorial_digest(brief()))
            self.assertFalse(result['independent_transcription_verified'])
            self.assertFalse(result['full_av_review']);self.assertFalse(result['production_approved'])
            self.assertFalse(result['publication_enabled']);self.assertEqual(len(result['scenes']),1)
            self.assertEqual(result['timestamp_normalization']['mode'],
                             'measured_video_offset_stream_copy')
            self.assertEqual(result['timestamp_normalization']['video_start_seconds'], 0)
            self.assertEqual(result['timestamp_normalization']['audio_start_seconds'], 0)
            self.assertEqual(result['motion']['loop_seconds'],3)
            self.assertEqual(result['motion']['output_fps'],24)
            self.assertEqual(result['motion']['kind'],'periodic_whole_character_sway_bob_v1')
            self.assertEqual(result['motion']['kind'],render.MOTION_KIND)
            self.assertIn('whole-character sway and bob',result['motion']['scope'])
            row=result['scenes'][0]
            self.assertEqual(len(row['motion_frames_sha256']),24)
            self.assertEqual(row['motion_frames_sha256']['frame-00.png'],row['panel_sha256'])
            for filename,expected in row['motion_frames_sha256'].items():
                self.assertEqual(render.digest(out/row['motion_directory']/filename),expected)
            # Decode two encoded frames to prove actual output contains movement.
            frames=subprocess.check_output(['ffmpeg','-v','error','-i',str(out/'video.mp4'),
                '-vf',r'select=eq(n\,0)+eq(n\,18)','-vsync','0','-frames:v','2',
                '-f','rawvideo','-pix_fmt','rgb24','-threads','1','-'])
            frame_bytes=720*1280*3
            self.assertEqual(len(frames),frame_bytes*2)
            self.assertNotEqual(frames[:frame_bytes],frames[frame_bytes:])

            revealed=brief()
            revealed['scenes'][0]['visual_spec']={'kind':'comparison','headline':'SAME DINNER',
                'labels':['PENDING','POSTED'],'values':['20','24'],'reveal_after_seconds':.51,'gesture':'point_right'}
            timed=Path(td)/'timed'
            result=render.render_cycle(revealed,timed,voice_python=sys.executable,voice_root=td,timeout=60)
            self.assertEqual(result['status'],'AWAITING_REVIEW',result)
            self.assertEqual(result['scenes'][0]['visual_reveal']['first_visible_scene_frame'],13)
            self.assertEqual(result['scenes'][0]['authored_gesture'],'point_right')
            region=subprocess.check_output(['ffmpeg','-v','error','-i',str(timed/'segment-00.mp4'),
                '-vf',r'select=eq(n\,0)+eq(n\,12)+eq(n\,13)+eq(n\,84),crop=240:300:396:360',
                '-vsync','0','-frames:v','4','-f','rawvideo','-pix_fmt','rgb24','-threads','1','-'])
            stride=240*300*3
            self.assertEqual(len(region),4*stride)
            dark=[sum(channel<120 for channel in region[i:i+stride:3]) for i in range(0,len(region),stride)]
            self.assertEqual(dark[:2],[0,0])
            self.assertTrue(all(count>500 for count in dark[2:]))

            revealed['layout']='landscape'
            wide=Path(td)/'wide'
            result=render.render_cycle(revealed,wide,voice_python=sys.executable,voice_root=td,
                                       timeout=60,minimum_duration=4)
            self.assertEqual(result['status'],'AWAITING_REVIEW',result)
            self.assertEqual(result['minimum_duration_seconds'],4)
            self.assertEqual(result['measured_narration_frame_budget'],103)
            self.assertGreaterEqual(result['encoded_picture_duration_seconds'],4)
            self.assertEqual(result['layout'],'landscape')
            self.assertEqual(result['scenes'][0]['visual_reveal']['first_visible_scene_frame'],13)
            probe=json.loads((wide/'probe.json').read_text())
            picture=next(s for s in probe['streams'] if s['codec_type']=='video')
            self.assertEqual((picture['width'],picture['height'],picture['sample_aspect_ratio']),(1280,720,'1:1'))
            region=subprocess.check_output(['ffmpeg','-v','error','-i',str(wide/'segment-00.mp4'),
                '-vf',r'select=eq(n\,0)+eq(n\,12)+eq(n\,13)+eq(n\,84),crop=240:300:912:180',
                '-vsync','0','-frames:v','4','-f','rawvideo','-pix_fmt','rgb24','-threads','1','-'])
            self.assertEqual(len(region),4*stride)
            dark=[sum(channel<120 for channel in region[i:i+stride:3]) for i in range(0,len(region),stride)]
            self.assertEqual(dark[:2],[0,0])
            self.assertTrue(all(count>500 for count in dark[2:]))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Media tools unavailable')
    def test_mux_start_normalization_shifts_only_video_timestamps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, staged, final = (root/name for name in ('base.mp4', 'staged.mp4', 'final.mp4'))
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y',
                '-f', 'lavfi', '-i', 'color=c=blue:s=90x160:r=24:d=1',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=24000:duration=1',
                '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-ar', '24000', '-ac', '1', '-shortest', str(base)], check=True)
            # Reproduce concat's video-only lead-in while retaining audio at zero.
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y',
                '-itsoffset', '0.041992', '-i', str(base), '-i', str(base),
                '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', str(staged)], check=True)

            def starts(path):
                raw = subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                    '-of', 'json', str(path)])
                streams = json.loads(raw)['streams']
                return {stream['codec_type']: float(stream['start_time']) for stream in streams}

            before = starts(staged)
            self.assertGreater(before['video'], .04)
            self.assertEqual(before['audio'], 0)
            evidence = render.normalize_mux_video_start(staged, final, time.monotonic()+30)
            self.assertEqual(evidence['staged_video_start_seconds'], before['video'])
            self.assertEqual(starts(final), {'video': 0, 'audio': 0})

            self.assertEqual(evidence['encoded_streams_sha256'], {
                'video': render.encoded_stream_sha256(final, 'v:0', root/'final-video-check.log',
                                                      time.monotonic()+30),
                'audio': render.encoded_stream_sha256(final, 'a:0', root/'final-audio-check.log',
                                                      time.monotonic()+30),
            })

            def audio_framehash(path):
                return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                    '-map', '0:a:0', '-c', 'copy', '-f', 'framehash', '-'])
            self.assertEqual(audio_framehash(staged), audio_framehash(final))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Media tools unavailable')
    def test_mux_start_normalization_removes_changed_stream_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, staged, final = (root/name for name in ('base.mp4', 'staged.mp4', 'final.mp4'))
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y',
                '-f', 'lavfi', '-i', 'color=c=blue:s=90x160:r=24:d=0.5',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=24000:duration=0.5',
                '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-ar', '24000', '-ac', '1', '-shortest', str(base)], check=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y',
                '-itsoffset', '0.041992', '-i', str(base), '-i', str(base),
                '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', str(staged)], check=True)
            with patch.object(render, 'encoded_stream_sha256',
                              side_effect=['video-a', 'audio-a', 'video-b', 'audio-a']):
                with self.assertRaisesRegex(ValueError, 'encoded stream payloads'):
                    render.normalize_mux_video_start(staged, final, time.monotonic()+30)
            self.assertFalse(final.exists())


class PinnedASRTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.hub=Path(self.temp.name)/'hub'
        self.snapshot=self.hub/'models--Systran--faster-whisper-base.en'/'snapshots'/render.ASR_REVISION
        self.snapshot.mkdir(parents=True)
        self.assets={name:(len(name.encode()),hashlib.sha256(name.encode()).hexdigest())
                     for name in render.ASR_ASSETS}
        for name in self.assets:(self.snapshot/name).write_bytes(name.encode())
        self.addCleanup(patch.stopall)
        patch.object(render,'ASR_ASSETS',self.assets).start()
        patch.dict(os.environ,{'HF_HUB_CACHE':str(self.hub)}).start()

    def test_exact_snapshot_selected_without_mutable_main_and_identity_retained(self):
        refs=self.snapshot.parent.parent/'refs';refs.mkdir();(refs/'main').write_text('0'*40)
        path,identity=render.pinned_asr_snapshot()
        self.assertEqual(path,self.snapshot)
        self.assertEqual(identity['revision'],render.ASR_REVISION)
        self.assertEqual(set(identity['files']),set(self.assets))
        self.assertEqual(identity['files']['model.bin']['sha256'],self.assets['model.bin'][1])

    def test_normal_blob_symlink_supported_but_escape_rejected(self):
        model=self.snapshot/'model.bin';model.unlink()
        blob=self.hub/'models--Systran--faster-whisper-base.en'/'blobs'/'verified'
        blob.parent.mkdir();blob.write_bytes(b'model.bin');model.symlink_to(blob)
        render.pinned_asr_snapshot()
        model.unlink();outside=Path(self.temp.name)/'outside';outside.write_bytes(b'model.bin');model.symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'outside selected cache'):render.pinned_asr_snapshot()

    def test_corruption_missing_and_unverified_extra_files_rejected(self):
        model=self.snapshot/'model.bin'
        model.write_bytes(b'MODEL.BIN')
        with self.assertRaisesRegex(ValueError,'size/hash'):render.pinned_asr_snapshot()
        model.unlink()
        with self.assertRaisesRegex(ValueError,'exactly'):render.pinned_asr_snapshot()
        model.write_bytes(b'model.bin');(self.snapshot/'preprocessor_config.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'exactly'):render.pinned_asr_snapshot()

    def test_missing_pin_blocks_before_importing_or_loading_model(self):
        self.snapshot.rename(self.snapshot.with_name('0'*40))
        with patch.dict(sys.modules,{'faster_whisper':None}):
            with self.assertRaisesRegex(ValueError,'snapshot unavailable'):
                render.transcribe_encoded({},Path(self.temp.name),self.temp.name)

    def test_hf_home_cache_location_supported(self):
        with patch.dict(os.environ,{'HF_HOME':self.temp.name}):
            del os.environ['HF_HUB_CACHE']
            path,_=render.pinned_asr_snapshot()
        self.assertEqual(path,self.snapshot)


if __name__=='__main__':unittest.main()
