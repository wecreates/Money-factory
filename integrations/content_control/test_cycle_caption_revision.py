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

    def test_duration_evidence_survives_caption_only_revision(self):
        from integrations.content_control.cycle_job import check_completed
        source_brief = brief()
        source_brief['portrait_handoff'] = {
            **{f'{name}_sha256': 'a' * 64 for name in ('candidate','cycle','brief','package','render')},
            'scenes': [{'scene_id': scene['id'], 'start_seconds': index, 'end_seconds': index+1}
                       for index, scene in enumerate(source_brief['scenes'])],
        }
        m._write(self.root/'brief.json', source_brief)
        render_path = self.root/'render/render.json'
        rendered = json.loads(render_path.read_text())
        container = json.loads((self.root/'delivery/package.json').read_text())['media']['duration_seconds']
        rendered.update(maximum_duration_seconds=60, measured_narration_frame_budget=24,
                        encoded_picture_duration_seconds=1, encoded_container_duration_seconds=container)
        m._write(render_path, rendered)
        (self.root/'delivery').rename(self.base/'initial-delivery')
        packaged = package_cycle(compile_editorial(source_brief), self.root/'render', self.root/'delivery')
        cycle_path = self.root/'cycle.json'
        cycle = json.loads(cycle_path.read_text())
        cycle.update(maximum_duration_seconds=60, brief_sha256=m.digest(self.root/'brief.json'),
                     package_sha256=m.digest(self.root/'delivery/package.json'), archive_sha256=packaged['archive_sha256'])
        m._write(cycle_path, cycle)
        result = m.revise_captions(self.root, self.source, self.out)
        self.assertEqual(result['status'], 'AWAITING_REVIEW', result)
        self.assertEqual(check_completed(self.out, cycle['brief_sha256'], require_portrait_duration=True)
                         ['maximum_duration_seconds'], 60)

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
        review = json.loads((self.base/'restored/delivery/automated-review.json').read_text())
        self.assertEqual(review['candidate_sha256'], self.candidate)
        self.assertEqual(review['caption_sha256'], m.digest(self.out/'render/captions.vtt'))

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

    def test_retime_packages_a_new_caption_identity_and_keeps_media(self):
        original = m.inspect_cycle(self.root)
        revised = VTT.replace(b'than a purchase posts.', b'than a\npurchase posts.')
        del self.edits['edits']
        self.edits['retimed_vtt'] = revised.decode()
        m._write(self.source, self.edits)
        result = m.revise_captions(self.root, self.source, self.out)
        self.assertEqual(result['status'], 'AWAITING_REVIEW', result)
        self.assertEqual(result['operation'], 'caption_timing_revision')
        self.assertEqual((self.out/'render/captions.vtt').read_bytes(), revised)
        self.assertEqual(m.inspect_cycle(self.root), original)
        current = m.inspect_cycle(self.out)
        self.assertEqual(current['candidate_sha256'], original['candidate_sha256'])
        for name in ('delivery/captions.vtt', 'delivery/package.json', 'delivery/automated-review.json'):
            self.assertNotEqual(current['files_sha256'][name], original['files_sha256'][name])
        review = json.loads((self.out/'delivery/automated-review.json').read_text())
        self.assertFalse(review['full_audiovisual_review_verified'])
        self.assertEqual(review['caption_sha256'], current['files_sha256']['delivery/captions.vtt'])

    def test_retime_only_between_adjacent_cues(self):
        first = ('00:00:00.000 --> 00:00:00.500\nOne two\n\n'
                 '00:00:00.500 --> 00:00:00.900\nthree four.\n\n')
        later = '00:00:01.500 --> 00:00:02.000\nFive.\n\n'
        before = ('WEBVTT\n\n' + first + later).encode()
        after = ('WEBVTT\n\n00:00:00.000 --> 00:00:00.700\nOne two three\n\n'
                 '00:00:00.700 --> 00:00:00.900\nfour.\n\n' + later)
        self.assertEqual(m.retime_vtt(before, after), after.encode())
        for invalid in (before.decode(), after.replace('three', 'three!'), after.replace('two three', 'three two'),
                        after.replace('00:00:00.900', '00:00:01.500'),
                        after.replace('00:00:01.500', '00:00:00.800'),
                        after.replace('00:00:00.700 -->', '00:00:00.800 -->'),
                        after.replace('One two', '<b>One</b> two')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                m.retime_vtt(before, invalid)

    def test_text_correction_to_retimed_multiline_cue_needs_explicit_line(self):
        multiline = VTT.replace(b'than a purchase posts.', b'than a\npurchase posts.')
        edit = {'cue': 1, 'before': 'purchase posts.', 'after': 'purchase appears.'}
        with self.assertRaisesRegex(ValueError, 'explicit line'):
            m.correct_vtt(multiline, [edit])
        self.assertEqual(m.correct_vtt(multiline, [dict(edit, line=2)]),
                         multiline.replace(b'purchase posts.', b'purchase appears.'))

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

    def test_unbound_caption_bytes_fail_before_repair(self):
        snapshot = m.inspect_cycle(self.root)
        (self.root/'delivery/captions.vtt').write_bytes(VTT.replace(b'than', b'Then'))
        with patch.object(m, 'inspect_cycle', return_value=snapshot):
            with self.assertRaisesRegex(ValueError, 'Source captions changed'):
                m.revise_captions(self.root, self.source, self.out)
        self.assertFalse(self.out.exists())


if __name__=='__main__':unittest.main()
