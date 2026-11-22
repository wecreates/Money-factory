"""Synthetic bytes exercise delivery identity/failure rules, never media quality."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from integrations.content_control import review_package as m


def fixture(root):
    root.mkdir()
    for name,data in {'video.mp4':b'synthetic video','captions.vtt':b'WEBVTT\n','video.mp4.json':b'{}','REVIEW.md':b'Review pending'}.items():
        (root/name).write_bytes(data)
    run={'status':'AWAITING_REVIEW','technical_status':'PASS','publication_enabled':False,'production_approved':False,
         'full_av_review':False,'candidate_sha256':m.digest(root/'video.mp4'),'caption_sha256':m.digest(root/'captions.vtt'),
         'artifacts_sha256':{p.name:m.digest(p) for p in root.iterdir()}}
    (root/'run.json').write_text(json.dumps(run))
    return run


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.review=self.root/'source';self.run=fixture(self.review)
    def export(self,output=None,**kwargs):
        return m.package_review(self.review,output or self.root/'delivery',expected_run_sha256=m.digest(self.review/'run.json'),
            expected_candidate_sha256=self.run['candidate_sha256'],provenance={'test':'synthetic'},**kwargs)
    def test_playable_layout_portable_zip_and_source_unchanged(self):
        before={p.name:m.digest(p) for p in self.review.iterdir()}
        result=self.export()
        self.assertFalse(result['production_approved']);self.assertFalse(result['publication_enabled'])
        page=(self.root/'delivery/review/index.html').read_text()
        self.assertIn('src="video.mp4"',page);self.assertNotIn('http',page)
        with zipfile.ZipFile(self.root/'delivery/review-package.zip') as z:
            self.assertEqual(z.namelist().count('review/video.mp4'),1)
            self.assertEqual(z.read('review/video.mp4'),b'synthetic video')
        self.assertEqual(before,{p.name:m.digest(p) for p in self.review.iterdir()})
    def test_tampered_source_rejected(self):
        (self.review/'video.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.export()
    def test_reserved_recorded_filename_rejected(self):
        (self.review/'index.html').write_text('must not overwrite')
        self.run['artifacts_sha256']['index.html']=m.digest(self.review/'index.html')
        (self.review/'run.json').write_text(json.dumps(self.run))
        with self.assertRaisesRegex(ValueError,'Reserved'):self.export()
    def test_unrecorded_and_missing_artifact_rejected(self):
        (self.review/'extra').write_text('no')
        with self.assertRaisesRegex(ValueError,'Unrecorded'):self.export()
        (self.review/'extra').unlink();(self.review/'captions.vtt').unlink()
        with self.assertRaises(OSError):self.export()
    def test_input_output_ancestor_symlinks_rejected(self):
        (self.root/'link').symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'Symlink'):self.export(self.root/'link/delivery')
        self.review=self.root/'link/source'
        with self.assertRaisesRegex(ValueError,'Symlink'):self.export()
    def test_nested_output_and_collision_rejected(self):
        with self.assertRaisesRegex(ValueError,'outside input'):self.export(self.review/'new-output')
        with self.assertRaisesRegex(ValueError,'outside input'):self.export(self.root/'source/../source/new-output')
        (self.root/'delivery').mkdir()
        with self.assertRaisesRegex(ValueError,'exists'):self.export()
    def test_copy_failure_retains_source(self):
        with patch.object(m,'copy_file',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.export()
        self.assertFalse((self.root/'delivery').exists());self.assertTrue((self.review/'video.mp4').exists())
    def test_expired_deadline_and_mid_copy_timeout_refused(self):
        import io,time
        with self.assertRaises(TimeoutError): self.export(deadline=time.monotonic()-1)
        self.assertFalse((self.root/'delivery').exists())
        incoming=io.BytesIO(b'x'*(2*1024*1024));outgoing=io.BytesIO()
        with patch.object(m.time,'monotonic',side_effect=[0,2]):
            with self.assertRaises(TimeoutError):m.copy_chunks(incoming,outgoing,1)
        self.assertEqual(len(outgoing.getvalue()),1024*1024)

    def test_true_approval_rejected(self):
        self.run['full_av_review']=True;(self.review/'run.json').write_text(json.dumps(self.run))
        with self.assertRaisesRegex(ValueError,'flags'):self.export()
    def test_optional_export_wrong_candidate_rejected(self):
        edit=self.root/'edit';edit.mkdir()
        (edit/'export-receipt.json').write_text(json.dumps({'status':'INTERCHANGE_VERIFIED','roundtrip_verified':True,
            'candidate_sha256':'0'*64,'input_run_sha256':m.digest(self.review/'run.json')}))
        with self.assertRaisesRegex(ValueError,'OTIO source'):self.export(edit_dir=edit)
        self.assertFalse((self.root/'delivery').exists())


if __name__=='__main__':unittest.main()
