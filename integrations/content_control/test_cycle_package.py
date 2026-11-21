"""Actual small media exercises packaging, identity failures and HTML escaping."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from integrations.content_control import cycle_package as m


class CyclePackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_temp = tempfile.TemporaryDirectory()
        cls.media = Path(cls.media_temp.name) / 'video.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                        'color=c=white:s=160x240:r=12:d=1', '-f', 'lavfi', '-i',
                        'anullsrc=r=24000:cl=mono', '-t', '1', '-c:v', 'libx264',
                        '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(cls.media)],
                       check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.media_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.render = self.root / 'render'; self.render.mkdir()
        shutil.copyfile(self.media, self.render / 'video.mp4')
        (self.render / 'captions.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:00.900\nTest.\n')
        self.editorial = {'title': 'The fee trap', 'topic': 'Finance', 'scenes': [
            {'id': 's1', 'narration': '<script>alert(1)</script>', 'visual': 'Dave considers a card.'}],
            'sources': [{'id': 's1', 'url': 'https://example.com/research', 'claim': 'Test claim',
                         'retrieved_at': '2026-11-21T12:00:00+00:00'}],
            'reference_observations': [{'url': 'https://example.com/reference', 'observation_type': 'transcript',
                                        'observed_at': '2026-11-21T12:00:00+00:00', 'patterns': ['Immediate conflict']}]}
        self.receipt = {'technical_status': 'PASS', 'candidate_sha256': m.digest(self.render / 'video.mp4'),
                        'caption_sha256': m.digest(self.render / 'captions.vtt'),
                        'editorial_sha256': m.editorial_digest(self.editorial),
                        'publication_enabled': False, 'production_approved': False, 'full_av_review': False}
        self.save_receipt()

    def save_receipt(self):
        (self.render / 'render.json').write_text(json.dumps(self.receipt))

    def export(self, target=None):
        return m.package_cycle(self.editorial, self.render, target or self.root / 'package')

    def test_real_decode_thumbnails_bindings_and_portable_archive(self):
        result = self.export()
        self.assertEqual(result['status'], 'AWAITING_REVIEW')
        self.assertFalse(result['full_av_review'])
        self.assertFalse(result['thumbnail_performance_verified'])
        self.assertEqual(len(result['thumbnails']), 3)
        for thumbnail in result['thumbnails']:
            self.assertTrue(0 < thumbnail['source_timestamp_seconds'] < result['media']['duration_seconds'])
            self.assertEqual(thumbnail['sha256'], m.digest(self.root / 'package' / thumbnail['file']))
        for name, sha in result['files_sha256'].items():
            self.assertEqual(sha, m.digest(self.root / 'package' / name))
        page = (self.root / 'package/index.html').read_text()
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('src="video.mp4"', page)
        self.assertIn('transcript', page)
        with zipfile.ZipFile(self.root / 'package/review-package.zip') as archive:
            self.assertEqual(archive.testzip(), None)
            self.assertIn('package.json', archive.namelist())
            self.assertNotIn('review-package.zip', archive.namelist())

    def test_modified_video_captions_or_editorial_rejected(self):
        for target, expected in [('video.mp4', 'Candidate'), ('captions.vtt', 'Caption')]:
            path = self.render / target
            old = path.read_bytes(); path.write_bytes(old + b'changed')
            with self.assertRaisesRegex(ValueError, expected): self.export()
            path.write_bytes(old)
        self.editorial['title'] = 'Unbound title'
        with self.assertRaisesRegex(ValueError, 'Editorial'): self.export()
        self.assertFalse((self.root / 'package').exists())

    def test_matching_hash_does_not_accept_corrupt_media(self):
        (self.render / 'video.mp4').write_bytes(b'not a real mp4')
        self.receipt['candidate_sha256'] = m.digest(self.render / 'video.mp4'); self.save_receipt()
        with self.assertRaises(RuntimeError): self.export()

    def test_enabled_publication_or_quality_approval_rejected(self):
        for name in ('publication_enabled', 'production_approved', 'full_av_review'):
            self.receipt[name] = True; self.save_receipt()
            with self.assertRaisesRegex(ValueError, 'flags'): self.export()
            self.receipt[name] = False

    def test_active_source_url_rejected(self):
        self.editorial['sources'][0]['url'] = 'javascript:alert(1)'
        self.receipt['editorial_sha256'] = m.editorial_digest(self.editorial); self.save_receipt()
        with self.assertRaisesRegex(ValueError, 'HTTPS'): self.export()
        self.assertFalse((self.root / 'package').exists())

    def test_output_collision_symlinks_and_nested_target_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside'): self.export(self.render / 'package')
        (self.root / 'package').mkdir()
        with self.assertRaisesRegex(ValueError, 'exists'): self.export()
        (self.root / 'link').symlink_to(self.render, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            m.package_cycle(self.editorial, self.root / 'link', self.root / 'other')

    def test_failed_thumbnail_removes_only_partial_package(self):
        with patch.object(m, 'make_thumbnail', side_effect=RuntimeError('thumbnail failure')):
            with self.assertRaisesRegex(RuntimeError, 'thumbnail failure'): self.export()
        self.assertFalse((self.root / 'package').exists())
        self.assertTrue((self.render / 'video.mp4').is_file())

    def test_expired_deadline_and_environment_locks(self):
        with self.assertRaises(TimeoutError):
            m.package_cycle(self.editorial, self.render, self.root / 'package', deadline=time.monotonic() - 1)
        for key in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED'):
            with patch.dict(os.environ, {key: 'true'}):
                with self.assertRaisesRegex(ValueError, 'disabled'): self.export()
        self.receipt['paid_generation_enabled'] = True; self.save_receipt()
        with self.assertRaisesRegex(ValueError, 'flags'): self.export()

    def test_process_timeout_uses_remaining_budget(self):
        with patch.object(m.time, 'monotonic', return_value=10), patch.object(m.subprocess, 'run') as launch:
            launch.return_value.stdout = b''
            m.run(['ffprobe', 'example'], timeout=30, deadline=12)
            self.assertEqual(launch.call_args.kwargs['timeout'], 2)
        with patch.object(m.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ffprobe', 1)):
            with self.assertRaises(TimeoutError): m.run(['ffprobe'])


if __name__ == '__main__':
    unittest.main()
