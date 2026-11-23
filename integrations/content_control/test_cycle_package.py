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
        self.assertNotIn('layout', result)
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
        self.assertIn('href="automated-review.json"', page)
        self.assertIn('transcript', page)
        diagnostics = json.loads((self.root / 'package/automated-review.json').read_text())
        self.assertEqual(diagnostics['candidate_sha256'], result['candidate_sha256'])
        self.assertEqual(diagnostics['caption_sha256'], result['caption_sha256'])
        self.assertEqual(diagnostics['watcher']['status'], 'SIGNALS_MEASURED')
        self.assertGreaterEqual(diagnostics['listener']['silence_seconds'], .9)
        self.assertEqual(diagnostics['reviewer']['status'], 'FULL_REVIEW_REQUIRED')
        self.assertFalse(diagnostics['competitor_audiovisual_comparison_verified'])
        with zipfile.ZipFile(self.root / 'package/review-package.zip') as archive:
            self.assertEqual(archive.testzip(), None)
            self.assertIn('package.json', archive.namelist())
            self.assertIn('automated-review.json', archive.namelist())
            self.assertNotIn('review-package.zip', archive.namelist())

    def test_native_landscape_binds_layout_and_uses_uncropped_frames(self):
        target = self.render / 'video.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i',
                        'color=c=white:s=1280x720:r=12:d=1', '-f', 'lavfi', '-i',
                        'anullsrc=r=24000:cl=mono', '-t', '1', '-c:v', 'libx264',
                        '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(target)],
                       check=True, capture_output=True, timeout=30)
        self.editorial['layout'] = 'landscape'
        self.receipt.update(candidate_sha256=m.digest(target),
                            editorial_sha256=m.editorial_digest(self.editorial))
        self.save_receipt()
        with self.assertRaisesRegex(ValueError, 'landscape layouts must match'):
            self.export()
        self.assertFalse((self.root / 'package').exists())
        self.receipt['layout'] = 'landscape'
        self.save_receipt()
        result = self.export()
        self.assertEqual(result['layout'], 'landscape')
        self.assertEqual(result['candidate_sha256'], m.digest(target))
        self.assertEqual((result['media']['width'], result['media']['height']), (1280, 720))
        for t in result['thumbnails']:
            self.assertEqual(t['framing'], 'full_frame')
            self.assertIsNone(t['source_crop_pixels'])
            self.assertEqual(t['source_frame_size'], [1280, 720])

    def test_landscape_layout_rejects_portrait_raster(self):
        self.editorial['layout'] = 'landscape'
        self.receipt.update(layout='landscape', editorial_sha256=m.editorial_digest(self.editorial))
        self.save_receipt()
        with self.assertRaisesRegex(ValueError, 'Native 1280x720'):
            self.export()
        self.assertFalse((self.root / 'package').exists())

    def test_focus_crop_requires_known_renderer_and_records_fallback(self):
        media = {'width': 720, 'height': 1280}
        receipt = {'scope': 'Fresh offline speech and original diagram-based picture video; technical verification only.'}
        editorial = {'scenes': [{'visual_spec': {'kind': 'comparison'}}]}
        self.assertEqual(m.diagram_thumbnail_crop(editorial, receipt, media), (45, 300, 675, 870))
        for unknown in ({}, {'scope': 'unrelated portrait renderer'}):
            self.assertIsNone(m.diagram_thumbnail_crop(editorial, unknown, media))
        self.assertIsNone(m.diagram_thumbnail_crop(editorial, receipt, {'width': 1280, 'height': 720}))
        self.assertIsNone(m.diagram_thumbnail_crop({'scenes': [{}]}, receipt, media))
        result = self.export()
        self.assertTrue(all(t['framing'] == 'full_frame' and t['source_crop_pixels'] is None
                            and t['source_frame_size'] == [160, 240] and t['source_crop_omissions'] == []
                            for t in result['thumbnails']))
        self.assertIn('(complete frame)', (self.root / 'package/index.html').read_text())
        focused = dict(result['thumbnails'][0], framing='diagram_focus')
        self.assertIn('omits source headline, scene counter, character and speaker label',
                      m._page(self.editorial, [focused], self.receipt['candidate_sha256']))

    def test_diagram_focus_does_not_crop_the_opted_speaker_label_into_thumbnails(self):
        media = {'width': 720, 'height': 1280}
        receipt = {'scope': 'Fresh offline speech and original diagram-based picture video; technical verification only.',
                   'speaker_label_position': 'above'}
        editorial = {'scenes': [{'visual_spec': {'kind': 'checklist'}}], 'speaker_label_position': 'above'}
        self.assertEqual(m.diagram_thumbnail_crop(editorial, receipt, media), (45, 300, 675, 800))
        del receipt['speaker_label_position']
        with self.assertRaisesRegex(ValueError, 'positions must match'):
            m.diagram_thumbnail_crop(editorial, receipt, media)

    def test_independent_copy_changes_thumbnail_and_preserves_title_and_media(self):
        baseline = self.export()
        self.assertNotIn('thumbnail_copy', baseline)
        self.editorial['thumbnail_copy'] = 'Fee < Myth?'
        self.receipt['editorial_sha256'] = m.editorial_digest(self.editorial)
        self.save_receipt()
        revised_path = self.root / 'revised'
        with patch.object(m, 'make_thumbnail', wraps=m.make_thumbnail) as draw_overlay:
            revised = self.export(revised_path)
        self.assertEqual([call.args[2] for call in draw_overlay.call_args_list], ['Fee < Myth?'] * 3)
        self.assertEqual(revised['thumbnail_copy'], 'Fee < Myth?')
        self.assertEqual(revised['candidate_sha256'], baseline['candidate_sha256'])
        self.assertEqual(revised['caption_sha256'], baseline['caption_sha256'])
        for old, new in zip(baseline['thumbnails'], revised['thumbnails']):
            self.assertNotEqual(old['sha256'], new['sha256'])
            self.assertEqual(new['sha256'], m.digest(revised_path / new['file']))
        page = (revised_path / 'index.html').read_text()
        self.assertIn('<h1>The fee trap</h1>', page)
        self.assertIn('Thumbnail copy: Fee &lt; Myth?', page)

    def test_explicit_crop_enlarges_diagram_and_rejects_out_of_bounds(self):
        from PIL import Image, ImageDraw
        source = self.root / 'panel.png'
        image = Image.new('RGB', (720, 1280), 'red')
        ImageDraw.Draw(image).rectangle((45, 300, 674, 869), fill='blue')
        image.save(source)
        full, focused = self.root / 'full.png', self.root / 'focused.png'
        m.make_thumbnail(source, full, 'A title', 0)
        m.make_thumbnail(source, focused, 'A title', 0, source_crop=(45, 300, 675, 870))
        with Image.open(full) as a, Image.open(focused) as b:
            # Known diagram fills more pixels; header/background is not retained.
            blue_a = sum(pixel == (0, 0, 255) for pixel in a.getdata())
            blue_b = sum(pixel == (0, 0, 255) for pixel in b.getdata())
            self.assertGreater(blue_b, blue_a * 3)
            self.assertNotIn((255, 0, 0), b.getdata())
        for crop in ((-1, 0, 720, 1280), (0, 0, 721, 1280), (0, 0, 0, 10)):
            with self.assertRaisesRegex(ValueError, 'crop'):
                m.make_thumbnail(source, focused, 'A title', 0, source_crop=crop)

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
