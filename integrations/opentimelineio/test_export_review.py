"""Actual native OTIO/FFmpeg fixture roundtrip; no creative approval implied."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import opentimelineio as otio
from integrations.opentimelineio import export_review as m


class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory()
        cls.media = Path(cls.shared.name)/'fixture.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','color=c=blue:s=32x32:r=24:d=30',
                        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=30',
                        '-threads','1','-c:v','libx264','-c:a','aac','-t','30',str(cls.media)],check=True,timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packet = self.root/'packet'
        self.packet.mkdir()
        shutil.copyfile(self.media,self.packet/'video.mp4')
        (self.packet/'captions.vtt').write_text('WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.860\nSynthetic fixture.\n')
        self.frames = [{'scene':i,'start':i*40,'end':(i+1)*40} for i in range(18)]
        self.renderer = {'kind':'unpublished_picture_cut','video_sha256':m.digest(self.packet/'video.mp4'),
             'caption_sha256':m.digest(self.packet/'captions.vtt'),'frames':self.frames,
             'publication_enabled':False,'production_approved':False}
        self.run = {'status':'AWAITING_REVIEW','technical_status':'PASS','source_inputs_unchanged':True,
             'publication_enabled':False,'production_approved':False,'full_av_review':False,
             'candidate_sha256':self.renderer['video_sha256'],'caption_sha256':self.renderer['caption_sha256']}
        self.refresh()

    def refresh(self):
        (self.packet/'video.mp4.json').write_text(json.dumps(self.renderer))
        self.run['artifacts_sha256']={name:m.digest(self.packet/name) for name in ('video.mp4','video.mp4.json','captions.vtt')}
        (self.packet/'run.json').write_text(json.dumps(self.run))
        self.sha=m.digest(self.packet/'run.json')

    def export(self):
        return m.export(self.packet,self.root/'output',self.sha)

    def test_real_media_roundtrip_and_relocated_relative_references(self):
        before={p.name:m.digest(p) for p in self.packet.iterdir()}
        receipt=self.export()
        self.assertEqual((receipt['cuts'],receipt['caption_markers']),(18,1))
        self.assertEqual(receipt['status'],'INTERCHANGE_VERIFIED')
        self.assertFalse(receipt['production_approved'])
        self.assertFalse(receipt['nle_import_verified'])
        moved=self.root/'relocated'
        (self.root/'output').rename(moved)
        timeline=otio.core.deserialize_json_from_string((moved/'timeline.otio').read_text())
        m.verify_roundtrip(timeline,self.frames,m.caption_markers(moved/'captions.vtt'),self.run['candidate_sha256'])
        for track in timeline.tracks:
            for clip in track:
                self.assertEqual(m.digest(moved/clip.media_reference.target_url),receipt['candidate_sha256'])
        self.assertEqual(before,{p.name:m.digest(p) for p in self.packet.iterdir()})

    def test_truncated_packet_refused_before_output(self):
        (self.packet/'video.mp4.json').unlink()
        with self.assertRaisesRegex(ValueError,'regular file'): self.export()
        self.assertFalse((self.root/'output').exists())

    def test_bad_expected_run_hash(self):
        self.sha='0'*64
        with self.assertRaisesRegex(ValueError,'run.json hash'): self.export()
        self.assertFalse((self.root/'output').exists())

    def test_tampered_media_or_captions_or_render_receipt(self):
        for name in ('video.mp4','captions.vtt','video.mp4.json'):
            with self.subTest(name=name):
                path=self.packet/name
                original=path.read_bytes()
                path.write_bytes(original+b' ')
                with self.assertRaisesRegex(ValueError,'artifact hash'): self.export()
                path.write_bytes(original)

    def test_missing_flags_and_forged_approval_rejected(self):
        original=copy.deepcopy(self.run)
        for key in ('publication_enabled','production_approved','full_av_review'):
            for value in (True,None):
                self.run=copy.deepcopy(original)
                if value is None: del self.run[key]
                else: self.run[key]=value
                self.refresh()
                with self.assertRaisesRegex(ValueError,key): self.export()

    def test_wrong_candidate_binding_rejected(self):
        self.renderer['video_sha256']='0'*64
        self.refresh()
        with self.assertRaisesRegex(ValueError,'renderer binding'): self.export()

    def test_malformed_cuts_rejected_even_if_hashes_updated(self):
        original=copy.deepcopy(self.frames)
        for fields in ({'start':1},{'end':721},{'scene':True}):
            self.renderer['frames']=copy.deepcopy(original)
            self.renderer['frames'][0].update(fields)
            self.refresh()
            with self.assertRaises(ValueError): self.export()

    def test_caption_bounds_rejected(self):
        (self.packet/'captions.vtt').write_text('WEBVTT\n\n1\n00:00:31.000 --> 00:00:32.000\nBad.\n')
        self.renderer['caption_sha256']=self.run['caption_sha256']=m.digest(self.packet/'captions.vtt')
        self.refresh()
        with self.assertRaisesRegex(ValueError,'caption cue'): self.export()

    def test_symlink_and_existing_output_refused(self):
        video=self.packet/'video.mp4'
        video.unlink()
        video.symlink_to(self.media)
        with self.assertRaisesRegex(ValueError,'regular file'): self.export()
        video.unlink()
        shutil.copyfile(self.media,video)
        (self.root/'output').mkdir()
        (self.root/'output'/'keep').write_text('existing')
        with self.assertRaisesRegex(ValueError,'output already exists'): self.export()
        self.assertEqual((self.root/'output'/'keep').read_text(),'existing')

    def test_bad_actual_media_refused_even_with_bound_hash(self):
        (self.packet/'video.mp4').write_bytes(b'not media')
        self.renderer['video_sha256']=self.run['candidate_sha256']=m.digest(self.packet/'video.mp4')
        self.refresh()
        with self.assertRaises(subprocess.CalledProcessError): self.export()
        self.assertFalse((self.root/'output').exists())

    def test_copy_failure_cleans_only_new_output(self):
        with patch.object(m.shutil,'copyfile',side_effect=OSError('disk failure')):
            with self.assertRaisesRegex(OSError,'disk failure'): self.export()
        self.assertFalse((self.root/'output').exists())
        self.assertTrue((self.packet/'video.mp4').exists())

    def test_native_roundtrip_detects_cut_and_caption_corruption(self):
        run,frames,cues=m.validate_packet(self.packet,self.sha)
        tl=m.make_timeline(run,frames,cues,self.sha)
        tl.tracks[0][0].source_range=m.time_range(1,39)
        with self.assertRaises(ValueError):m.verify_roundtrip(tl,frames,cues,run['candidate_sha256'])
        tl=m.make_timeline(run,frames,cues,self.sha)
        tl.tracks[0].markers[0].name='Altered'
        with self.assertRaisesRegex(ValueError,'caption roundtrip'):m.verify_roundtrip(tl,frames,cues,run['candidate_sha256'])


if __name__ == '__main__': unittest.main()
