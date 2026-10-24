"""Offline Hypit bridge tests. Fixtures are synthetic and are never render evidence."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hypit.adapter import (ARCHIVE_SHA256, BLOB_TYPE, REVISION, dispatch,
                           prepare_project, validate_export)

DISABLED = {'publication_enabled': False, 'paid_generation_enabled': False}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def png(width=2, height=2):
    def chunk(kind, raw):
        return struct.pack('>I', len(raw)) + kind + raw + struct.pack('>I', zlib.crc32(kind + raw))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\x00' + b'\x20\x80\xd0' * width) * height)) + chunk(b'IEND', b''))


class HypitBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        image = png()
        (self.root / 'owned.png').write_bytes(image)
        self.prep = {**DISABLED, 'project_id': 'cyzor-test', 'title': 'Original CYZOR storyboard',
                     'intended_use': 'own_organization', 'frame_rate': 30, 'width': 1080, 'height': 1920,
                     'scenes': [{'id': 'opening', 'duration_frames': 90, 'image': {
                         'path': str(self.root / 'owned.png'), 'sha256': sha(image),
                         'rights_basis': 'original', 'rights_attested': True}}]}
        # Intentionally only an MP4 signature. Passing intake must NEVER imply media decode.
        self.video = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom'
        (self.root / 'video.mp4').write_bytes(self.video)
        self.report = {'format': 'hypit.build-result@1', 'source': {'id': 'main.svml'},
                       'run': {'id': 'build.svrun'}, 'targets': ['final.video'],
                       'outcome': 'complete', 'finishedAt': 1792782000000,
                       'outputs': {'final.video': {'type': BLOB_TYPE, 'value': {
                           'kind': 'build-file', 'path': 'video.mp4', 'size': len(self.video), 'mediaType': 'video/mp4'}}}}

    def intake(self, report=None):
        raw = json.dumps(report or self.report).encode()
        (self.root / 'result.json').write_bytes(raw)
        return {**DISABLED, 'preparation': copy.deepcopy(self.prep), 'export': {
            'path': str(self.root / 'video.mp4'), 'sha256': sha(self.video),
            'request_sha256': prepare_project(self.prep)['request_sha256'],
            'result_path': str(self.root / 'result.json'), 'result_sha256': sha(raw)}}

    def test_status_has_truthful_blocked_runtime(self):
        got = dispatch({**DISABLED, 'tool': 'hypit', 'operation': 'status'})
        self.assertEqual(got['status'], 'BLOCKED')
        self.assertEqual(got['upstream_revision'], REVISION)
        self.assertEqual(got['archive_sha256'], ARCHIVE_SHA256)
        for name in ('production_ready', 'publication_enabled', 'paid_generation_enabled', 'live_execution_enabled'):
            self.assertIs(got[name], False)
        self.assertEqual(got['provider_calls'], 0)

    def test_prepare_project_emits_source_run_recipe_and_boundary(self):
        got = prepare_project(self.prep)
        self.assertEqual(got['status'], 'PASS')
        self.assertEqual(set(got['project_files']), {'main.svml', 'style.svs', 'build.svrun', 'package.json'})
        self.assertIn('<time:Window id="scene-0" from="0f" for="90f"/>', got['project_files']['main.svml'])
        self.assertIn('<target output="final.video"/>', got['project_files']['build.svrun'])
        self.assertTrue(json.loads(got['project_files']['package.json'])['hypit']['project'])
        self.assertFalse(got['upstream_compile_verified'])
        self.assertFalse(got['narration_included'])
        self.assertFalse(got['commercial_rights_verified'])
        self.assertEqual(got['request_sha256'], prepare_project(self.prep)['request_sha256'])
        self.assertFalse((self.root / 'main.svml').exists())

    def test_multiple_scene_timing_and_no_markup_injection(self):
        other = copy.deepcopy(self.prep['scenes'][0])
        other.update(id='ending', duration_frames=60, note='<html:Video>not executable</html:Video>')
        self.prep['scenes'].append(other)
        self.prep['title'] = '\"><script>ignored()</script>'
        got = prepare_project(self.prep)
        self.assertIn('from="90f" for="60f"', got['project_files']['main.svml'])
        self.assertEqual(got['project']['total_frames'], 150)
        self.assertNotIn('ignored()', got['project_files']['main.svml'])
        self.assertNotIn('not executable', got['project_files']['main.svml'])

    def test_changed_project_or_asset_changes_binding(self):
        before = prepare_project(self.prep)['request_sha256']
        self.prep['scenes'][0]['duration_frames'] += 1
        self.assertNotEqual(before, prepare_project(self.prep)['request_sha256'])

    def test_rights_missing_false_or_third_party_fail(self):
        for key, value in [('rights_basis', 'third_party_reference'), ('rights_attested', False), ('rights_attested', 'true')]:
            bad = copy.deepcopy(self.prep)
            bad['scenes'][0]['image'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                prepare_project(bad)

    def test_multitenant_and_redistribution_fail_closed(self):
        for use in ('multi_tenant', 'commercial_redistribution'):
            self.prep['intended_use'] = use
            with self.assertRaises(ValueError):
                prepare_project(self.prep)

    def test_activation_credential_and_execution_options_rejected(self):
        for key, value in [('api_key', 'not-a-real-secret'), ('publication_enabled', True),
                           ('paid_generation_enabled', True), ('network_enabled', True), ('paid_services_enabled', True)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                prepare_project({**self.prep, key: value})
        for operation in ('install', 'build', 'render', 'publish', 'fetch-instagram'):
            with self.assertRaises(ValueError):
                dispatch({**DISABLED, 'tool': 'hypit', 'operation': operation})

    def test_missing_explicit_disabled_flags_rejected(self):
        for key in DISABLED:
            bad = copy.deepcopy(self.prep)
            del bad[key]
            with self.assertRaises(ValueError):
                prepare_project(bad)

    def test_bad_numbers_and_ids_rejected(self):
        for key, value in [('frame_rate', True), ('frame_rate', 29), ('width', 1079), ('height', 0)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                prepare_project({**self.prep, key: value})
        for value in (True, float('nan'), 0, 1801):
            bad = copy.deepcopy(self.prep)
            bad['scenes'][0]['duration_frames'] = value
            with self.assertRaises(ValueError):
                prepare_project(bad)
        self.prep['scenes'][0]['id'] = 'x\"/><script>'
        with self.assertRaises(ValueError):
            prepare_project(self.prep)

    def test_duplicate_scene_and_overlong_project_rejected(self):
        self.prep['scenes'] *= 2
        with self.assertRaises(ValueError):
            prepare_project(self.prep)
        self.prep['scenes'] = [dict(copy.deepcopy(self.prep['scenes'][0]), id=f'scene-{i}', duration_frames=1800) for i in range(4)]
        with self.assertRaises(ValueError):
            prepare_project(self.prep)

    def test_remote_asset_and_digest_mismatch_rejected(self):
        for path in ('https://instagram.com/reel/example', '//remote/owned.png', 'C:\\file.png'):
            bad = copy.deepcopy(self.prep)
            bad['scenes'][0]['image']['path'] = path
            with self.assertRaises(ValueError):
                prepare_project(bad)
        self.prep['scenes'][0]['image']['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            prepare_project(self.prep)

    def test_symlink_and_parent_symlink_rejected(self):
        link = self.root / 'link.png'
        link.symlink_to(self.root / 'owned.png')
        self.prep['scenes'][0]['image']['path'] = str(link)
        with self.assertRaises(ValueError):
            prepare_project(self.prep)
        parent = self.root / 'linked-directory'
        parent.symlink_to(self.root, target_is_directory=True)
        self.prep['scenes'][0]['image']['path'] = str(parent / 'owned.png')
        with self.assertRaises(ValueError):
            prepare_project(self.prep)

    def test_raw_parent_paths_rejected_for_inputs_and_exports(self):
        bad = copy.deepcopy(self.prep)
        bad['scenes'][0]['image']['path'] = str(self.root / 'nested/../owned.png')
        with self.assertRaises(ValueError):
            prepare_project(bad)
        data = self.intake()
        data['export']['path'] = str(self.root / 'nested/../video.mp4')
        with self.assertRaises(ValueError):
            validate_export(data)

    def test_invalid_png_and_oversized_dimensions_rejected(self):
        for raw in (b'not an image', png(1, 1)[:16] + struct.pack('>II', 9000, 1) + png(1, 1)[24:]):
            (self.root / 'owned.png').write_bytes(raw)
            self.prep['scenes'][0]['image']['sha256'] = sha(raw)
            with self.assertRaises(ValueError):
                prepare_project(self.prep)

    def test_export_matches_native_bytes_preserves_report_and_keeps_quality_blocked(self):
        data = self.intake()
        before = (self.root / 'result.json').read_bytes()
        got = validate_export(data)
        self.assertEqual(got['status'], 'PASS')
        self.assertTrue(got['candidate']['native_result_file_binding_verified'])
        for name in ('full_decode_verified', 'source_generation_verified', 'upstream_execution_verified'):
            self.assertIs(got['candidate'][name], False)
        self.assertFalse(got['production_ready'])
        self.assertEqual(got['candidate']['state'], 'PENDING_MEDIA_DECODE_AND_REVIEW')
        self.assertEqual(before, (self.root / 'result.json').read_bytes())
        self.assertFalse(got['preserved_report']['modified'])

    def test_request_and_result_digest_mismatch_rejected(self):
        for field in ('sha256', 'request_sha256', 'result_sha256'):
            data = self.intake()
            data['export'][field] = '0' * 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_export(data)

    def test_non_complete_native_results_rejected(self):
        for state in ('failed', 'cancelled', 'pending', None):
            report = copy.deepcopy(self.report)
            report['outcome'] = state
            with self.assertRaises(ValueError):
                validate_export(self.intake(report))
        for key, value in [('format', 'made-up'), ('finishedAt', True), ('targets', ['other']), ('source', {})]:
            report = copy.deepcopy(self.report)
            report[key] = value
            with self.assertRaises(ValueError):
                validate_export(self.intake(report))

    def test_external_forwarded_traversal_and_mismatch_results_rejected(self):
        for key, value in [('kind', 'external-file'), ('kind', 'build-output'), ('build', 'different-build'),
                           ('path', '../video.mp4'), ('path', '/video.mp4'), ('path', 'dir//video.mp4'),
                           ('path', 'file:///video.mp4'), ('path', 'C:\\video.mp4'),
                           ('mediaType', 'audio/wav'), ('size', 1)]:
            report = copy.deepcopy(self.report)
            report['outputs']['final.video']['value'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_export(self.intake(report))

    def test_native_export_must_match_declared_file_not_just_report(self):
        data = self.intake()
        (self.root / 'copy.mp4').write_bytes(self.video)
        data['export']['path'] = str(self.root / 'copy.mp4')
        (self.root / 'video.mp4').write_bytes(self.video + b'changed')
        with self.assertRaises(ValueError):
            validate_export(data)

    def test_dispatch_json_duplicate_and_nonfinite_keys_rejected(self):
        path = self.root / 'input.json'
        for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
            path.write_text(raw)
            with self.assertRaises(ValueError):
                dispatch({**DISABLED, 'tool': 'hypit', 'operation': 'prepare-project', 'input': str(path)})

    def test_canonical_content_control_route_for_all_operations(self):
        import os
        import subprocess
        money = Path(__file__).resolve().parents[1]
        candidates = [Path(os.environ['CONTENT_CONTROL_ROOT']) / 'scripts/repository_tools.py'] if os.environ.get('CONTENT_CONTROL_ROOT') else [money.parent / 'content-control/scripts/repository_tools.py', money / 'content-control-bridge/scripts/repository_tools.py']
        wrapper = next((path for path in candidates if path.is_file()), None)
        if wrapper is None:
            self.skipTest('Content Control checkout needed for cross-repository wiring test')
        for operation in ('status', 'prepare-project', 'validate-export'):
            input_path = self.root / (operation + '-input.json')
            input_path.write_text(json.dumps(self.intake() if operation == 'validate-export' else self.prep))
            output = self.root / (operation + '-output.json')
            job = {**DISABLED, 'tool': 'hypit', 'operation': operation,
                   'input': str(input_path), 'output': str(output)}
            job_path = self.root / (operation + '-job.json')
            job_path.write_text(json.dumps(job))
            child = subprocess.run([sys.executable, str(wrapper), str(job_path),
                                    '--runtime', str(self.root / 'worker-runtime')],
                                   env=dict(os.environ, MONEY_FACTORY_ROOT=str(money)),
                                   text=True, capture_output=True, timeout=10)
            self.assertEqual(child.returncode, 2 if operation == 'status' else 0, child.stderr)
            receipt = json.loads(Path(str(output) + '.receipt.json').read_text())
            self.assertEqual(receipt['output_sha256'], sha(output.read_bytes()))
            self.assertFalse(receipt['upstream_runtime_verified'])
            self.assertFalse(receipt['network_executed'])
            self.assertFalse(receipt['production_ready'])

    def test_prepare_and_validate_use_no_process_or_network(self):
        with patch('subprocess.run', side_effect=AssertionError('subprocess prohibited')), \
             patch('socket.socket', side_effect=AssertionError('network prohibited')):
            prepare_project(self.prep)
            validate_export(self.intake())


if __name__ == '__main__':
    unittest.main()
