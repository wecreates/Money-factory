"""Offline Floot payload staging tests; no provider write or playback claim."""
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
    prepare_upload_payload,
    verify_upload_payload,
)
from integrations.content_control.private_preview_binding import FLAGS, ROLE_PATHS
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


if __name__ == '__main__':
    unittest.main()
