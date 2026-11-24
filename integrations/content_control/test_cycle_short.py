"""Synthetic fixture tests establish transport/encoding, not creative acceptance."""
from html import escape
import json
import re
from fractions import Fraction
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control import cycle_av_review
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

    def media(self, size='90x160', *, rate='24', duration=3):
        subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i',f'color=c=blue:s={size}:r={rate}:d={duration}',
                        '-f','lavfi','-i',f'sine=frequency=440:duration={duration}','-c:v','libx264','-threads','1',
                        '-c:a','aac','-shortest',str(self.source/'video.mp4')],check=True)

    def test_real_synthetic_cut_preserves_framing_and_bound_captions(self):
        self.media()
        with patch.object(m,'inspect_cycle',return_value=self.snapshot):
            r=m.make_short(self.root,self.base/'short',start=.5,end=2,timeout=30)
        self.assertEqual(r['status'],'AWAITING_REVIEW',r)
        self.assertEqual((r['media']['width'],r['media']['height']),(90,160))
        self.assertEqual(r['boundary_cue_numbers'],[1,2])
        self.assertEqual(r['candidate_sha256'],m.digest(self.base/'short/video.mp4'))
        self.assertRegex(r['decoded_picture_sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(set(r['encoded_streams_sha256']), {'video', 'audio'})
        self.assertTrue(all(re.fullmatch(r'[0-9a-f]{64}', value)
                            for value in r['encoded_streams_sha256'].values()))
        self.assertEqual(r['parent_candidate_sha256'],'a'*64)
        review = self.base / 'short/automated-review.json'
        self.assertEqual(r['automated_review_sha256'], m.digest(review))
        self.assertEqual(json.loads(review.read_text())['candidate_sha256'], r['candidate_sha256'])
        self.assertEqual(r['source_counter'],{'action':'preserve'})
        for flag in m.FLAGS:self.assertFalse(r[flag])
        self.assertIn('Second words.',(self.base/'short/captions.vtt').read_text())
        preview = self.base/'short/index.html'
        page = preview.read_text(encoding='utf-8')
        self.assertEqual(r['preview_sha256'], m.digest(preview))
        self.assertEqual(r['preview_caption_mode'], 'sidecar')
        self.assertEqual(r, json.loads((self.base/'short/short.json').read_text()))
        self.assertIn('<video controls playsinline preload="metadata" src="video.mp4">', page)
        self.assertIn('<track kind="captions" src="captions.vtt"', page)
        self.assertIn('href="captions.vtt" download', page)
        self.assertNotRegex(page, r'(?:src|href)="(?:[a-z]+:|/)')
        for key in ('candidate_sha256', 'caption_sha256', 'automated_review_sha256',
                    'parent_candidate_sha256', 'parent_cycle_sha256', 'source_caption_sha256'):
            self.assertIn(r[key], page)

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
        preview = burned/'index.html'
        page = preview.read_text(encoding='utf-8')
        self.assertEqual(b['preview_caption_mode'], 'burned')
        self.assertEqual(b['preview_sha256'], m.digest(preview))
        self.assertIn('playsinline', page)
        self.assertIn('href="captions.vtt" download', page)
        self.assertNotIn('<track', page)
        self.assertIn(b['candidate_sha256'], page)
        self.assertNotIn(a['candidate_sha256'], page)

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
            rejected = [('WEBVTT\n\n','timed cues')]
            for cue in ('<b>First</b>', '&lt;b&gt;First&lt;/b&gt;', r'{\pos(1,1)}First',
                        '&amp;#x27;', '&#60;First', 'First & second'):
                rejected.append((VTT.replace('First words.', cue), 'unmarked'))
            for captions, reason in rejected:
                with self.subTest(captions=captions):
                    (self.source/'captions.vtt').write_text(captions)
                    with self.assertRaisesRegex(ValueError,reason):
                        m.make_short(self.root,self.base/'unused',start=0,end=1,compact_captions=True)
                    self.assertFalse((self.base/'unused').exists())

    def test_compact_burn_accepts_renderer_quote_escapes_and_keeps_sidecar_bytes(self):
        self.media('720x1280'); self.known_layout()
        cue = """It's "ready"."""
        escaped = VTT.replace('First words.', escape(cue))
        literal = VTT.replace('First words.', cue)
        source = self.source/'captions.vtt'
        with patch.object(m,'inspect_cycle',return_value=self.snapshot):
            source.write_text(escaped)
            bound_source = m.digest(source)
            result = m.make_short(self.root,self.base/'escaped',start=0,end=1,compact_captions=True)
            self.assertEqual(m.digest(source), bound_source)
            source.write_text(literal)
            control = m.make_short(self.root,self.base/'literal',start=0,end=1,compact_captions=True)
        self.assertEqual(result['status'], 'AWAITING_REVIEW', result)
        self.assertEqual(control['status'], 'AWAITING_REVIEW', control)
        self.assertEqual(result['decoded_picture_sha256'], control['decoded_picture_sha256'])
        self.assertEqual(result['source_caption_sha256'], bound_source)
        escaped_sidecar = self.base/'escaped/captions.vtt'
        self.assertEqual(escaped_sidecar.read_text(), m.clip_captions(escaped, 0, 1000)[0])
        self.assertEqual(result['caption_sha256'], m.digest(escaped_sidecar))

    def test_counter_rectangle_contains_maximum_renderer_counter_without_headline(self):
        from PIL import Image, ImageDraw, ImageFont
        from integrations.content_control.cycle_render import FONT
        draw=ImageDraw.Draw(Image.new('RGB',(720,1280)))
        for counter in ('1/1','1/30','30/30'):
            a,b,c,d=draw.textbbox((660,50),counter,font=ImageFont.truetype(FONT,22),anchor='rt')
            self.assertGreaterEqual(a,570);self.assertGreaterEqual(b,40)
            self.assertLessEqual(c,680);self.assertLessEqual(d,85)
        self.assertLess(85,105)  # Existing headline begins at y105.

    def test_captions_end_at_shorter_encoded_picture_or_container_duration(self):
        def fake_run(command, deadline):
            if command[0] == 'ffmpeg' and '-c:v' in command:
                Path(command[-1]).write_bytes(b'synthetic media')
            return b''
        for label, picture, container in [('picture', Fraction(145, 100), 1.5),
                                          ('container', Fraction(15, 10), 1.45)]:
            output = self.base / label
            source = {'width': 90, 'height': 160, 'duration_seconds': 3}
            actual = {**source, 'duration_seconds': container, 'picture_duration_seconds': picture}
            with self.subTest(shorter=label), patch.object(m, 'inspect_cycle', return_value=self.snapshot), \
                 patch.object(m, '_probe', side_effect=[source, actual]), patch.object(m, '_run', side_effect=fake_run), \
                 patch.object(m, 'media_identities', return_value=({'video':'1'*64,'audio':'2'*64},'3'*64)):
                result = m.make_short(self.root, output, start=.5, end=2)
                self.assertEqual(result['status'], 'AWAITING_REVIEW', result)
                self.assertIn('00:00:01.450', (output/'captions.vtt').read_text())
                self.assertNotIn('00:00:01.500', (output/'captions.vtt').read_text())

    def test_bounds_existing_paths_and_symlinks_rejected(self):
        for a,b in [(0,61),(float('nan'),2),(-1,1),(1,1),(False,2)]:
            with self.assertRaises(ValueError):m.make_short(self.root,self.base/'unused',start=a,end=b)
        out=self.base/'existing';out.mkdir()
        with self.assertRaises(ValueError):m.make_short(self.root,out,start=0,end=1)
        link=self.base/'link';link.symlink_to(self.root)
        with self.assertRaises(ValueError):m.make_short(link,self.base/'unused',start=0,end=1)

    def test_real_fractional_frame_tail_cannot_exceed_short_limit(self):
        with patch.object(m, 'inspect_cycle', return_value=self.snapshot):
            self.media(rate='24000/1001', duration=60.2)
            overshoot = m.make_short(self.root, self.base/'overshoot', start=0, end=60, timeout=30)
            self.media(duration=60.2)
            exact = m.make_short(self.root, self.base/'exact', start=0, end=60, timeout=30)

        self.assertEqual(overshoot['status'], 'BLOCKED', overshoot)
        self.assertIn('60-second Short limit', overshoot['reason'])
        self.assertEqual(json.loads((self.base/'overshoot/short.json').read_text()), overshoot)
        self.assertNotIn('candidate_sha256', overshoot)
        self.assertFalse((self.base/'overshoot/index.html').exists())
        self.assertGreater(overshoot['encoded_picture_duration_seconds'], 60)
        self.assertEqual(exact['status'], 'AWAITING_REVIEW', exact)
        self.assertEqual(exact['media']['duration_seconds'], 60)
        self.assertEqual(exact['encoded_picture_duration_seconds'], 60)

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


    def test_preview_is_blocked_when_a_bound_output_changes_after_diagnostics(self):
        self.media()
        write_review = cycle_av_review.write_automated_review
        for filename, reason in (
                ('video.mp4', 'changed before preview'),
                ('captions.vtt', 'changed before preview'),
                ('automated-review.json', 'does not match the unpublished candidate and captions')):
            with self.subTest(filename=filename):
                output = self.base/filename

                def change_after_write(*args, **kwargs):
                    write_review(*args, **kwargs)
                    path = output/filename
                    if filename == 'automated-review.json':
                        report = json.loads(path.read_text())
                        report['caption_sha256'] = 'f'*64
                        path.write_text(json.dumps(report))
                    else:
                        with path.open('ab') as stream:
                            stream.write(b'changed')

                with patch.object(m, 'inspect_cycle', return_value=self.snapshot), \
                     patch.object(cycle_av_review, 'write_automated_review', side_effect=change_after_write):
                    receipt = m.make_short(self.root, output, start=0, end=2, timeout=30)
                self.assertEqual(receipt['status'], 'BLOCKED', receipt)
                self.assertIn(reason, receipt['reason'])
                self.assertNotIn('preview_sha256', receipt)
                self.assertFalse((output/'index.html').exists())
                self.assertEqual(receipt, json.loads((output/'short.json').read_text()))


if __name__=='__main__':unittest.main()
