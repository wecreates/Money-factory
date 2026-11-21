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
                path=Path(td)/(kind+'.png');render.draw_panel(scene,path,0,1)
                with Image.open(path) as image:self.assertEqual(image.size,(720,1280))
                hashes.append(render.digest(path))
            self.assertEqual(len(set(hashes)),len(render.KINDS))

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


if __name__=='__main__':unittest.main()
