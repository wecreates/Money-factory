"""Deployment-to-durable private-preview binding tests; not playback proof."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from integrations.local_agent_queue import canonical
from integrations.content_control.private_preview_binding import (
    FLAGS,
    OBSERVATION_SCOPE,
    ROLE_PATHS,
    verify_private_preview_binding,
)
from integrations.content_control import private_preview_binding as binding_module
from integrations.content_control.review_delivery import export_review
from integrations.content_control.review_package import digest
from integrations.content_control.test_cycle_queue_delivery import CycleDeliveryTests


class PrivatePreviewBindingTests(unittest.TestCase):
    setUp = CycleDeliveryTests.setUp
    tearDown = CycleDeliveryTests.tearDown
    queue_review = CycleDeliveryTests.queue_review

    def export(self):
        queue, _, _ = self.queue_review()
        delivery = self.base / 'binding-delivery'
        report = export_review(queue.root, 'cycle-test', delivery)
        return delivery, report

    def observation(self, delivery, *, omitted=(), observed_at=None):
        source_files = {
            'src/App.tsx': 'a' * 64,
            'src/helpers/reviewEvidence.ts': 'b' * 64,
        }
        objects = []
        for role, key in ROLE_PATHS.items():
            if role not in omitted:
                path = delivery / key
                objects.append({
                    'role': role,
                    'key': key,
                    'size_bytes': path.stat().st_size,
                    'sha256': digest(path),
                })
        value = {
            'schema_version': 1,
            'status': 'UNPUBLISHED_PRIVATE_PREVIEW_OBSERVED',
            'provider': 'floot',
            'project_id': 'private-preview-project',
            'source_version': '1795636751508',
            'source_checkpoint': 'a6edb9f9-8266-483f-b4e4-84b8e27fd49e',
            'source_files_sha256': source_files,
            'source_manifest_sha256': hashlib.sha256(
                canonical(source_files).encode()).hexdigest(),
            'observed_at': observed_at or datetime.now(timezone.utc).isoformat(),
            'visibility': 'private',
            'objects': objects,
            'scope': OBSERVATION_SCOPE,
            **FLAGS,
        }
        path = self.base / ('observation-' + str(len(omitted)) + '.json')
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
        return path, value, digest(path)

    def test_observation_cannot_predate_durable_delivery(self):
        delivery, report = self.export()
        completed_at = json.loads((delivery / 'package.json').read_text())[
            'provenance']['completed_at_unix']
        for offset, accepted in ((-0.000001, False), (0, True), (0.000001, True)):
            with self.subTest(offset=offset):
                observed_at = datetime.fromtimestamp(
                    completed_at + offset, timezone.utc).isoformat()
                observation, _, observed_sha = self.observation(
                    delivery, observed_at=observed_at)
                if accepted:
                    result = verify_private_preview_binding(
                        delivery, report['delivery_identity_sha256'],
                        observation, observed_sha)
                    self.assertEqual(result['status'], 'PASS')
                else:
                    with self.assertRaisesRegex(ValueError, 'predates'):
                        verify_private_preview_binding(
                            delivery, report['delivery_identity_sha256'],
                            observation, observed_sha)

    def test_completion_time_uses_hash_bound_receipt_and_microsecond_precision(self):
        delivery, _ = self.export()
        expected = binding_module._expected_objects(delivery)
        receipt = json.loads((delivery / 'package.json').read_text())
        receipt['provenance']['completed_at_unix'] = 1795656478.1234567
        forged = (json.dumps(receipt, sort_keys=True) + '\n').encode()
        with patch.object(Path, 'read_bytes', return_value=forged), \
                self.assertRaisesRegex(ValueError, 'changed during chronology'):
            binding_module._delivery_completion(delivery, expected)

        matching = json.loads(json.dumps(expected))
        matching['delivery_receipt']['sha256'] = hashlib.sha256(forged).hexdigest()
        with patch.object(Path, 'read_bytes', return_value=forged):
            completed = binding_module._delivery_completion(delivery, matching)
        self.assertEqual(
            completed,
            datetime.fromtimestamp(1795656478.1234567, timezone.utc))

    def write(self, path, value):
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
        return digest(path)

    def test_exact_five_role_binding_passes_with_all_acceptance_false(self):
        delivery, report = self.export()
        observation, value, observed_sha = self.observation(delivery)
        result = verify_private_preview_binding(
            delivery, report['delivery_identity_sha256'], observation, observed_sha)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['candidate_sha256'], report['candidate_sha256'])
        self.assertEqual(result['caption_sha256'], digest(delivery / 'review/captions.vtt'))
        self.assertEqual(result['package_sha256'], report['package_sha256'])
        self.assertEqual(result['archive_sha256'], report['archive_sha256'])
        self.assertEqual(result['delivery_receipt_sha256'], digest(delivery / 'package.json'))
        self.assertEqual(result['deployment_observation_sha256'], observed_sha)
        self.assertEqual(result['source_manifest_sha256'], value['source_manifest_sha256'])
        self.assertEqual(result['missing_roles'], [])
        self.assertTrue(all(result[key] is False for key in FLAGS))
        self.assertIn('remain unverified', result['scope'])
        identity = {key: result[key] for key in (
            'delivery_identity_sha256', 'delivery_receipt_sha256',
            'candidate_sha256', 'caption_sha256', 'package_sha256',
            'archive_sha256', 'deployment_observation_sha256', 'provider',
            'project_id', 'source_version', 'source_checkpoint',
            'source_files_sha256', 'source_manifest_sha256', 'observed_at',
            'visibility', 'objects', *FLAGS,
        )}
        self.assertEqual(
            result['preview_binding_identity_sha256'],
            hashlib.sha256(canonical(identity).encode()).hexdigest())

    def test_each_missing_role_is_explicitly_blocked_and_present_bytes_match(self):
        delivery, report = self.export()
        for role in ROLE_PATHS:
            with self.subTest(role=role):
                observation, _, observed_sha = self.observation(delivery, omitted=(role,))
                result = verify_private_preview_binding(
                    delivery, report['delivery_identity_sha256'], observation, observed_sha)
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertEqual(result['missing_roles'], [role])
                self.assertTrue(all(result[key] is False for key in FLAGS))

    def test_present_hash_size_and_key_mismatches_fail_instead_of_blocking(self):
        delivery, report = self.export()
        observation, value, _ = self.observation(delivery)
        for field, replacement in (
                ('sha256', '0' * 64),
                ('size_bytes', value['objects'][0]['size_bytes'] + 1),
                ('key', 'review/other.mp4')):
            with self.subTest(field=field):
                changed = json.loads(json.dumps(value))
                changed['objects'][0][field] = replacement
                observed_sha = self.write(observation, changed)
                with self.assertRaisesRegex(ValueError, 'object'):
                    verify_private_preview_binding(
                        delivery, report['delivery_identity_sha256'], observation, observed_sha)

    def test_duplicate_unknown_and_url_evidence_cannot_enter_the_inventory(self):
        delivery, report = self.export()
        observation, value, _ = self.observation(delivery)
        cases = []
        duplicate = json.loads(json.dumps(value)); duplicate['objects'][1] = duplicate['objects'][0]
        cases.append(duplicate)
        unknown = json.loads(json.dumps(value)); unknown['objects'][0]['role'] = 'signed_url'
        cases.append(unknown)
        url = json.loads(json.dumps(value)); url['objects'][0]['key'] = 'https://example.test/signed?token=x'
        cases.append(url)
        extra = json.loads(json.dumps(value)); extra['http_status'] = 200
        cases.append(extra)
        for index, changed in enumerate(cases):
            with self.subTest(index=index):
                observed_sha = self.write(observation, changed)
                with self.assertRaises(ValueError):
                    verify_private_preview_binding(
                        delivery, report['delivery_identity_sha256'], observation, observed_sha)

    def test_source_manifest_safety_flags_and_visibility_fail_closed(self):
        delivery, report = self.export()
        observation, value, _ = self.observation(delivery)
        changes = [
            ('source_manifest_sha256', '0' * 64),
            ('visibility', 'public'),
            ('published', True),
            ('publication_enabled', True),
            ('paid_inference_enabled', True),
            ('physical_phone_verified', True),
            ('full_av_review', True),
        ]
        for field, replacement in changes:
            with self.subTest(field=field):
                changed = json.loads(json.dumps(value)); changed[field] = replacement
                observed_sha = self.write(observation, changed)
                with self.assertRaises(ValueError):
                    verify_private_preview_binding(
                        delivery, report['delivery_identity_sha256'], observation, observed_sha)

    def test_future_non_utc_and_nonnormalized_source_evidence_fail_closed(self):
        delivery, report = self.export()
        observation, value, _ = self.observation(delivery)
        changes = []
        future = json.loads(json.dumps(value))
        future['observed_at'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        changes.append(future)
        non_utc = json.loads(json.dumps(value))
        non_utc['observed_at'] = '2026-11-25T16:00:00-08:00'
        changes.append(non_utc)
        path_change = json.loads(json.dumps(value))
        path_change['source_files_sha256']['src//App.tsx'] = \
            path_change['source_files_sha256'].pop('src/App.tsx')
        path_change['source_manifest_sha256'] = hashlib.sha256(
            canonical(path_change['source_files_sha256']).encode()).hexdigest()
        changes.append(path_change)
        traversal = json.loads(json.dumps(value))
        traversal['source_files_sha256']['../App.tsx'] = \
            traversal['source_files_sha256'].pop('src/App.tsx')
        traversal['source_manifest_sha256'] = hashlib.sha256(
            canonical(traversal['source_files_sha256']).encode()).hexdigest()
        changes.append(traversal)
        empty = json.loads(json.dumps(value))
        empty['source_files_sha256'] = {}
        empty['source_manifest_sha256'] = hashlib.sha256(
            canonical(empty['source_files_sha256']).encode()).hexdigest()
        changes.append(empty)
        url_identity = json.loads(json.dumps(value))
        url_identity['project_id'] = 'https://example.test/project'
        changes.append(url_identity)
        for index, changed in enumerate(changes):
            with self.subTest(index=index):
                observed_sha = self.write(observation, changed)
                with self.assertRaises(ValueError):
                    verify_private_preview_binding(
                        delivery, report['delivery_identity_sha256'], observation, observed_sha)

    def test_transient_object_snapshot_cannot_survive_final_replay(self):
        delivery, report = self.export()
        observation, _, observed_sha = self.observation(delivery)
        first = binding_module._expected_objects(delivery)
        second = json.loads(json.dumps(first))
        second['candidate_video']['sha256'] = '0' * 64
        with patch.object(binding_module, '_expected_objects',
                          side_effect=[first, second]), \
                self.assertRaisesRegex(ValueError, 'changed during binding'):
            verify_private_preview_binding(
                delivery, report['delivery_identity_sha256'], observation, observed_sha)

    def test_external_hashes_reject_coherent_observation_and_delivery_rewrites(self):
        delivery, report = self.export()
        observation, value, observed_sha = self.observation(delivery)
        changed = json.loads(json.dumps(value)); changed['source_version'] = 'different-version'
        self.write(observation, changed)
        with self.assertRaisesRegex(ValueError, 'trusted expected identity'):
            verify_private_preview_binding(
                delivery, report['delivery_identity_sha256'], observation, observed_sha)

        observation, _, observed_sha = self.observation(delivery)
        video = delivery / 'review/video.mp4'
        video.write_bytes(video.read_bytes() + b'changed')
        with self.assertRaises(ValueError):
            verify_private_preview_binding(
                delivery, report['delivery_identity_sha256'], observation, observed_sha)

    def test_duplicate_json_nonfinite_and_symlink_observation_fail(self):
        delivery, report = self.export()
        observation, value, _ = self.observation(delivery)
        raw = json.dumps(value)
        observation.write_text(raw[:-1] + ',"provider":"duplicate"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            verify_private_preview_binding(
                delivery, report['delivery_identity_sha256'], observation, digest(observation))
        observation.write_text(raw.replace('"schema_version": 1',
                                           '"schema_version": NaN'))
        with self.assertRaisesRegex(ValueError, 'Nonfinite'):
            verify_private_preview_binding(
                delivery, report['delivery_identity_sha256'], observation, digest(observation))
        target = self.base / 'real-observation.json'; target.write_text(raw)
        observation.unlink(); observation.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            verify_private_preview_binding(
                delivery, report['delivery_identity_sha256'], observation, digest(target))

    def test_cli_returns_zero_only_for_complete_binding(self):
        delivery, report = self.export()
        observation, _, observed_sha = self.observation(delivery)
        command = [
            sys.executable, '-m', 'integrations.content_control.private_preview_binding',
            '--delivery', str(delivery),
            '--expected-delivery-identity', report['delivery_identity_sha256'],
            '--observation', str(observation),
            '--expected-observation-identity', observed_sha,
        ]
        complete = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
        self.assertEqual(json.loads(complete.stdout)['status'], 'PASS')
        observation, _, observed_sha = self.observation(
            delivery, omitted=('source_package', 'review_archive', 'delivery_receipt'))
        command[8] = str(observation)
        command[-1] = observed_sha
        blocked = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(blocked.returncode, 2)
        self.assertEqual(json.loads(blocked.stdout)['status'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()
