"""Synthetic fixture tests establish transport/encoding, not creative acceptance."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control import cycle_short as m

VTT='WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nFirst words.\n\n2\n00:00:01.200 --> 00:00:02.500\nSecond words.\n\n3\n00:00:02.500 --> 00:00:03.000\nLast words.\n'


class CaptionTests(unittest.TestCase):
    def test_clip_rebase_and_disclose_boundary_text(self):
        text,boundary=m.clip_captions(VTT,500,2000)
        self.assertEqual(boundary,[1,2])
        self.assertIn('00:00:00.000 --> 00:00:00.500\nFirst words.',text)
        self.assertIn('00:00:00.700 --> 00:00:01.500\nSecond words.',text)
        self.assertNotIn('Last words',text)

    def test_exact_edges_and_empty_interval(self):
        text,boundary=m.clip_captions(VTT,1200,2500)
        self.assertEqual(boundary,[]);self.assertNotIn('First',text);self.assertNotIn('Last',text)
        self.assertEqual(m.clip_captions(VTT,3000,4000),('WEBVTT\n\n',[]))

    def test_unsupported_or_invalid_captions_fail_closed(self):
        for text in ('bad',VTT.replace('00:00:01.200','00:00:00.900'),
                     VTT.replace('00:00:01.000','00:00:00.000'),
                     VTT.replace('00:00:01.000','00:00:01.000 align:start')):
            with self.subTest(text=text),self.assertRaises(ValueError):m.clip_captions(text,0,2000)


class ShortTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'cycle';self.source=self.root/'delivery'
        self.source.mkdir(parents=True);(self.source/'captions.vtt').write_text(VTT)
        self.snapshot={'candidate_sha256':'a'*64,'files_sha256':{'cycle.json':'b'*64}}

    def media(self, size='90x160'):
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'color=c=blue:s={size}:r=24:d=3',
                        '-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-threads','1',
                        '-c:a','aac','-shortest',str(self.source/'video.mp4')],check=True)

    def test_real_synthetic_cut_preserves_framing_and_bound_captions(self):
        self.media()
        with patch.object(m,'inspect_cycle',return_value=self.snapshot):
            r=m.make_short(self.root,self.base/'short',start=.5,end=2,timeout=30)
        self.assertEqual(r['status'],'AWAITING_REVIEW',r)
        self.assertEqual((r['media']['width'],r['media']['height']),(90,160))
        self.assertEqual(r['boundary_cue_numbers'],[1,2])
        self.assertEqual(r['candidate_sha256'],m.digest(self.base/'short/video.mp4'))
        self.assertEqual(r['parent_candidate_sha256'],'a'*64)
        self.assertEqual(r['source_counter'],{'action':'preserve'})
        for flag in m.FLAGS:self.assertFalse(r[flag])
        self.assertIn('Second words.',(self.base/'short/captions.vtt').read_text())

    def known_layout(self):
        self.snapshot['editorial']={'scenes':[{'visual_spec':{'kind':'card'}}]}
        (self.source/'render.json').write_text(json.dumps({'scope':
            'Fresh offline speech and original diagram-based picture video; technical verification only.'}))

    def test_counter_opt_in_changes_only_known_corner_and_preserves_captions(self):
        from PIL import Image
        self.media('720x1280'); self.known_layout()
        with patch.object(m,'inspect_cycle',return_value=self.snapshot):
            r=m.make_short(self.root,self.base/'clean',start=0,end=1,timeout=30,hide_source_counter=True)
        self.assertEqual(r['status'],'AWAITING_REVIEW',r)
        self.assertEqual(r['source_counter']['rectangle_xywh'],[570,40,110,45])
        self.assertEqual(r['tool_sha256'],m.digest(Path(m.__file__)))
        frame=self.base/'frame.png'
        subprocess.run(['ffmpeg','-v','error','-i',str(self.base/'clean/video.mp4'),
                        '-frames:v','1','-threads','1',str(frame)],check=True)
        with Image.open(frame) as image:
            for point in ((580,45),(670,75)):
                pixel=image.getpixel(point)
                self.assertTrue(all(abs(a-b)<12 for a,b in zip(pixel,(247,241,230))),pixel)
            for point in ((550,60),(600,105),(360,600)):
                pixel=image.getpixel(point); self.assertLess(pixel[0],15);self.assertGreater(pixel[2],230)
        self.assertEqual((self.base/'clean/captions.vtt').read_text(),m.clip_captions(VTT,0,1000)[0])

    def test_counter_opt_in_rejects_unknown_layout_before_output_creation(self):
        self.known_layout()
        for media,scope in [({'width':90,'height':160,'duration_seconds':3},None),
                            ({'width':720,'height':1280,'duration_seconds':3},'Unknown renderer')]:
            if scope:(self.source/'render.json').write_text(json.dumps({'scope':scope}))
            with patch.object(m,'inspect_cycle',return_value=self.snapshot), \
                 patch.object(m,'_probe',return_value=media),self.assertRaisesRegex(ValueError,'known 720x1280'):
                m.make_short(self.root,self.base/'unused',start=0,end=1,hide_source_counter=True)
            self.assertFalse((self.base/'unused').exists())
        for value in ('true',1,None):
            with self.assertRaisesRegex(ValueError,'boolean'):
                m.make_short(self.root,self.base/'unused',start=0,end=1,hide_source_counter=value)

    def test_compact_burn_uses_excerpt_clock_and_copies_audio(self):
        from PIL import Image
        self.media('720x1280'); self.known_layout()
        clean, burned = self.base/'plain', self.base/'path: with spaces'
        with patch.object(m,'inspect_cycle',return_value=self.snapshot):
            a=m.make_short(self.root,clean,start=.5,end=2,timeout=30)
            b=m.make_short(self.root,burned,start=.5,end=2,timeout=30,compact_captions=True)
        self.assertEqual(a['status'],'AWAITING_REVIEW',a)
        self.assertEqual(b['status'],'AWAITING_REVIEW',b)
        self.assertEqual(b['caption_overlay']['style'],m.COMPACT_STYLE)
        self.assertEqual(b['caption_sha256'],a['caption_sha256'])
        self.assertEqual(b['boundary_cue_numbers'],[1,2])
        def audio_hash(path):
            return subprocess.check_output(['ffmpeg','-v','error','-i',str(path/'video.mp4'),
                                            '-map','0:a:0','-c:a','copy','-f','framehash','-'])
        self.assertEqual(audio_hash(burned),audio_hash(clean))
        for offset, visible in (('0.25',True),('0.60',False),('0.90',True)):
            frame=self.base/f'{offset}.png'
            subprocess.run(['ffmpeg','-v','error','-i',str(burned/'video.mp4'),'-ss',offset,
                            '-frames:v','1','-threads','1',str(frame)],check=True)
            with Image.open(frame) as image:
                red=image.getchannel('R')
                self.assertLess(red.crop((0,0,720,1150)).getextrema()[1],50)
                self.assertEqual(red.crop((0,1150,720,1280)).getextrema()[1]>140,visible)

    def test_compact_burn_rejects_empty_or_marked_up_cues(self):
        self.media('720x1280'); self.known_layout()
        with patch.object(m,'inspect_cycle',return_value=self.snapshot):
            for captions, reason in [('WEBVTT\n\n','timed cues'),(VTT.replace('First','<b>First</b>'),'unmarked')]:
                (self.source/'captions.vtt').write_text(captions)
                with self.assertRaisesRegex(ValueError,reason):
                    m.make_short(self.root,self.base/'unused',start=0,end=1,compact_captions=True)
                self.assertFalse((self.base/'unused').exists())

    def test_counter_rectangle_contains_maximum_renderer_counter_without_headline(self):
        from PIL import Image, ImageDraw, ImageFont
        from integrations.content_control.cycle_render import FONT
        draw=ImageDraw.Draw(Image.new('RGB',(720,1280)))
        for counter in ('1/1','1/30','30/30'):
            a,b,c,d=draw.textbbox((660,50),counter,font=ImageFont.truetype(FONT,22),anchor='rt')
            self.assertGreaterEqual(a,570);self.assertGreaterEqual(b,40)
            self.assertLessEqual(c,680);self.assertLessEqual(d,85)
        self.assertLess(85,105)  # Existing headline begins at y105.

    def test_captions_end_at_actual_encoded_duration(self):
        def fake_run(command, deadline):
            if command[0] == 'ffmpeg' and '-c:v' in command:
                Path(command[-1]).write_bytes(b'synthetic media')
            return b''
        with patch.object(m,'inspect_cycle',return_value=self.snapshot), \
             patch.object(m,'_probe',side_effect=[{'width':90,'height':160,'duration_seconds':3},
                                                 {'width':90,'height':160,'duration_seconds':1.45}]), \
             patch.object(m,'_run',side_effect=fake_run):
            r=m.make_short(self.root,self.base/'shorter',start=.5,end=2)
        self.assertEqual(r['status'],'AWAITING_REVIEW',r)
        self.assertIn('00:00:01.450',(self.base/'shorter/captions.vtt').read_text())
        self.assertNotIn('00:00:01.500',(self.base/'shorter/captions.vtt').read_text())

    def test_bounds_existing_paths_and_symlinks_rejected(self):
        for a,b in [(0,61),(float('nan'),2),(-1,1),(1,1),(False,2)]:
            with self.assertRaises(ValueError):m.make_short(self.root,self.base/'unused',start=a,end=b)
        out=self.base/'existing';out.mkdir()
        with self.assertRaises(ValueError):m.make_short(self.root,out,start=0,end=1)
        link=self.base/'link';link.symlink_to(self.root)
        with self.assertRaises(ValueError):m.make_short(link,self.base/'unused',start=0,end=1)

    def test_wrong_framing_and_source_duration_rejected(self):
        self.media()
        with patch.object(m,'inspect_cycle',return_value=self.snapshot):
            with self.assertRaisesRegex(ValueError,'exceeds source'):
                m.make_short(self.root,self.base/'unused',start=0,end=4)
        raw={'streams':[{'codec_type':'video','width':160,'height':90},{'codec_type':'audio'}],
             'format':{'duration':'3'}}
        with patch.object(m,'_run',return_value=json.dumps(raw).encode()),self.assertRaisesRegex(ValueError,'portrait'):
            m._probe(self.source/'video.mp4',123)

    def test_failed_encode_and_changed_source_keep_blocked_receipts(self):
        self.media()
        with patch.object(m,'inspect_cycle',return_value=self.snapshot), \
             patch.object(m,'_probe',return_value={'width':90,'height':160,'duration_seconds':3}), \
             patch.object(m,'_run',side_effect=RuntimeError('synthetic failure')):
            r=m.make_short(self.root,self.base/'failed',start=0,end=2)
        self.assertEqual(r['status'],'BLOCKED');self.assertIn('synthetic failure',r['reason'])
        with patch.object(m,'inspect_cycle',side_effect=[self.snapshot,dict(self.snapshot,changed=True)]):
            r=m.make_short(self.root,self.base/'changed',start=0,end=2,timeout=30)
        self.assertEqual(r['status'],'BLOCKED');self.assertIn('changed',r['reason'])


if __name__=='__main__':unittest.main()
