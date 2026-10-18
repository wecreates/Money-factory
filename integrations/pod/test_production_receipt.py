"""Receipt commit fault injection; synthetic bytes are not live acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class ReceiptCommitTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('receipt_agent', Path(__file__).with_name('production_agent.py'))
        self.agent = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.agent)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.final = self.root/'money-factory-receipt.json'
        self.value = {'status':'REVIEW_REQUIRED','publication_enabled':False,'title':'Étoile 日本語'}

    def save(self): self.agent.write_receipt(self.root, self.value)

    def assert_clean(self):
        self.assertFalse(self.final.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_complete_synced_bytes_precede_exclusive_commit(self):
        real_sync, real_link = os.fsync, os.link
        events = []
        def sync(fd):
            kind = 'directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file'
            events.append(kind)
            self.assertEqual(self.final.exists(), kind == 'directory')
            real_sync(fd)
        def link(*args, **kwargs):
            self.assertEqual(events, ['file'])
            real_link(*args, **kwargs)
            self.assertEqual(json.loads(self.final.read_text()), self.value)
            events.append('link')
        with patch.object(self.agent.os, 'fsync', side_effect=sync), \
             patch.object(self.agent.os, 'link', side_effect=link): self.save()
        self.assertEqual(events, ['file','link','directory'])
        self.assertEqual(list(self.root.iterdir()), [self.final])
        self.assertEqual(self.final.stat().st_mode & 0o777, 0o600)

    def test_short_writes_complete_and_zero_write_fails_cleanly(self):
        real_write = os.write
        with patch.object(self.agent.os, 'write', side_effect=lambda fd,b:real_write(fd,b[:7])):
            self.save()
        self.assertEqual(json.loads(self.final.read_text()), self.value)
        self.final.unlink()
        with patch.object(self.agent.os, 'write', return_value=0):
            with self.assertRaisesRegex(OSError, 'RECEIPT_WRITE_INCOMPLETE'): self.save()
        self.assert_clean()

    def test_precommit_write_sync_and_link_failures_leave_no_receipt(self):
        for operation in ('write', 'fsync', 'link'):
            with self.subTest(operation=operation):
                with patch.object(self.agent.os, operation, side_effect=OSError('injected storage failure')):
                    with self.assertRaisesRegex(OSError, 'injected storage failure'): self.save()
                self.assert_clean()
        self.save()  # Direct persistence retry after handled precommit failure.
        self.assertEqual(json.loads(self.final.read_text()), self.value)

    def test_existing_file_symlink_fifo_and_directory_are_never_replaced(self):
        for kind in ('file','symlink','fifo','directory'):
            with self.subTest(kind=kind):
                target = self.root/'target'
                if kind=='file': self.final.write_bytes(b'existing receipt')
                elif kind=='symlink':
                    target.write_bytes(b'existing target'); self.final.symlink_to(target)
                elif kind=='fifo': os.mkfifo(self.final)
                else: self.final.mkdir()
                original = self.final.lstat()
                with self.assertRaises(FileExistsError): self.save()
                current = self.final.lstat()
                self.assertEqual((current.st_ino,current.st_mode),(original.st_ino,original.st_mode))
                if kind=='file': self.assertEqual(self.final.read_bytes(),b'existing receipt')
                if kind=='symlink': self.assertEqual(target.read_bytes(),b'existing target')
                self.assertFalse(list(self.root.glob('.mf-receipt-*.tmp')))
                if kind=='directory': self.final.rmdir()
                else: self.final.unlink()
                if target.exists(): target.unlink()

    def test_concurrent_receipt_winner_is_preserved(self):
        real_link = os.link
        def race(*args, **kwargs):
            self.final.write_bytes(b'other completed receipt')
            return real_link(*args, **kwargs)
        with patch.object(self.agent.os, 'link', side_effect=race):
            with self.assertRaises(FileExistsError): self.save()
        self.assertEqual(self.final.read_bytes(), b'other completed receipt')
        self.assertFalse(list(self.root.glob('.mf-receipt-*.tmp')))

    def test_directory_sync_failure_retains_complete_committed_receipt(self):
        real_sync = os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode): raise OSError('directory sync failed')
            real_sync(fd)
        with patch.object(self.agent.os, 'fsync', side_effect=fail_directory):
            with self.assertRaisesRegex(RuntimeError, '^RECEIPT_COMMITTED_RECOVERY_REQUIRED$'): self.save()
        self.assertEqual(json.loads(self.final.read_text()), self.value)
        self.assertEqual(list(self.root.iterdir()), [self.final])
        with self.assertRaises(FileExistsError): self.save()

    def test_postcommit_cleanup_failure_reports_recovery_without_deleting_final(self):
        with patch.object(self.agent.os, 'unlink', side_effect=OSError('unlink denied')):
            with self.assertRaisesRegex(RuntimeError, '^RECEIPT_COMMITTED_RECOVERY_REQUIRED$') as caught: self.save()
        self.assertEqual(json.loads(self.final.read_text()), self.value)
        self.assertEqual(len(list(self.root.glob('.mf-receipt-*.tmp'))), 1)
        self.assertIn('RECEIPT_STAGING_CLEANUP_REQUIRED', caught.exception.__cause__.__notes__)

    def test_error_after_successful_link_is_classified_as_committed(self):
        real_link = os.link
        def interrupted(*args, **kwargs):
            real_link(*args, **kwargs)
            raise KeyboardInterrupt('interrupt after commit')
        with patch.object(self.agent.os, 'link', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, '^RECEIPT_COMMITTED_RECOVERY_REQUIRED$'): self.save()
        self.assertEqual(json.loads(self.final.read_text()), self.value)
        self.assertEqual(list(self.root.iterdir()), [self.final])

    def test_invalid_json_does_not_create_files(self):
        self.value['bad'] = float('nan')
        with self.assertRaises(ValueError): self.save()
        self.assert_clean()


class ReceiptIntegrationTests(unittest.TestCase):
    def test_real_file_size_failure_leaves_no_partial_final_receipt(self):
        # Limit only this disposable subprocess, after synthetic child output is
        # complete. This exercises the actual agent through final receipt saving.
        code = '''import resource,signal
from unittest.mock import patch
import test_production_snapshot as fixture
case=fixture.ProductionSnapshotTests();case.setUp()
try:
 def child(argv,**kwargs):
  case.finish(argv,**kwargs)
  signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
  resource.setrlimit(resource.RLIMIT_FSIZE,(32,32))
 with patch.object(fixture.agent,'run_review_child',side_effect=child):
  try:case.run_agent()
  except OSError:pass
  else:raise AssertionError('filesystem failure accepted')
 assert not (case.output/'money-factory-receipt.json').exists(),'partial final receipt survived'
 assert not list(case.output.glob('.mf-receipt-*.tmp')),'staging file survived handled failure'
 assert (case.output/'package/manifest.json').exists()
finally:case.doCleanups()
'''
        result = subprocess.run([sys.executable, '-c', code], timeout=5,
            env=dict(os.environ, PYTHONPATH=str(Path(__file__).parent.resolve())),
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__': unittest.main()
