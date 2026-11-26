"""Offline Floot payload staging tests; no provider write or playback claim."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from integrations.content_control import floot_private_preview_payload as payload_module
from integrations.content_control.floot_private_preview_payload import (
    READBACK_RECEIPT_SCOPE,
    SOURCE_SNAPSHOT_SCOPE,
    build_readback_observation,
    prepare_upload_payload,
    verify_readback_observation_bundle,
    verify_upload_payload,
)
from integrations.content_control.private_preview_binding import (
    FLAGS, ROLE_PATHS, verify_private_preview_binding,
)
from integrations.content_control.review_delivery import export_review
from integrations.content_control.review_package import digest
from integrations.content_control.test_cycle_queue_delivery import CycleDeliveryTests


class FlootPrivatePreviewPayloadTests(unittest.TestCase):
    setUp = CycleDeliveryTests.setUp
    tearDown = CycleDeliveryTests.tearDown
    queue_review = CycleDeliveryTests.queue_review

    def export(self):
        queue, _, _ = self.queue_review()
        delivery = self.base / 'floot-delivery'
        report = export_review(queue.root, 'cycle-test', delivery)
        return delivery, report

    def prepare(self):
        delivery, report = self.export()
        output = self.base / 'floot-payload'
        manifest = prepare_upload_payload(
            delivery, report['delivery_identity_sha256'], output)
        return delivery, report, output, manifest

    def readback_inputs(self):
        delivery, report, payload, manifest = self.prepare()
        readback = self.base / 'provider-readback'; readback.mkdir()
        for item in manifest['objects']:
            (readback / item['role']).write_bytes(
                (payload / item['staged_path']).read_bytes())
        source_files = {
            'src/App.tsx': 'a' * 64,
            ('cyzor-deliveries/' + report['delivery_identity_sha256'] +
             '/floot-upload-manifest.json'):
                digest(payload / 'floot-upload-manifest.json'),
        }
        snapshot = {
            'schema_version': 1,
            'status': 'PRIVATE_FLOOT_SOURCE_OBSERVED',
            'provider': 'floot',
            'project_id': 'private-preview-project',
            'source_version': '1795636751508',
            'source_checkpoint': 'a6edb9f9-8266-483f-b4e4-84b8e27fd49e',
            'source_files_sha256': source_files,
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'visibility': 'private',
            'published': False,
            'publication_enabled': False,
            'paid_inference_enabled': False,
            'scope': SOURCE_SNAPSHOT_SCOPE,
        }
        source = self.base / 'provider-source-snapshot.json'
        source.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + '\n')
        source_sha = digest(source)
        receipt_value = {
            'schema_version': 1,
            'status': 'PRIVATE_FLOOT_READBACK_COMPLETE',
            'provider': 'floot',
            'project_id': snapshot['project_id'],
            'source_version': snapshot['source_version'],
            'source_checkpoint': snapshot['source_checkpoint'],
            'source_snapshot_sha256': source_sha,
            'upload_manifest_sha256': digest(
                payload / 'floot-upload-manifest.json'),
            'readback_completed_at': datetime.now(timezone.utc).isoformat(),
            'visibility': 'private',
            'published': False,
            'publication_enabled': False,
            'paid_inference_enabled': False,
            'objects': [{
                'role': item['role'],
                'logical_key': item['logical_key'],
                'storage_key': item['storage_key'],
                'size_bytes': item['size_bytes'],
                'sha256': item['sha256'],
                'retrieval_method': 'provider_object_readback',
            } for item in manifest['objects']],
            'scope': READBACK_RECEIPT_SCOPE,
        }
        receipt = self.base / 'provider-readback-receipt.json'
        receipt.write_text(json.dumps(
            receipt_value, indent=2, sort_keys=True) + '\n')
        return (delivery, report, payload, readback, source, source_sha,
                snapshot, receipt, digest(receipt), receipt_value)

    def test_exact_five_roles_are_staged_for_private_add_only_upload(self):
        delivery, report, output, manifest = self.prepare()
        self.assertEqual({path.name for path in output.iterdir()},
                         {'floot-upload-manifest.json', 'objects'})
        self.assertEqual({path.name for path in (output / 'objects').iterdir()},
                         set(ROLE_PATHS))
        self.assertEqual(manifest, verify_upload_payload(
            delivery, report['delivery_identity_sha256'], output))
        self.assertEqual(manifest['status'], 'PRIVATE_UPLOAD_PAYLOAD_READY')
        self.assertFalse(manifest['provider_write_performed'])
        self.assertFalse(manifest['upload_completed'])
        self.assertFalse(manifest['readback_completed'])
        self.assertTrue(manifest['readback_required'])
        self.assertTrue(all(manifest[key] is False for key in FLAGS))
        for item in manifest['objects']:
            self.assertEqual(
                item['storage_key'],
                f"deliveries/{report['delivery_identity_sha256']}/{item['logical_key']}")
            self.assertTrue(item['add_only'])
            self.assertFalse(item['overwrite_allowed'])
            self.assertEqual(item['transfer_method'], 'raw_bytes')
            self.assertEqual(
                (output / item['staged_path']).read_bytes(),
                (delivery / item['logical_key']).read_bytes())

    def test_existing_contained_and_symlink_parent_outputs_are_rejected(self):
        delivery, report = self.export()
        existing = self.base / 'existing'; existing.mkdir()
        link = self.base / 'linked-parent'; link.symlink_to(self.base, target_is_directory=True)
        for output in (existing, delivery / 'payload', link / 'payload'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                prepare_upload_payload(
                    delivery, report['delivery_identity_sha256'], output)

    def test_publish_and_paid_runtime_flags_fail_before_staging(self):
        delivery, report = self.export()
        for name in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED',
                     'PAID_INFERENCE_ENABLED'):
            output = self.base / ('blocked-' + name.lower())
            with self.subTest(name=name), patch.dict(
                    os.environ, {name: 'true'}, clear=False), self.assertRaises(ValueError):
                prepare_upload_payload(
                    delivery, report['delivery_identity_sha256'], output)
            self.assertFalse(output.exists())

    def test_each_object_must_fit_the_provider_limit(self):
        delivery, report = self.export()
        for role, logical in ROLE_PATHS.items():
            limit = (delivery / logical).stat().st_size - 1
            with self.subTest(role=role), patch.object(
                    payload_module, 'MAX_FLOOT_OBJECT', limit), self.assertRaises(ValueError):
                prepare_upload_payload(
                    delivery, report['delivery_identity_sha256'],
                    self.base / f'oversized-{role}')

    def test_staged_bytes_and_manifest_cannot_be_swapped_or_promoted(self):
        delivery, report, output, manifest = self.prepare()
        source_package = output / 'objects/source_package'
        delivery_receipt = output / 'objects/delivery_receipt'
        source_bytes, receipt_bytes = source_package.read_bytes(), delivery_receipt.read_bytes()
        source_package.write_bytes(receipt_bytes)
        delivery_receipt.write_bytes(source_bytes)
        with self.assertRaises(ValueError):
            verify_upload_payload(delivery, report['delivery_identity_sha256'], output)
        source_package.write_bytes(source_bytes); delivery_receipt.write_bytes(receipt_bytes)

        path = output / 'floot-upload-manifest.json'
        changed = json.loads(path.read_text())
        changed['objects'][0]['storage_key'] = 'https://example.test/signed-token'
        changed['provider_write_performed'] = True
        path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            verify_upload_payload(delivery, report['delivery_identity_sha256'], output)

    def test_source_change_during_staging_leaves_no_complete_payload(self):
        delivery, report = self.export()
        output = self.base / 'toctou-payload'
        verified = payload_module.verify_exported_cycle(
            delivery, report['delivery_identity_sha256'])
        expected = payload_module._expected_objects(delivery, verified)
        changed = json.loads(json.dumps(expected))
        changed[0]['sha256'] = '0' * 64
        with patch.object(payload_module, '_expected_objects',
                          side_effect=[expected, changed]), self.assertRaises(ValueError):
            prepare_upload_payload(
                delivery, report['delivery_identity_sha256'], output)
        self.assertFalse(output.exists())

    def test_atomic_publish_never_replaces_a_concurrent_destination(self):
        delivery, report = self.export()
        output = self.base / 'concurrent-payload'

        def collide(stage, destination):
            destination.mkdir()
            (destination / 'sentinel').write_text('concurrent owner')
            raise FileExistsError('destination appeared')

        with patch.object(payload_module, '_publish_restore', side_effect=collide), \
                self.assertRaises(FileExistsError):
            prepare_upload_payload(
                delivery, report['delivery_identity_sha256'], output)
        self.assertEqual((output / 'sentinel').read_text(), 'concurrent owner')

    def test_failed_post_publish_replay_removes_only_owned_output(self):
        delivery, report = self.export()
        output = self.base / 'failed-final-replay'
        original = payload_module.verify_upload_payload

        def verify(delivery_dir, identity, candidate):
            if Path(candidate) == output:
                raise ValueError('forced final replay failure')
            return original(delivery_dir, identity, candidate)

        with patch.object(payload_module, 'verify_upload_payload', side_effect=verify), \
                self.assertRaisesRegex(ValueError, 'forced final replay'):
            prepare_upload_payload(
                delivery, report['delivery_identity_sha256'], output)
        self.assertFalse(output.exists())

    def test_cli_prepare_and_verify_fail_closed(self):
        delivery, report = self.export()
        output = self.base / 'cli-payload'
        base = [sys.executable, '-m',
                'integrations.content_control.floot_private_preview_payload']
        common = ['--delivery', str(delivery), '--expected-delivery-identity',
                  report['delivery_identity_sha256'], '--payload', str(output)]
        prepared = subprocess.run(base + ['prepare'] + common, text=True,
                                  capture_output=True, timeout=30)
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        verified = subprocess.run(base + ['verify'] + common, text=True,
                                  capture_output=True, timeout=30)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        (output / 'objects/captions').write_bytes(b'changed')
        blocked = subprocess.run(base + ['verify'] + common, text=True,
                                 capture_output=True, timeout=30)
        self.assertEqual(blocked.returncode, 2)
        self.assertEqual(json.loads(blocked.stdout)['status'], 'BLOCKED')

    def test_complete_readback_builds_strict_observation_without_acceptance(self):
        (delivery, report, payload, readback, source, source_sha, _, receipt,
         receipt_sha, _) = self.readback_inputs()
        output = self.base / 'private-preview-observation'
        receipt = build_readback_observation(
            delivery, report['delivery_identity_sha256'], payload, readback,
            source, source_sha, receipt, receipt_sha, output)
        self.assertEqual(receipt['status'], 'PRIVATE_READBACK_OBSERVATION_READY')
        self.assertTrue(receipt['external_observation_pin_required'])
        self.assertTrue(receipt['external_bundle_pin_required'])
        self.assertFalse(receipt['provider_write_independently_verified'])
        self.assertTrue(all(receipt[key] is False for key in FLAGS))
        self.assertEqual({path.name for path in output.iterdir()}, {
            'private-preview-observation.json', 'floot-readback-receipt.json',
            'floot-source-snapshot.json', 'readback-observation-bundle.json'})
        binding = verify_private_preview_binding(
            delivery, report['delivery_identity_sha256'],
            output / 'private-preview-observation.json',
            digest(output / 'private-preview-observation.json'))
        self.assertEqual(binding['status'], 'PASS')
        self.assertFalse(binding['playback_verified'])
        self.assertFalse(binding['physical_phone_verified'])
        replay = verify_readback_observation_bundle(
            delivery, report['delivery_identity_sha256'], payload, readback,
            output, receipt['source_snapshot_sha256'],
            receipt['readback_receipt_sha256'], receipt['observation_sha256'],
            receipt['bundle_receipt_sha256'])
        self.assertEqual(replay['status'], 'PASS')

    def test_partial_or_changed_readback_emits_no_observation(self):
        (delivery, report, payload, readback, source, source_sha, _, receipt,
         receipt_sha, _) = self.readback_inputs()
        for mode in ('missing', 'changed'):
            with self.subTest(mode=mode):
                target = readback / 'captions'
                original = target.read_bytes()
                if mode == 'missing':
                    target.unlink()
                else:
                    target.write_bytes(original + b'changed')
                output = self.base / ('blocked-observation-' + mode + '.json')
                with self.assertRaises(ValueError):
                    build_readback_observation(
                        delivery, report['delivery_identity_sha256'], payload,
                        readback, source, source_sha, receipt, receipt_sha, output)
                self.assertFalse(output.exists())
                target.write_bytes(original)

    def test_source_snapshot_pin_physical_keys_and_safety_are_required(self):
        (delivery, report, payload, readback, source, source_sha, snapshot,
         receipt, receipt_sha, receipt_value) = self.readback_inputs()
        cases = []
        changed = json.loads(json.dumps(snapshot)); changed['published'] = True
        cases.append(changed)
        for index, changed in enumerate(cases):
            with self.subTest(index=index):
                source.write_text(json.dumps(changed))
                changed_sha = digest(source)
                with self.assertRaises(ValueError):
                    build_readback_observation(
                        delivery, report['delivery_identity_sha256'], payload,
                        readback, source, changed_sha, receipt, receipt_sha,
                        self.base / f'unsafe-observation-{index}.json')
        source.write_text(json.dumps(snapshot))
        with self.assertRaisesRegex(ValueError, 'trusted expected identity'):
            build_readback_observation(
                delivery, report['delivery_identity_sha256'], payload,
                readback, source, source_sha, receipt, receipt_sha,
                self.base / 'wrong-pin-observation.json')

        source.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + '\n')
        receipt_value['source_snapshot_sha256'] = digest(source)
        receipt_value['objects'][0]['storage_key'] = 'deliveries/wrong/key'
        receipt.write_text(json.dumps(receipt_value))
        with self.assertRaisesRegex(ValueError, 'physical-key binding'):
            build_readback_observation(
                delivery, report['delivery_identity_sha256'], payload,
                readback, source, digest(source), receipt, digest(receipt),
                self.base / 'wrong-physical-key')

    def test_staged_bytes_and_hardlinks_cannot_masquerade_as_provider_readback(self):
        (delivery, report, payload, readback, source, source_sha, _, receipt,
         receipt_sha, _) = self.readback_inputs()
        with self.assertRaisesRegex(ValueError, 'separate from payload'):
            build_readback_observation(
                delivery, report['delivery_identity_sha256'], payload,
                payload / 'objects', source, source_sha, receipt, receipt_sha,
                self.base / 'contained-readback')
        target = readback / 'captions'
        target.unlink()
        os.link(payload / 'objects/captions', target)
        with self.assertRaisesRegex(ValueError, 'must not hardlink'):
            build_readback_observation(
                delivery, report['delivery_identity_sha256'], payload,
                readback, source, source_sha, receipt, receipt_sha,
                self.base / 'hardlinked-readback')

        target.unlink()
        target.write_bytes((payload / 'objects/captions').read_bytes())
        real_open = os.open

        def swap_open(path, flags, *args, **kwargs):
            if Path(path) == target:
                return real_open(payload / 'objects/captions', flags, *args, **kwargs)
            return real_open(path, flags, *args, **kwargs)

        with patch.object(payload_module.os, 'open', side_effect=swap_open), \
                self.assertRaisesRegex(ValueError, 'must not hardlink'):
            build_readback_observation(
                delivery, report['delivery_identity_sha256'], payload,
                readback, source, source_sha, receipt, receipt_sha,
                self.base / 'aba-readback')

    def test_readback_receipt_chronology_and_source_identity_are_required(self):
        (delivery, report, payload, readback, source, source_sha, snapshot, receipt,
         _, receipt_value) = self.readback_inputs()
        changed = json.loads(json.dumps(receipt_value))
        changed['source_checkpoint'] = 'different-checkpoint'
        receipt.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'physical-key binding'):
            build_readback_observation(
                delivery, report['delivery_identity_sha256'], payload,
                readback, source, source_sha, receipt, digest(receipt),
                self.base / 'wrong-checkpoint')

        changed = json.loads(json.dumps(receipt_value))
        changed['readback_completed_at'] = '2999-01-01T00:00:00+00:00'
        receipt.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'readback completion timestamp'):
            build_readback_observation(
                delivery, report['delivery_identity_sha256'], payload,
                readback, source, source_sha, receipt, digest(receipt),
                self.base / 'future-readback')

        stale_source = json.loads(json.dumps(snapshot))
        stale_source['observed_at'] = '2000-01-01T00:00:00+00:00'
        source.write_text(json.dumps(stale_source))
        stale_source_sha = digest(source)
        changed = json.loads(json.dumps(receipt_value))
        changed['source_snapshot_sha256'] = stale_source_sha
        receipt.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'predates durable delivery'):
            build_readback_observation(
                delivery, report['delivery_identity_sha256'], payload,
                readback, source, stale_source_sha, receipt, digest(receipt),
                self.base / 'stale-source')

    def test_readback_bundle_publish_is_no_replace_and_owned_cleanup_only(self):
        (delivery, report, payload, readback, source, source_sha, _, receipt,
         receipt_sha, _) = self.readback_inputs()
        output = self.base / 'concurrent-readback-bundle'

        def collide(stage, destination):
            destination.mkdir()
            (destination / 'sentinel').write_text('concurrent owner')
            raise FileExistsError('destination appeared')

        with patch.object(payload_module, '_publish_restore', side_effect=collide), \
                self.assertRaises(FileExistsError):
            build_readback_observation(
                delivery, report['delivery_identity_sha256'], payload,
                readback, source, source_sha, receipt, receipt_sha, output)
        self.assertEqual((output / 'sentinel').read_text(), 'concurrent owner')

        owned_output = self.base / 'owned-failed-final-replay'
        original = payload_module.verify_private_preview_binding
        calls = 0

        def verify(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError('forced final binding replay failure')
            return original(*args, **kwargs)

        with patch.object(payload_module, 'verify_private_preview_binding',
                          side_effect=verify), self.assertRaisesRegex(
                              ValueError, 'forced final binding replay'):
            build_readback_observation(
                delivery, report['delivery_identity_sha256'], payload,
                readback, source, source_sha, receipt, receipt_sha, owned_output)
        self.assertFalse(owned_output.exists())


if __name__ == '__main__':
    unittest.main()
