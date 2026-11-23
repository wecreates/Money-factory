import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from integrations.content_control.cycle_av_benchmarks import compare_benchmarks


def signals(duration=20, *, width=720):
    return {'media': {'duration_seconds': duration, 'width': width, 'height': 1280},
            'watcher': {'black_seconds': 1, 'frozen_seconds': 2},
            'listener': {'silence_seconds': 4, 'peak_dbfs': -2, 'mean_dbfs': -16}}


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.manifest = self.root / 'benchmarks.json'
        self.rows = []
        for index, url in enumerate(('https://www.youtube.com/watch?v=DHjqpvDnNGE',
                                     'https://player.example.com/videos/second')):
            name = f'reference-{index}.mp4'
            media = b'\x00\x00\x00\x10ftypisom' + bytes([index]) * 8
            (self.root / name).write_bytes(media)
            self.rows.append({'url': url, 'path': name, 'sha256': hashlib.sha256(media).hexdigest(),
                              'authorized': True, 'selection_rationale': 'Compare pacing within this editorial lane.',
                              'selection_evidence_url': 'https://example.com/source/benchmark-notes',
                              'selected_at': '2026-11-23T14:58:00Z'})

    def compare(self, scan, *, width=720, reference_sets=None):
        manifest = {'schema_version': 1}
        if reference_sets is None:
            manifest['references'] = self.rows
        else:
            manifest['reference_sets'] = reference_sets
        self.manifest.write_text(json.dumps(manifest))
        with patch.dict('os.environ', {'CYZOR_REVIEW_BENCHMARKS': str(self.manifest)}):
            return compare_benchmarks('a' * 64, signals(width=width), scan=scan, deadline=time.monotonic() + 10)

    def test_missing_config_blocks_without_scanning(self):
        scan = Mock()
        with patch.dict('os.environ', {}, clear=True):
            result = compare_benchmarks('a' * 64, signals(), scan=scan, deadline=time.monotonic() + 10)
        self.assertEqual(result['reason'], 'BENCHMARK_MANIFEST_UNCONFIGURED')
        self.assertFalse(result['full_av_review'])
        scan.assert_not_called()

    def test_two_exact_local_references_produce_only_technical_deltas(self):
        scan = Mock(side_effect=[signals(10), signals(40)])
        with patch('socket.create_connection', side_effect=AssertionError('network disallowed')):
            result = self.compare(scan)
        self.assertEqual(result['status'], 'TECHNICAL_COMPARISON_COMPLETE')
        self.assertEqual(len(result['comparisons']), 2)
        self.assertEqual([call.args[0] for call in scan.call_args_list],
                         [self.root / row['path'] for row in self.rows])
        self.assertFalse(result['reference_selection_independently_verified'])
        self.assertFalse(result['full_av_review'])
        self.assertFalse(result['publication_enabled'])
        first = result['comparisons'][0]
        self.assertEqual(first['sha256'], self.rows[0]['sha256'])
        self.assertNotIn('path', first)
        self.assertAlmostEqual(first['candidate_minus_reference']['silence_fraction'], -.2)
        self.assertEqual(first['candidate_minus_reference']['peak_dbfs'], 0)

    def test_mixed_manifest_selects_only_matching_pair_and_names_missing_format(self):
        landscape = []
        for index, row in enumerate(self.rows):
            name = f'landscape-{index}.mp4'
            media = (self.root / row['path']).read_bytes() + b'wide'
            (self.root / name).write_bytes(media)
            landscape.append({**row, 'url': f'https://player.example.com/videos/landscape-{index}',
                              'path': name, 'sha256': hashlib.sha256(media).hexdigest()})
        sets = {'portrait': self.rows, 'landscape': landscape}
        for orientation, width in [('portrait', 720), ('landscape', 1920)]:
            with self.subTest(orientation=orientation):
                scan = Mock(return_value=signals(width=width))
                result = self.compare(scan, width=width, reference_sets=sets)
                self.assertEqual(result['status'], 'TECHNICAL_COMPARISON_COMPLETE')
                self.assertEqual(result['reference_format'], orientation)
                self.assertEqual([call.args[0] for call in scan.call_args_list],
                                 [self.root / row['path'] for row in sets[orientation]])
        scan = Mock()
        result = self.compare(scan, width=1280, reference_sets=sets)
        self.assertEqual(result['reason'], 'BENCHMARK_FORMAT_UNCONFIGURED')
        self.assertEqual(result['reference_format'], 'square')
        scan.assert_not_called()

    def test_refuses_unapproved_duplicate_live_or_remote_reference_before_scan(self):
        original = dict(self.rows[1])
        for field, value in [('url', 'https://www.instagram.com/reel/abc/'),
                             ('url', 'https://youtu.be/DHjqpvDnNGE?si=alias'),
                             ('url', 'https://127.0.0.1/video'), ('path', 'https://example.com/video.mp4'),
                             ('authorized', False), ('sha256', 'a' * 64), ('sha256', 'b' * 64),
                             ('selected_at', '2026-11-23T14:58:00')]:
            with self.subTest(field=field, value=value):
                self.rows[1] = {**original, field: value}
                scan = Mock()
                self.assertEqual(self.compare(scan)['status'], 'BLOCKED')
                scan.assert_not_called()

    def test_timeout_orientation_mismatch_and_changed_bytes_do_not_publish_partial_results(self):
        for scan, reason in [(Mock(side_effect=TimeoutError), 'BENCHMARK_COMPARISON_TIMED_OUT'),
                             (Mock(return_value=signals(width=1920)), 'BENCHMARK_INPUT_OR_SCAN_INVALID')]:
            result = self.compare(scan)
            self.assertEqual(result['reason'], reason)
            self.assertEqual(result['comparisons'], [])

        def change(path, **kwargs):
            path.write_bytes(path.read_bytes() + b'changed')
            return signals()
        result = self.compare(change)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['comparisons'], [])
