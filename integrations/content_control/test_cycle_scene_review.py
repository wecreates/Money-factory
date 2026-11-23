"""Synthetic timeline/encoding checks do not establish creative acceptance."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from integrations.content_control import cycle_scene_review as m


class ScenePlanTests(unittest.TestCase):
    def setUp(self):
        self.render = {'scenes': [{'scene_id': 'first', 'start': 0, 'end': 1},
                                  {'scene_id': 'second', 'start': 1, 'end': 2}]}
        self.editorial = {'scenes': [{'id': 'first', 'start_seconds': 0, 'end_seconds': 12},
                                     {'id': 'second', 'start_seconds': 12, 'end_seconds': 24}]}

    def test_uses_measured_intervals_not_planning_times(self):
        result = m.scene_plan(self.render, self.editorial, 2.045)
        self.assertEqual([s['requested_sample_seconds'] for s in result], [.5, 1.5])
        self.assertEqual([s['frame'] for s in result], ['scene-01.png', 'scene-02.png'])

    def test_missing_reordered_and_duplicate_scene_ids_rejected(self):
        for scenes in ([], self.render['scenes'][:1], self.render['scenes'][::-1],
                       [self.render['scenes'][0], dict(self.render['scenes'][1], scene_id='first')]):
            with self.subTest(scenes=scenes), self.assertRaises(ValueError):
                m.scene_plan({'scenes': scenes}, self.editorial, 2)

    def test_invalid_gaps_overlaps_nonfinite_and_incomplete_timelines(self):
        for index, key, value in ((0, 'start', .1), (1, 'start', 1.1), (1, 'start', .9),
                                   (1, 'end', float('nan')), (1, 'end', float('inf')),
                                   (0, 'start', False), (1, 'end', 1.8), (1, 'end', 3),
                                   (1, 'end', 1.01)):
            rendered = copy.deepcopy(self.render); rendered['scenes'][index][key] = value
            with self.subTest(index=index, key=key, value=value), self.assertRaises(ValueError):
                m.scene_plan(rendered, self.editorial, 2)


class SceneSamplingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base / 'cycle'
        self.delivery = self.root / 'delivery'; self.delivery.mkdir(parents=True)
        self.out = self.base / 'samples'
        self.editorial = {'scenes': [{'id': 'first', 'speaker': 'dave', 'narration': '<script>unsafe</script>',
                                      'start_seconds': 0, 'end_seconds': 12},
                                     {'id': 'second', 'speaker': 'points_monk', 'narration': 'Second words.',
                                      'start_seconds': 12, 'end_seconds': 24}]}
        rendered = {'scenes': [{'scene_id': 'first', 'start': 0, 'end': 1},
                                {'scene_id': 'second', 'start': 1, 'end': 2}]}
        (self.delivery / 'render.json').write_text(json.dumps(rendered))
        self.snapshot = {'candidate_sha256': 'a'*64, 'files_sha256': {'cycle.json': 'b'*64},
                         'editorial': self.editorial}

    def media(self, fps=24, size='90x160'):
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'color=red:s={size}:r={fps}:d=1',
                        '-f', 'lavfi', '-i', f'color=blue:s={size}:r={fps}:d=1',
                        '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono',
                        '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]', '-map', '2:a',
                        '-t', '2', '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac',
                        str(self.delivery / 'video.mp4')], check=True)
        self.snapshot['candidate_sha256'] = m.digest(self.delivery / 'video.mp4')

    def test_real_decode_samples_every_scene_and_keeps_source_unchanged(self):
        self.media(); initial = m.digest(self.delivery / 'video.mp4')
        with patch.object(m, 'inspect_cycle', return_value=self.snapshot):
            result = m.make_scene_review(self.root, self.out, timeout=30)
        self.assertEqual(result['status'], 'SCENE_SAMPLES_READY', result)
        self.assertNotIn('layout', result)
        self.assertEqual(result['sampled_scene_count'], 2)
        self.assertEqual(result['candidate_sha256'], initial)
        self.assertEqual(m.digest(self.delivery / 'video.mp4'), initial)
        for name, dominant in [('scene-01.png', 0), ('scene-02.png', 2)]:
            with Image.open(self.out / name) as image:
                self.assertEqual(image.size, (90, 160))
                color = image.getpixel((45, 80)); self.assertGreater(color[dominant], 240)
        for name, sha in result['artifacts_sha256'].items(): self.assertEqual(m.digest(self.out / name), sha)
        for flag in m.FLAGS: self.assertFalse(result[flag])
        self.assertFalse(result['planned_storyboard_times_used'])
        for scene in result['scenes']:
            self.assertLessEqual(scene['requested_sample_seconds'], scene['decoded_frame_pts_seconds'] + .00001)
            self.assertLess(scene['decoded_frame_pts_seconds'], scene['end_seconds'])
        html = (self.out / 'index.html').read_text()
        self.assertIn('&lt;script&gt;unsafe&lt;/script&gt;', html); self.assertNotIn('<script>', html)
        self.assertIn('not burned', html)
        self.assertEqual(json.loads((self.out / 'scene-review.json').read_text()), result)

    def test_opted_landscape_samples_native_frames_and_compact_sheet(self):
        self.media(size='1280x720')
        self.editorial['layout'] = 'landscape'
        manifest = self.delivery / 'render.json'
        render = json.loads(manifest.read_text())
        render['layout'] = 'landscape'
        manifest.write_text(json.dumps(render))
        with patch.object(m, 'inspect_cycle', return_value=self.snapshot):
            result = m.make_scene_review(self.root, self.out, timeout=30)
        self.assertEqual(result['status'], 'SCENE_SAMPLES_READY', result)
        self.assertEqual(result['layout'], 'landscape')
        self.assertEqual(result['candidate_sha256'], m.digest(self.delivery / 'video.mp4'))
        for name, dominant in [('scene-01.png', 0), ('scene-02.png', 2)]:
            with Image.open(self.out / name) as image:
                self.assertEqual(image.size, (1280, 720))
                self.assertGreater(image.getpixel((640, 360))[dominant], 240)
        with Image.open(self.out / 'contact-sheet.jpg') as sheet:
            self.assertEqual(sheet.size, (780, 179))

    def test_planned_reveal_retains_adjacent_encoded_pictures_and_pts(self):
        self.media()
        self.editorial['scenes'] = self.editorial['scenes'][:1]
        render = {'scenes': [{'scene_id': 'first', 'start': 0, 'end': 2, 'visual_reveal': {
            'kind': 'second_comparison_card', 'first_visible_scene_frame': 24, 'rendered_offset_seconds': 1}}]}
        (self.delivery/'render.json').write_text(json.dumps(render))
        with patch.object(m, 'inspect_cycle', return_value=self.snapshot):
            result = m.make_scene_review(self.root, self.out, timeout=30)
        self.assertEqual(result['status'], 'SCENE_SAMPLES_READY', result)
        pair, = result['planned_reveal_samples']
        self.assertEqual(pair['planned_first_visible_frame'], 24)
        for side, dominant in [('before', 0), ('at', 2)]:
            path = self.out/pair[side]['frame']
            self.assertEqual(m.digest(path), pair[side]['sha256'])
            with Image.open(path) as image:
                self.assertGreater(image.getpixel((45, 80))[dominant], 240)
        self.assertAlmostEqual(pair['at']['decoded_frame_pts_seconds'] -
                               pair['before']['decoded_frame_pts_seconds'], 1/24, places=5)
        self.assertIn('Planned reveal', (self.out/'index.html').read_text())

    def test_landscape_without_opt_in_stays_unsupported(self):
        self.media(size='1280x720')
        with patch.object(m, 'inspect_cycle', return_value=self.snapshot):
            with self.assertRaisesRegex(ValueError, '9:16 portrait'):
                m.make_scene_review(self.root, self.out, timeout=30)
        self.assertFalse(self.out.exists())

    def test_source_mutation_blocks_receipt_even_after_frames_decode(self):
        self.media()
        with patch.object(m, 'inspect_cycle', side_effect=[self.snapshot, dict(self.snapshot, changed=True)]):
            result = m.make_scene_review(self.root, self.out, timeout=30)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('changed', result['reason']); self.assertNotIn('sampled_scene_count', result)
        self.assertTrue(result['partial_outputs_retained'])

    def test_low_fps_seek_cannot_claim_a_sample_from_following_scene(self):
        self.media(fps=1)
        rendered = {'scenes': [{'scene_id': 'first', 'start': 0, 'end': .5},
                                {'scene_id': 'second', 'start': .5, 'end': 2}]}
        (self.delivery / 'render.json').write_text(json.dumps(rendered))
        with patch.object(m, 'inspect_cycle', return_value=self.snapshot):
            result = m.make_scene_review(self.root, self.out, timeout=30)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('outside requested scene', result['reason'])
        self.assertNotIn('sampled_scene_count', result)

    def test_decoder_failure_retains_blocked_receipt(self):
        with patch.object(m, 'inspect_cycle', return_value=self.snapshot), \
             patch.object(m, '_probe', return_value={'width':90, 'height':160, 'duration_seconds':2}), \
             patch.object(m, '_run', side_effect=RuntimeError('decoder failure')):
            result = m.make_scene_review(self.root, self.out)
        self.assertEqual(result['status'], 'BLOCKED'); self.assertIn('decoder failure', result['reason'])
        self.assertTrue((self.out / 'scene-review.json').exists())

    def test_environment_paths_symlinks_and_timeouts_fail_before_work(self):
        for timeout in (True, 0, 601, float('nan')):
            with self.assertRaises(ValueError): m.make_scene_review(self.root, self.out, timeout=timeout)
        for key in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED'):
            with patch.dict(os.environ, {key: 'true'}), self.assertRaisesRegex(ValueError, 'disabled'):
                m.make_scene_review(self.root, self.out)
        for target in (self.root, self.root / 'samples', self.base):
            with self.assertRaises(ValueError): m.make_scene_review(self.root, target)
        link = self.base / 'link'; link.symlink_to(self.root)
        with self.assertRaises(ValueError): m.make_scene_review(link, self.out)
        self.assertFalse(self.out.exists())

    def test_pixel_limit_precedes_output(self):
        with patch.object(m, 'inspect_cycle', return_value=self.snapshot), \
             patch.object(m, '_probe', return_value={'width':2160, 'height':3840, 'duration_seconds':2}), \
             self.assertRaisesRegex(ValueError, 'pixel limit'):
            m.make_scene_review(self.root, self.out)
        self.assertFalse(self.out.exists())


if __name__ == '__main__': unittest.main()
