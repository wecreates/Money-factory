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


class RenderValidationTests(unittest.TestCase):
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
                         ['Dr. A. Smith paid $3.14 in U.S.', 'fees.'])
        self.assertTrue(render._caption_sentence_end('$3.14.'))

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
    def test_gesture_moves_only_arms_and_loops_without_changing_layout(self):
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
                self.assertGreaterEqual(bounds[0],280); self.assertLessEqual(bounds[2],440)
                self.assertGreaterEqual(bounds[1],910); self.assertLessEqual(bounds[3],1040)
                self.assertIsNotNone(ImageChops.difference(peak,opposite).getbbox())
                # Diagrams/headlines, face, feet and speaker label stay identical.
                self.assertEqual(start.crop((0,0,720,910)).tobytes(),peak.crop((0,0,720,910)).tobytes())
                self.assertEqual(start.crop((0,1040,720,1280)).tobytes(),peak.crop((0,1040,720,1280)).tobytes())
            for phase in (True,float('nan'),float('inf'),'0'):
                with self.assertRaises(ValueError):render.draw_panel(scene,paths[0],0,1,phase=phase)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe') and Path(render.FONT).is_file(),'Media runtime unavailable')
    def test_actual_mux_and_decode_with_explicit_synthetic_voice_fixture(self):
        try:
            import PIL
        except ImportError:
            self.skipTest('Pillow unavailable')
        real_run=render.run
        def voice_fixture(command,log,deadline,env=None):
            if '--synthesize' not in command:return real_run(command,log,deadline,env)
            out=Path(command[command.index('--output')+1]);data=json.loads((out/'editorial.json').read_text())
            text=data['scenes'][0]['narration'];wav=out/'voice-00.wav';rate=24000
            samples=[int(1000*math.sin(i*2*math.pi*220/rate)) for i in range(rate)]
            with wave.open(str(wav),'wb') as stream:
                stream.setparams((1,2,rate,0,'NONE','not compressed'))
                stream.writeframes(struct.pack('<'+'h'*len(samples),*samples))
            render.write(out/'voice.json',{'model_revision':'synthetic-test-fixture','clips':[{
                'audio_sha256':render.digest(wav),'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
                'duration_seconds':1.0}]})
        with tempfile.TemporaryDirectory() as td,patch.object(render,'run',side_effect=voice_fixture):
            out=Path(td)/'run';result=render.render_cycle(brief(),out,voice_python=sys.executable,voice_root=td,timeout=60)
            self.assertEqual(result['status'],'AWAITING_REVIEW',result)
            self.assertEqual(result['candidate_sha256'],render.digest(out/'video.mp4'))
            self.assertEqual(result['caption_sha256'],render.digest(out/'captions.vtt'))
            self.assertEqual(result['editorial_sha256'],render.editorial_digest(brief()))
            self.assertFalse(result['independent_transcription_verified'])
            self.assertFalse(result['full_av_review']);self.assertFalse(result['production_approved'])
            self.assertFalse(result['publication_enabled']);self.assertEqual(len(result['scenes']),1)
            self.assertEqual(result['motion']['loop_seconds'],3)
            self.assertEqual(result['motion']['output_fps'],24)
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
