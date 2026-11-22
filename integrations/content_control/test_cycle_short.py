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

    def media(self):
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=90x160:r=24:d=3',
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
        for flag in m.FLAGS:self.assertFalse(r[flag])
        self.assertIn('Second words.',(self.base/'short/captions.vtt').read_text())

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
