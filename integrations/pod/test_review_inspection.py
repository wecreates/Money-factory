"""Read-only recovery checks; synthetic packages never establish live acceptance."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch

import inspect_review as inspection
import test_production_snapshot as fixture


class ReviewInspectionTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ProductionSnapshotTests(); self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        with patch.object(fixture.agent, 'run_review_child', side_effect=self.case.finish):
            self.receipt = self.case.run_agent()
        self.final = self.case.output/'money-factory-receipt.json'

    def inspect(self): return inspection.inspect_review(self.case.job, self.case.output)

    def snapshot(self):
        return {str(p.relative_to(self.case.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.case.root.rglob('*') if p.is_file()}

    def test_complete_package_is_read_only_and_never_claims_approval_or_durability(self):
        staging = self.case.output/'.mf-receipt-leftover.tmp'
        staging.write_bytes(b'leftover; retain for diagnosis')
        before = self.snapshot()
        with patch.object(inspection, 'validate_review_output', wraps=inspection.validate_review_output) as verify, \
             patch.object(subprocess, 'Popen', side_effect=AssertionError('must not execute a renderer')):
            value = self.inspect()
        verify.assert_called_once()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(value['status'], 'VERIFIED_REVIEW_FILES')
        self.assertEqual(value['review_status'], 'REVIEW_REQUIRED')
        for field in ('publication_enabled', 'production_ready', 'paid_generation_enabled',
                      'marketplace_ready', 'durability_verified', 'approval_verified'):
            self.assertIs(value[field], False)
        self.assertEqual(value['package_sha256'], self.receipt['package_sha256'])
        self.assertEqual(value['input_sha256'], self.receipt['input_sha256'])
        self.assertEqual(value['receipt_sha256'], hashlib.sha256(self.final.read_bytes()).hexdigest())
        self.assertEqual(value['remaining_checks'], self.receipt['remaining_checks'])

    def test_real_cli_needs_only_job_and_existing_output(self):
        before = self.snapshot()
        result = subprocess.run([sys.executable, str(Path(inspection.__file__).resolve()),
            '--job', str(self.case.job), '--output', str(self.case.output)],
            capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'VERIFIED_REVIEW_FILES')
        self.assertEqual(self.snapshot(), before)

    def test_changed_original_input_is_rejected_before_artifact_reads(self):
        self.case.job.write_bytes(self.case.body+b' ')
        with patch.object(inspection, 'validate_review_output', side_effect=AssertionError('artifact work reached')):
            with self.assertRaisesRegex(ValueError, '^RECEIPT_INPUT_MISMATCH$'): self.inspect()

    def test_receipt_result_disagreement_is_rejected(self):
        for key, value in (('package_sha256', '0'*64), ('unexpected', True)):
            with self.subTest(key=key):
                self.final.write_text(json.dumps(dict(self.receipt, **{key:value})))
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, '^RECEIPT_RESULT_MISMATCH$'): self.inspect()
                self.assertEqual(self.snapshot(), before)

    def test_boolean_integer_and_nonfinite_extras_are_not_equivalent_receipts(self):
        path = self.case.output/'result.json'
        result = json.loads(path.read_text()); result['counter'] = 1
        path.write_text(json.dumps(result))
        for value in (True, float('nan'), float('inf')):
            with self.subTest(value=value):
                self.final.write_text(json.dumps(dict(self.receipt, counter=value)))
                with self.assertRaises(ValueError): self.inspect()

    def test_missing_or_corrupt_artifact_is_rejected_without_repair(self):
        path = self.case.output/'package/art.bin'
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, '^ARTIFACT_HASH_MISMATCH$'): self.inspect()
        path.unlink()
        with self.assertRaises(FileNotFoundError): self.inspect()
        self.assertFalse(path.exists())

    def test_missing_and_truncated_receipts_are_never_recreated(self):
        for content in (b'{', b'\xff', None):
            with self.subTest(content=content):
                if content is None: self.final.unlink()
                else: self.final.write_bytes(content)
                with self.assertRaises((ValueError, FileNotFoundError)): self.inspect()
                if content is None: self.assertFalse(self.final.exists())
                else: self.assertEqual(self.final.read_bytes(), content)

    def test_receipt_symlink_fifo_and_oversize_are_rejected_without_blocking(self):
        self.final.unlink()
        self.final.symlink_to(self.case.output/'result.json')
        with self.assertRaises(OSError): self.inspect()
        self.final.unlink(); os.mkfifo(self.final)
        result = subprocess.run([sys.executable, str(Path(inspection.__file__).resolve()),
            '--job', str(self.case.job), '--output', str(self.case.output)],
            capture_output=True, text=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('OUTPUT_FILE_INVALID', result.stderr)
        self.final.unlink(); self.final.write_bytes(b' '* (inspection.MAX_OUTPUT_JSON_BYTES+1))
        with self.assertRaisesRegex(ValueError, '^OUTPUT_TOO_LARGE$'): self.inspect()

    def test_receipt_or_result_release_claims_are_rejected(self):
        for target in (self.final, self.case.output/'result.json'):
            original = target.read_bytes()
            try:
                value = json.loads(original); value['publication_enabled'] = True
                target.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, '^RESULT_SCOPE_INVALID$'): self.inspect()
            finally: target.write_bytes(original)

    def test_manifest_scope_is_rechecked_after_receipt_commit(self):
        path = self.case.output/'package/manifest.json'
        value = json.loads(path.read_text()); value['platform'] = 'redbubble'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, '^MANIFEST_SCOPE_INVALID$'): self.inspect()

    def test_ineligible_input_is_not_accepted_for_recovery(self):
        for value in ({'publication_enabled':True}, [],
                      {'publication_enabled':False,'paid_generation_enabled':False,'platform':'etsy'}):
            with self.subTest(value=value):
                self.case.job.write_text(json.dumps(value))
                with self.assertRaises(ValueError): self.inspect()

    def test_postcommit_sync_failure_can_be_inspected_without_claiming_durability(self):
        self.final.unlink()
        real_sync = os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode): raise OSError('injected directory sync failure')
            real_sync(fd)
        with patch.object(fixture.agent.os, 'fsync', side_effect=fail_directory):
            with self.assertRaisesRegex(RuntimeError, '^RECEIPT_COMMITTED_RECOVERY_REQUIRED$'):
                fixture.agent.write_receipt(self.case.output, self.receipt)
        before = self.snapshot()
        result = self.inspect()
        self.assertIs(result['durability_verified'], False)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__': unittest.main()
