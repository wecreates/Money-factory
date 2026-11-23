"""Native OTIO and FFmpeg regression checks on synthetic completed cycles."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import opentimelineio as otio

from integrations.content_control.cycle_editorial import compile_editorial
from integrations.content_control.cycle_package import editorial_digest, package_cycle
from integrations.content_control.test_cycle_editorial import brief
from integrations.opentimelineio import export_cycle_review as exporter


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


class AuthoredCycleExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.source = Path(temp.name) / 'cycle'
        render = cls.source / 'render'
        render.mkdir(parents=True)
        media = render / 'video.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-copyts', '-itsoffset', '0.042',
                        '-f', 'lavfi', '-i', 'color=blue:s=90x160:r=24:d=2',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=24000:duration=2',
                        '-map', '0:v:0', '-map', '1:a:0', '-fps_mode', 'passthrough',
                        '-threads', '1', '-c:v', 'libx264', '-c:a', 'aac', str(media)], check=True, timeout=30)
        narration = render / 'captions.vtt'
        narration.write_text('WEBVTT\n\n00:00:00.000 --> 00:00:00.500\nWords.\n\n'
                             '2\n00:00:01.000 --> 00:00:01.750\nMore\nwords.  \n', encoding='utf-8')
        editorial = compile_editorial(brief())
        write_json(cls.source / 'brief.json', brief())
        write_json(cls.source / 'editorial.json', editorial)
        cls.candidate = exporter.digest(media)
        flags = {'status': 'AWAITING_REVIEW', 'technical_status': 'PASS', **exporter.FLAGS,
                 'candidate_sha256': cls.candidate}
        write_json(render / 'render.json', dict(flags, editorial_sha256=editorial_digest(editorial),
                   caption_sha256=exporter.digest(narration),
                   scenes=[{'scene_id': 's1', 'start': 0, 'end': 1}, {'scene_id': 's2', 'start': 1, 'end': 2}]))
        # Actual FFmpeg frames suffice for the synthetic manifest; the exporter does not use thumbnail pixels.
        with patch('integrations.content_control.cycle_package.make_thumbnail',
                   side_effect=lambda source, target, *_args, **_kwargs: shutil.copyfile(source, target)):
            package_cycle(editorial, render, cls.source / 'delivery')
        cls.package = exporter.digest(cls.source / 'delivery/package.json')
        write_json(cls.source / 'cycle.json', dict(flags, package_sha256=cls.package,
                   editorial_sha256=exporter.digest(cls.source / 'editorial.json'),
                   brief_sha256=exporter.digest(cls.source / 'brief.json')))

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.cycle = self.base / 'cycle'
        shutil.copytree(self.source, self.cycle)
        self.output = self.base / 'output'

    def export(self, **options):
        pins = dict(candidate_sha256=self.candidate, package_sha256=self.package, timeout=30)
        return exporter.export_cycle(self.cycle, self.output, **(pins | options))

    def test_native_interchange_retains_exact_streams_and_survives_relocation(self):
        source = exporter.inspect_cycle(self.cycle)
        result = self.export()
        self.assertEqual(result['status'], 'INTERCHANGE_VERIFIED')
        self.assertEqual((result['video_frames'], result['caption_markers']), (48, 2))
        self.assertEqual(result['decoded_av'], 'PASS')
        self.assertTrue(result['roundtrip_verified'])
        self.assertGreater(result['streams']['video']['start_ticks'], 0)
        self.assertEqual(result['streams']['audio']['start_ticks'], 0)
        self.assertEqual(result['files_sha256']['video.mp4'], self.candidate)
        self.assertEqual(result['files_sha256']['package.json'], self.package)
        self.assertEqual(result['exporter_sha256'], exporter.digest(exporter.__file__))
        self.assertEqual(json.loads((self.output / 'export-receipt.json').read_text()), result)
        self.assertEqual(exporter.inspect_cycle(self.cycle), source)
        relocated = self.output.rename(self.base / 'relocated')
        timeline = otio.core.deserialize_json_from_string((relocated / 'timeline.otio').read_text())
        picture, sound = timeline.tracks
        gap, *clips = picture
        self.assertIsInstance(gap, otio.schema.Gap)
        self.assertEqual(gap.source_range.duration.value, result['streams']['video']['start_ticks'])
        self.assertEqual([clip.name for clip in clips], ['s1', 's2'])
        self.assertEqual([clip.source_range.start_time.value for clip in clips],
                         [cut['start_ticks'] for cut in result['cuts']])
        self.assertEqual([(m.name, m.marked_range.start_time.value, m.marked_range.duration.value)
                          for m in picture.markers], [('Words.', 0, 500), ('More\nwords.  ', 1000, 750)])
        for clip, stream in zip([*clips, *sound], ['v:0', 'v:0', 'a:0']):
            self.assertEqual(clip.media_reference.metadata['cyzor']['intended_stream'], stream)
            self.assertEqual(clip.media_reference.target_url, 'video.mp4')
            self.assertEqual(exporter.digest(relocated / clip.media_reference.target_url), self.candidate)
        for flag in exporter.FLAGS:
            self.assertFalse(result[flag])

    def test_explicit_pins_and_existing_output_are_enforced(self):
        for field in ('candidate_sha256', 'package_sha256'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Pinned'):
                self.export(**{field: 'a' * 64})
            self.assertFalse(self.output.exists())
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'Fresh output'):
            self.export()

    def test_dirty_source_and_enabled_generation_are_refused(self):
        with patch.dict('os.environ', {'PAID_GENERATION_ENABLED': 'true'}):
            with self.assertRaisesRegex(ValueError, 'must stay disabled'):
                self.export()
        (self.cycle / 'delivery/captions.vtt').write_text('Changed source')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.export()
        self.assertFalse(self.output.exists())

    def test_incomplete_export_is_removed_if_copied_timeline_changes(self):
        run = exporter._run

        def mutate(command, deadline):
            result = run(command, deadline)
            if command[0] == 'ffmpeg':
                (self.output / 'timeline.otio').write_text('{}')
            return result

        with patch.object(exporter, '_run', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'Timeline changed'):
                self.export()
        self.assertFalse(self.output.exists())


class TimingTests(unittest.TestCase):
    def test_frame_pts_and_legacy_ffprobe_duration_field(self):
        report = ('best_effort_timestamp=516|pkt_duration=512|\n'
                  'best_effort_timestamp=1028|duration=512\n'
                  'best_effort_timestamp=1544|duration=512\n')
        clock = {'start_ticks': 516, 'end_ticks': 2056, 'rate': 12288}
        self.assertEqual(exporter.frame_edges(report, 3, clock), [516, 1028, 1544, 2056])
        with self.assertRaisesRegex(ValueError, 'increase'):
            exporter.frame_edges(report.replace('1544', '1028'), 3, clock)
        with self.assertRaisesRegex(ValueError, 'endpoints'):
            exporter.frame_edges(report, 3, dict(clock, end_ticks=2057))

    def test_nominal_scene_grid_selects_observed_pts_and_refuses_bad_boundaries(self):
        edges = [516, 1028, 1544, 2056]
        editorial = {'scenes': [{'id': 'first'}, {'id': 'second'}]}
        scene = {'scene_id': 'first', 'start': 0, 'end': 2 / 24}
        second = {'scene_id': 'second', 'start': 2 / 24, 'end': 3 / 24}
        cuts = exporter.scene_cuts({'scenes': [scene, second]}, editorial, edges)
        self.assertEqual((cuts[0]['end_ticks'], cuts[1]['start_ticks']), (1544, 1544))
        for value in (dict(second, start=0), dict(second, start=.1), dict(second, scene_id='first')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                exporter.scene_cuts({'scenes': [scene, value]}, editorial, edges)

    def test_caption_markers_refuse_overlapping_and_out_of_audio_cues(self):
        audio = {'start_ticks': 0, 'end_ticks': 24000, 'rate': 24000}
        cue = '00:00:00.000 --> 00:00:00.900\nWords.'
        for text in (cue + '\n\n' + cue, cue.replace('.900', '.999 align:start'),
                     cue.replace('00:00:00.900', '00:00:01.001')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                exporter.caption_markers('WEBVTT\n\n' + text, audio)


if __name__ == '__main__':
    unittest.main()
