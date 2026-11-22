"""Synthetic media verifies immutable caption repair, never audiovisual acceptance."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from integrations.content_control import cycle_caption_revision as m
from integrations.content_control.cycle_editorial import compile_editorial
from integrations.content_control.cycle_package import package_cycle, editorial_digest
from integrations.content_control.cycle_checkpoint import create_checkpoint, restore_checkpoint
from integrations.content_control.test_cycle_editorial import brief

VTT=b'WEBVTT\n\n00:00:00.000 --> 00:00:00.900\nthan a purchase posts.\n\n'


class CaptionRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory();cls.media=Path(cls.shared.name)/'video.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=white:s=90x160:r=24:d=1',
                        '-f','lavfi','-i','anullsrc=r=24000:cl=mono','-t','1','-c:v','libx264',
                        '-threads','1','-c:a','aac',str(cls.media)],check=True,timeout=30)

    @classmethod
    def tearDownClass(cls):cls.shared.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'cycle';self.root.mkdir();render=self.root/'render';render.mkdir()
        m._write(self.root/'brief.json',brief());editorial=compile_editorial(brief());m._write(self.root/'editorial.json',editorial)
        shutil.copyfile(self.media,render/'video.mp4');(render/'captions.vtt').write_bytes(VTT)
        self.candidate=m.digest(render/'video.mp4')
        rendered={'schema_version':1,'status':'AWAITING_REVIEW','technical_status':'PASS',**m.FLAGS,
                  'candidate_sha256':self.candidate,'caption_sha256':m.digest(render/'captions.vtt'),
                  'editorial_sha256':editorial_digest(editorial),'independent_transcription_verified':True,
                  'transcription_receipt_sha256':'a'*64,'caption_timing':'observed_word_timestamps'}
        m._write(render/'render.json',rendered)
        p=package_cycle(editorial,render,self.root/'delivery')
        m._write(self.root/'cycle.json',{'schema_version':1,'status':'AWAITING_REVIEW','technical_status':'PASS',**m.FLAGS,
                 'candidate_sha256':self.candidate,'brief_sha256':m.digest(self.root/'brief.json'),
                 'editorial_sha256':m.digest(self.root/'editorial.json'),'package_sha256':m.digest(self.root/'delivery/package.json'),
                 'archive_sha256':p['archive_sha256'],'finished_at':'2026-01-04T00:00:00+00:00'})
        self.edits={'candidate_sha256':self.candidate,'caption_sha256':m.digest(render/'captions.vtt'),
                    'reviewer':'Synthetic fixture reviewer','rationale':'Explicit fixture text correction, no audio review.',
                    'edits':[{'cue':1,'before':'than a purchase posts.','after':'Then a purchase posts.'}]}
        self.source=self.base/'edits.json';m._write(self.source,self.edits);self.out=self.base/'corrected'

    def test_actual_package_and_checkpoint_keep_source_unchanged(self):
        before=m.inspect_cycle(self.root);result=m.revise_captions(self.root,self.source,self.out)
        self.assertEqual(result['status'],'AWAITING_REVIEW',result)
        self.assertEqual(m.inspect_cycle(self.root),before)
        self.assertEqual(m.digest(self.out/'render/video.mp4'),self.candidate)
        self.assertEqual((self.out/'render/captions.vtt').read_bytes(),VTT.replace(b'than',b'Then'))
        for name in ('brief.json','editorial.json'):self.assertEqual((self.out/name).read_bytes(),(self.root/name).read_bytes())
        r=json.loads((self.out/'render/render.json').read_text());p=json.loads((self.out/'delivery/package.json').read_text())
        self.assertFalse(r['independent_transcription_verified']);self.assertFalse(p['independent_transcription_verified'])
        self.assertNotIn('transcription_receipt_sha256',r)
        self.assertEqual(r['caption_revision']['prior_asr_receipt_sha256'],'a'*64)
        self.assertFalse(result['full_av_review']);self.assertNotEqual(result['package_sha256'],before['cycle']['package_sha256'])
        checkpoint=self.base/'checkpoint.zip';c=create_checkpoint(self.out,checkpoint)
        restore_checkpoint(checkpoint,self.base/'restored',expected_sha256=c['checkpoint_sha256'])
        self.assertEqual(m.inspect_cycle(self.out),m.inspect_cycle(self.base/'restored'))

    def test_bad_bindings_and_text_fail_before_output(self):
        cases=[]
        for key in ('candidate_sha256','caption_sha256'):
            v=copy.deepcopy(self.edits);v[key]='0'*64;cases.append(v)
        for field,value in [('cue',2),('cue',True),('before','not matching'),('after',''),('after','<b>Then</b>'),
                            ('after','00:00:00.000 --> 00:00:01.000\nInjected'),('after','than a purchase posts.')]:
            v=copy.deepcopy(self.edits);v['edits'][0][field]=value;cases.append(v)
        v=copy.deepcopy(self.edits);v['edits']*=2;cases.append(v)
        for value in cases:
            m._write(self.source,value)
            with self.assertRaises(ValueError):m.revise_captions(self.root,self.source,self.out)
            self.assertFalse(self.out.exists())

    def test_duplicate_json_and_unsafe_paths_rejected(self):
        self.source.write_text('{"candidate_sha256":"a","candidate_sha256":"b"}')
        with self.assertRaises(ValueError):m.revise_captions(self.root,self.source,self.out)
        m._write(self.source,self.edits)
        with self.assertRaises(ValueError):m.revise_captions(self.root,self.source,self.root/'nested')
        self.out.mkdir()
        with self.assertRaises(ValueError):m.revise_captions(self.root,self.source,self.out)
        link=self.base/'link';link.symlink_to(self.source)
        with self.assertRaises(ValueError):m.revise_captions(self.root,link,self.base/'new')

    def test_input_mutation_blocks_result(self):
        original=m.package_cycle
        def mutate(*args,**kwargs):
            result=original(*args,**kwargs);self.source.write_text('{}');return result
        with patch.object(m,'package_cycle',side_effect=mutate):
            r=m.revise_captions(self.root,self.source,self.out)
        self.assertEqual(r['status'],'BLOCKED');self.assertIn('inputs changed',r['reason'])

    def test_source_mutation_blocks_result(self):
        original=m.package_cycle
        def mutate(*args,**kwargs):
            result=original(*args,**kwargs)
            (self.root/'delivery/captions.vtt').write_bytes(b'changed')
            return result
        with patch.object(m,'package_cycle',side_effect=mutate):
            r=m.revise_captions(self.root,self.source,self.out)
        self.assertEqual(r['status'],'BLOCKED');self.assertIn('changed',r['reason'])


if __name__=='__main__':unittest.main()
