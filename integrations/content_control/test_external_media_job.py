"""Offline external-media admission tests; fixtures are not audiovisual proof."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from integrations.local_agent_queue import Queue, work
from integrations.content_control.external_media_job import (
    LEGACY_SOURCE_EVIDENCE, MODEL_EDIT_OPERATION, REHASHED_SOURCE_EVIDENCE,
    SOURCE_BYTES_OPERATION, run_job, validate,
)
from integrations.content_control.review_package import digest
from integrations.content_control.review_delivery import export_review, status, verify_delivery
from integrations.queue_monitor import inspect_queue


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


@unittest.skipUnless(os.name == 'posix', 'Durable queue consumer requires POSIX ownership')
class ExternalMediaJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.external = self.root / 'external'; self.review = self.external / 'review'
        self.diagnostics = self.external / 'diagnostics'
        self.review.mkdir(parents=True); self.diagnostics.mkdir()
        self.source_sha = hashlib.sha256(b'original source candidate').hexdigest()
        self.trimmed_sha = hashlib.sha256(b'free local trimmed source').hexdigest()
        self.tool_commit = 'c' * 40
        self.prior = {
            'schema_version': 1, 'observed_at_utc': '2026-11-24T19:12:42Z',
            'workstream': 'C09',
            'source': {'repository': 'https://github.com/OpenMontageInc/OpenMontage.git',
                       'commit': 'b' * 40, 'checkout_clean': True},
            'safety': {'publication_enabled': False, 'paid_generation_enabled': False,
                       'provider_calls': 0, 'sandbox_weakened': False, 'external_write': False},
            'input': {'path': '/operator/source/video.mp4', 'sha256': self.source_sha,
                      'duration_seconds': 60.0, 'resolution': '1280x720',
                      'video_codec': 'h264', 'audio_codec': 'aac'},
            'ordinary_browser_probe': {'status': 'BLOCKED_PROCESS_SINGLETON_SOCKET_POLICY'},
            'remotion_attempt': {'render_completed': False},
            'actual_tool_consumers': [{'tool': 'video_trimmer', 'success': True,
                                       'cost_usd': 0.0, 'output_sha256': self.trimmed_sha}],
            'visual_review': {'creative_acceptance': False},
            'verdict': {'durable_queue_packaging': False},
        }
        self.prior_path = self.diagnostics / 'prior-openmontage-receipt.json'
        write_json(self.prior_path, self.prior)
        self.prior_sha = digest(self.prior_path)

        (self.review / 'video.mp4').write_bytes(b'SYNTHETIC_MEDIA_NOT_PLAYBACK_PROOF')
        (self.review / 'captions.vtt').write_text('WEBVTT\n')
        (self.review / 'REVIEW.md').write_text('Synthetic private review fixture.\n')
        self.candidate_sha = digest(self.review / 'video.mp4')
        self.metadata = {
            'schema_version': 1, 'status': 'AWAITING_REVIEW', 'tool': 'showcase_card',
            'tool_version': '0.1.0', 'provider': 'ffmpeg', 'runtime': 'local',
            'operation': 'contain_and_pad_portrait_preview',
            'observed_at_utc': '2026-11-24T19:47:20Z',
            'source_candidate_sha256': self.source_sha,
            'trimmed_source_sha256': self.trimmed_sha,
            'candidate_sha256': self.candidate_sha,
            'prior_openmontage_receipt_sha256': self.prior_sha,
            'openmontage_adapter_commit': self.tool_commit,
            'openmontage_repository': 'https://github.com/OpenMontageInc/OpenMontage.git',
            'openmontage_base_commit': 'b' * 40,
            'source_resolution': '1280x720', 'output_resolution': '1080x1920',
            'sample_aspect_ratio': '1:1', 'display_aspect_ratio': '9:16',
            'letterbox_y_offset': 656, 'duration_seconds': 59.0,
            'video_codec': 'h264', 'audio_codec': 'aac',
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_approved': False, 'production_ready': False,
            'full_av_review': False, 'provider_calls': 0, 'sandbox_weakened': False,
            'scope': 'Synthetic free local preview; not creative acceptance.',
        }
        write_json(self.review / 'video.mp4.json', self.metadata)
        artifacts = {path.name: digest(path) for path in self.review.iterdir()}
        self.run = {
            'schema_version': 1, 'status': 'AWAITING_REVIEW', 'technical_status': 'PASS',
            'observed_at_utc': '2026-11-24T19:47:20Z',
            'consumer': 'openmontage', 'operation': 'contain_and_pad_portrait_preview',
            'candidate_sha256': self.candidate_sha,
            'caption_sha256': digest(self.review / 'captions.vtt'),
            'source_candidate_sha256': self.source_sha,
            'prior_openmontage_receipt_sha256': self.prior_sha,
            'openmontage_adapter_commit': self.tool_commit,
            'artifacts_sha256': artifacts,
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_approved': False, 'production_ready': False,
            'full_av_review': False, 'provider_calls': 0, 'sandbox_weakened': False,
            'scope': 'Synthetic private review fixture.',
        }
        write_json(self.review / 'run.json', self.run)
        self.run_sha = digest(self.review / 'run.json')
        self.external_receipt = {
            'schema_version': 1, 'observed_at_utc': '2026-11-24T19:47:20Z',
            'workstream': 'C09',
            'issue_evidence': {'url': 'https://github.com/example/review',
                               'comment_id': 1, 'created_at_utc': '2026-11-24T19:15:16Z',
                               'live_read_at_utc': '2026-11-24T19:50:00Z'},
            'source': {'repository': 'https://github.com/OpenMontageInc/OpenMontage.git',
                       'base_commit': 'b' * 40, 'adapter_commit': self.tool_commit,
                       'checkout_clean': True, 'prior_receipt_sha256': self.prior_sha},
            'input': {'current_candidate_sha256': self.source_sha,
                      'trimmed_source_sha256': self.trimmed_sha,
                      'trim_seconds': [0, 59], 'source_resolution': '1280x720'},
            'consumer': {'tool': 'showcase_card', 'tool_version': '0.1.0',
                         'provider': 'ffmpeg', 'runtime': 'local',
                         'operation': 'contain_and_pad_portrait_preview',
                         'output_resolution': '1080x1920',
                         'scaled_picture_resolution': '1080x608',
                         'sample_aspect_ratio': '1:1', 'display_aspect_ratio': '9:16',
                         'letterbox_y_offset': 656, 'output_duration_seconds': 59.0,
                         'output_sha256': self.candidate_sha},
            'safety': {'publication_enabled': False, 'paid_generation_enabled': False,
                       'production_approved': False, 'provider_calls': 0,
                       'sandbox_weakened': False, 'external_write': False},
            'tests': {'command': 'synthetic', 'result': 'fixture',
                      'square_pixel_regression_added': True},
            'visual_review': {'creative_final_acceptance': False, 'full_av_review': False},
            'revision_package': {'status': 'AWAITING_REVIEW', 'durable_queue_completion': False},
            'verdict': {'creative_final_acceptance': False, 'durable_queue_completion': False},
        }
        self.receipt_path = self.external / 'safe-reframe-receipt.json'
        write_json(self.receipt_path, self.external_receipt)
        self.request = {
            'operation': 'package-openmontage-safe-reframe',
            'source_candidate_sha256': self.source_sha,
            'transformed_source_sha256': self.trimmed_sha,
            'candidate_sha256': self.candidate_sha,
            'external_receipt_sha256': digest(self.receipt_path),
            'prior_tool_receipt_sha256': self.prior_sha,
            'review_run_sha256': self.run_sha,
            'tool_commit': self.tool_commit, 'timeout_seconds': 30,
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_approved': False, 'production_ready': False,
            'full_av_review': False,
        }
        self.spec = {'id': 'offline-reframe', 'adapter': 'content-control-external-media',
                     'request': self.request, 'max_attempts': 1,
                     'publication_enabled': False, 'paid_generation_enabled': False}

    def run_queue(self):
        queue = Queue(self.root / 'queue'); self.addCleanup(queue.close)
        queue.enqueue(self.spec)
        report = work(queue, external_media_root=self.external)
        return queue, report

    def add_source_bytes(self):
        sources = self.external / 'source-evidence'
        sources.mkdir()
        (sources / 'original.mp4').write_bytes(b'original source candidate')
        (sources / 'trimmed.mp4').write_bytes(b'free local trimmed source')
        self.request['operation'] = SOURCE_BYTES_OPERATION
        return sources

    def convert_to_model_edit_packet(self):
        sources = self.external / 'source-evidence'
        sources.mkdir()
        (sources / 'original.mp4').write_bytes(b'original source candidate')
        (sources / 'trimmed.mp4').write_bytes(b'SYNTHETIC_MEDIA_NOT_PLAYBACK_PROOF')
        self.request.update(operation=MODEL_EDIT_OPERATION,
                            transformed_source_sha256=self.candidate_sha)
        model = {
            'schema_version': 1,
            'input': {'sha256': self.source_sha},
            'local_model': {'sha256': 'a' * 64, 'provider_calls': 0, 'cost_usd': 0.0},
            'output': {'sha256': self.candidate_sha, 'full_decode': 'PASS',
                       'audio_packet_stream_preserved': True},
            'safety': {'publication_enabled': False, 'paid_inference_enabled': False,
                       'provider_calls': 0, 'external_write': False,
                       'sandbox_weakened': False},
        }
        model_path = self.diagnostics / 'model-edit-receipt.json'
        write_json(model_path, model)
        self.request['prior_tool_receipt_sha256'] = digest(model_path)
        wrapper = {
            'schema_version': 1, 'observed_at_utc': '2026-11-25T08:05:53Z',
            'workstream': 'C09', 'operation': MODEL_EDIT_OPERATION,
            'source_candidate_sha256': self.source_sha,
            'candidate_sha256': self.candidate_sha,
            'model_receipt_sha256': self.request['prior_tool_receipt_sha256'],
            'tool_commit': self.tool_commit,
            'consumer': 'content-control-external-media',
            'safety': {'publication_enabled': False, 'paid_generation_enabled': False,
                       'production_approved': False, 'production_ready': False,
                       'full_av_review': False, 'provider_calls': 0},
            'scope': 'Synthetic exact-byte queue consumer test; not audiovisual proof.',
        }
        wrapper_path = self.external / 'model-consumer-receipt.json'
        write_json(wrapper_path, wrapper)
        self.request['external_receipt_sha256'] = digest(wrapper_path)
        self.metadata = {
            'schema_version': 1, 'status': 'AWAITING_REVIEW',
            'tool': 'OpenCV YuNet face detector 2023mar', 'runtime': 'local',
            'operation': MODEL_EDIT_OPERATION, 'observed_at_utc': '2026-11-25T08:05:53Z',
            'source_candidate_sha256': self.source_sha,
            'candidate_sha256': self.candidate_sha, 'model_sha256': 'a' * 64,
            'model_receipt_sha256': self.request['prior_tool_receipt_sha256'],
            'tool_commit': self.tool_commit, 'source_resolution': '1280x720',
            'output_resolution': '1080x1920', 'duration_seconds': 1.0,
            'video_codec': 'h264', 'audio_codec': 'aac', 'full_decode': 'PASS',
            'audio_packet_stream_preserved': True, 'publication_enabled': False,
            'paid_generation_enabled': False, 'production_approved': False,
            'full_av_review': False, 'production_ready': False, 'provider_calls': 0,
            'sandbox_weakened': False, 'scope': 'Synthetic metadata only.',
        }
        write_json(self.review / 'video.mp4.json', self.metadata)
        artifacts = {path.name: digest(path) for path in self.review.iterdir()
                     if path.name != 'run.json'}
        self.run = {
            'schema_version': 1, 'status': 'AWAITING_REVIEW', 'technical_status': 'PASS',
            'observed_at_utc': '2026-11-25T08:05:53Z',
            'consumer': 'content-control-external-media', 'operation': MODEL_EDIT_OPERATION,
            'candidate_sha256': self.candidate_sha,
            'caption_sha256': digest(self.review / 'captions.vtt'),
            'source_candidate_sha256': self.source_sha,
            'prior_tool_receipt_sha256': self.request['prior_tool_receipt_sha256'],
            'tool_commit': self.tool_commit, 'artifacts_sha256': artifacts,
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_approved': False, 'full_av_review': False,
            'production_ready': False, 'sandbox_weakened': False, 'provider_calls': 0,
            'scope': 'Synthetic queue consumer test; not audiovisual proof.',
        }
        write_json(self.review / 'run.json', self.run)
        self.request['review_run_sha256'] = digest(self.review / 'run.json')

    def test_model_edit_packet_uses_normal_queue_and_durable_export_consumers(self):
        self.convert_to_model_edit_packet()
        queue, report = self.run_queue()
        self.assertEqual(report['processed'][0]['state'], 'succeeded')
        stored = queue.get(self.spec['id'])['receipts'][0]['receipt']
        self.assertEqual(stored['source_evidence'], REHASHED_SOURCE_EVIDENCE)
        self.assertEqual(stored['candidate_sha256'], self.candidate_sha)
        review, proof = verify_delivery(queue.root, self.spec['id'])
        self.assertEqual(review, queue.root / 'attempts/offline-reframe/1/review')
        self.assertEqual(proof['operation'], MODEL_EDIT_OPERATION)
        exported = export_review(queue.root, self.spec['id'], self.root / 'private-model-export')
        self.assertEqual(exported['candidate_sha256'], self.candidate_sha)
        self.assertFalse(exported['publication_enabled'])

    def test_queue_packages_and_delivery_reverifies_exact_offline_bytes(self):
        queue, report = self.run_queue()
        self.assertEqual(report['processed'][0]['state'], 'succeeded')
        stored = queue.get(self.spec['id'])['receipts'][0]['receipt']
        self.assertEqual(stored['provider_calls'], 0)
        self.assertEqual(stored['candidate_sha256'], self.candidate_sha)
        self.assertFalse(stored['production_approved'])
        staged, proof = verify_delivery(queue.root, self.spec['id'])
        self.assertEqual(staged, queue.root / 'attempts/offline-reframe/1/review')
        self.assertEqual(proof['external_receipt_sha256'], self.request['external_receipt_sha256'])
        self.assertEqual(proof['tool_commit'], self.tool_commit)
        self.assertEqual(proof['source_evidence'], LEGACY_SOURCE_EVIDENCE)
        self.assertNotIn('source_evidence', stored)
        self.assertTrue(status(queue.root, self.spec['id'])['delivery_ready'])
        exported = export_review(queue.root, self.spec['id'], self.root / 'private-export')
        self.assertEqual(exported['candidate_sha256'], self.candidate_sha)
        self.assertEqual(exported['provenance']['provider_calls'], 0)

    def test_queue_retains_and_rehashes_original_trim_and_receipts_without_exporting_them(self):
        sources = self.add_source_bytes()
        queue, report = self.run_queue()
        self.assertEqual(report['processed'][0]['state'], 'succeeded')
        self.assertEqual(queue.get(self.spec['id'])['receipts'][0]['receipt']['source_evidence'],
                         REHASHED_SOURCE_EVIDENCE)
        attempt = queue.root / 'attempts/offline-reframe/1'
        for name, expected in (('original.mp4', self.source_sha), ('trimmed.mp4', self.trimmed_sha)):
            self.assertEqual(digest(attempt / 'source-evidence' / name), expected)
            (sources / name).unlink()
        self.receipt_path.unlink()
        self.prior_path.unlink()
        _, proof = verify_delivery(queue.root, self.spec['id'])
        self.assertEqual(proof['source_evidence'], REHASHED_SOURCE_EVIDENCE)
        exported = export_review(queue.root, self.spec['id'], self.root / 'private-export')
        self.assertEqual(exported['provenance']['source_evidence'], REHASHED_SOURCE_EVIDENCE)
        for archive in (attempt / 'delivery/review-package.zip', self.root / 'private-export/review-package.zip'):
            with ZipFile(archive) as bundle:
                self.assertNotIn('review/source-evidence/original.mp4', bundle.namelist())
                self.assertNotIn('review/source-evidence/trimmed.mp4', bundle.namelist())
                self.assertNotIn('review/safe-reframe-receipt.json', bundle.namelist())
                self.assertNotIn('review/diagnostics/prior-openmontage-receipt.json', bundle.namelist())
        trimmed = attempt / 'source-evidence/trimmed.mp4'
        original_trimmed = trimmed.read_bytes()
        trimmed.write_bytes(b'tampered after completion')
        self.assertFalse(status(queue.root, self.spec['id'])['delivery_ready'])
        trimmed.write_bytes(original_trimmed)
        (attempt / 'diagnostics/prior-openmontage-receipt.json').write_text('{}')
        self.assertFalse(status(queue.root, self.spec['id'])['delivery_ready'])

    def test_source_byte_operation_blocks_missing_wrong_symlink_or_oversized_input(self):
        sources = self.add_source_bytes()
        original = sources / 'original.mp4'
        owner_bytes = original.read_bytes()
        original.unlink()
        attempt = self.root / 'attempt-missing'; attempt.mkdir()
        self.assertEqual(run_job(self.request, attempt, external_media_root=self.external)['status'], 'BLOCKED')
        outside = self.root / 'outside-source.mp4'; outside.write_bytes(owner_bytes)
        original.symlink_to(outside)
        attempt = self.root / 'attempt-source-link'; attempt.mkdir()
        self.assertEqual(run_job(self.request, attempt, external_media_root=self.external)['status'], 'BLOCKED')
        original.unlink()
        original.write_bytes(b'wrong source bytes')
        attempt = self.root / 'attempt-source-wrong'; attempt.mkdir()
        self.assertEqual(run_job(self.request, attempt, external_media_root=self.external)['status'], 'BLOCKED')
        original.write_bytes(owner_bytes)
        limit = max((self.review / 'video.mp4').stat().st_size, len(owner_bytes))
        with patch('integrations.content_control.external_media_job.MAX_MEDIA', limit):
            attempt = self.root / 'attempt-source-total'; attempt.mkdir()
            self.assertEqual(run_job(self.request, attempt, external_media_root=self.external)['status'], 'BLOCKED')

    def test_source_byte_job_missing_durability_blocks_without_pass(self):
        self.add_source_bytes()
        with patch('integrations.content_control.external_media_job._sync_tree', side_effect=OSError):
            queue, report = self.run_queue()
        self.assertEqual(report['processed'][0]['state'], 'blocked')
        self.assertFalse(status(queue.root, self.spec['id'])['delivery_ready'])

    def test_source_bytes_do_not_admit_rebound_receipts_without_matching_trim(self):
        self.add_source_bytes()
        self.prior['actual_tool_consumers'][0]['output_sha256'] = 'f' * 64
        write_json(self.prior_path, self.prior)
        prior_sha = digest(self.prior_path)
        self.metadata['prior_openmontage_receipt_sha256'] = prior_sha
        write_json(self.review / 'video.mp4.json', self.metadata)
        self.run['artifacts_sha256']['video.mp4.json'] = digest(self.review / 'video.mp4.json')
        self.run['prior_openmontage_receipt_sha256'] = prior_sha
        write_json(self.review / 'run.json', self.run)
        self.external_receipt['source']['prior_receipt_sha256'] = prior_sha
        write_json(self.receipt_path, self.external_receipt)
        self.request.update(prior_tool_receipt_sha256=prior_sha,
                            external_receipt_sha256=digest(self.receipt_path),
                            review_run_sha256=digest(self.review / 'run.json'))
        attempt = self.root / 'attempt-unbound-trim'; attempt.mkdir()
        result = run_job(self.request, attempt, external_media_root=self.external)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('successful free trim', result['blocker'])

    def test_completed_external_job_is_visible_in_read_only_queue_monitor(self):
        queue, _report = self.run_queue()
        result = inspect_queue(queue.root)
        self.assertEqual(result['status'], 'HEALTHY')
        self.assertEqual(result['jobs'], [{
            'id': self.spec['id'], 'adapter': 'content-control-external-media',
            'state': 'succeeded', 'attempts': 1,
            'resource_limits': {'max_attempts': 1, 'timeout_seconds': 30},
        }])
        self.assertEqual(result['alerts'], [])
        self.assertNotIn(self.request['external_receipt_sha256'], json.dumps(result))
        self.assertFalse(result['publication_enabled'])
        self.assertFalse(result['paid_generation_enabled'])
        self.assertFalse(result['deployed_monitor_verified'])
        self.assertFalse(result['twenty_four_hour_soak_verified'])

    def test_request_cannot_select_paths_commands_providers_or_approval(self):
        for key, value in (
                ('external_media_root', '/tmp/escape'), ('command', ['ffmpeg']),
                ('provider', 'remote'), ('publication_enabled', True),
                ('paid_generation_enabled', True), ('production_approved', True),
                ('production_ready', True), ('full_av_review', True)):
            changed = dict(self.request); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(changed)

    def test_missing_operator_root_blocks_without_invoking_any_tool(self):
        attempt = self.root / 'attempt'; attempt.mkdir()
        result = run_job(self.request, attempt)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['provider_calls'], 0)
        self.assertFalse((attempt / 'review').exists())

    def test_tampered_output_receipts_and_lineage_fail_closed(self):
        cases = ('video', 'external-receipt', 'prior-receipt', 'run', 'metadata')
        for case in cases:
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory(dir=self.root) as temporary:
                    clone = Path(temporary) / 'external';
                    import shutil
                    shutil.copytree(self.external, clone)
                    if case == 'video':
                        (clone / 'review/video.mp4').write_bytes(b'tampered')
                    elif case == 'external-receipt':
                        (clone / 'safe-reframe-receipt.json').write_text('{}')
                    elif case == 'prior-receipt':
                        (clone / 'diagnostics/prior-openmontage-receipt.json').write_text('{}')
                    elif case == 'run':
                        (clone / 'review/run.json').write_text('{}')
                    else:
                        (clone / 'review/video.mp4.json').write_text('{}')
                    attempt = Path(temporary) / 'attempt'; attempt.mkdir()
                    result = run_job(self.request, attempt, external_media_root=clone)
                    self.assertEqual(result['status'], 'BLOCKED')

    def test_rebound_malicious_gates_provider_calls_and_duplicate_keys_are_rejected(self):
        for path_name, mutation in (
                ('safe-reframe-receipt.json', lambda value: value['safety'].__setitem__('production_approved', True)),
                ('safe-reframe-receipt.json', lambda value: value['safety'].__setitem__('provider_calls', 1)),
                ('diagnostics/prior-openmontage-receipt.json', lambda value: value['safety'].__setitem__('paid_generation_enabled', True))):
            with self.subTest(path=path_name):
                path = self.external / path_name
                value = json.loads(path.read_text()); mutation(value); write_json(path, value)
                changed = dict(self.request)
                field = 'external_receipt_sha256' if path.name == 'safe-reframe-receipt.json' else 'prior_tool_receipt_sha256'
                changed[field] = digest(path)
                attempt = self.root / ('attempt-' + str(len(list(self.root.glob('attempt-*'))))); attempt.mkdir()
                self.assertEqual(run_job(changed, attempt, external_media_root=self.external)['status'], 'BLOCKED')
                if path.name == 'safe-reframe-receipt.json':
                    write_json(path, self.external_receipt)
                else:
                    write_json(path, self.prior)
        self.receipt_path.write_text('{"schema_version":1,"schema_version":1}')
        changed = dict(self.request, external_receipt_sha256=digest(self.receipt_path))
        attempt = self.root / 'attempt-duplicate'; attempt.mkdir()
        self.assertEqual(run_job(changed, attempt, external_media_root=self.external)['status'], 'BLOCKED')

    def test_rebound_receipt_cannot_omit_safety_claim_dirty_source_or_encode_approval(self):
        mutations = {
            'missing-safety': lambda value: value.pop('safety'),
            'dirty-checkout': lambda value: value['source'].__setitem__('checkout_clean', False),
            'generic-approved': lambda value: value.__setitem__('approved', True),
            'approved-status': lambda value: value['revision_package'].__setitem__('status', 'APPROVED'),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                value = json.loads(json.dumps(self.external_receipt))
                mutate(value); write_json(self.receipt_path, value)
                changed = dict(self.request, external_receipt_sha256=digest(self.receipt_path))
                attempt = self.root / ('attempt-schema-' + name); attempt.mkdir()
                result = run_job(changed, attempt, external_media_root=self.external)
                self.assertEqual(result['status'], 'BLOCKED')
                write_json(self.receipt_path, self.external_receipt)

    def test_symlinks_oversize_and_delivery_tamper_are_rejected(self):
        outside = self.root / 'outside.mp4'; outside.write_bytes((self.review / 'video.mp4').read_bytes())
        original = (self.review / 'video.mp4').read_bytes()
        (self.review / 'video.mp4').unlink(); (self.review / 'video.mp4').symlink_to(outside)
        attempt = self.root / 'attempt-link'; attempt.mkdir()
        self.assertEqual(run_job(self.request, attempt, external_media_root=self.external)['status'], 'BLOCKED')
        (self.review / 'video.mp4').unlink(); (self.review / 'video.mp4').write_bytes(original)
        with patch('integrations.content_control.external_media_job.MAX_MEDIA', 1):
            attempt = self.root / 'attempt-large'; attempt.mkdir()
            self.assertEqual(run_job(self.request, attempt, external_media_root=self.external)['status'], 'BLOCKED')

        queue, _ = self.run_queue()
        packaged = queue.root / 'attempts/offline-reframe/1/delivery/review/video.mp4'
        packaged.write_bytes(b'tampered after durable completion')
        with self.assertRaises(ValueError):
            verify_delivery(queue.root, self.spec['id'])
        self.assertFalse(status(queue.root, self.spec['id'])['delivery_ready'])


if __name__ == '__main__':
    unittest.main()
