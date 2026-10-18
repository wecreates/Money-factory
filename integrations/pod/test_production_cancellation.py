"""Cancellation boundaries use real signals; fixture packages are not approval."""
import json
import os
from pathlib import Path
import signal
import stat
import sys
import threading
import unittest
from unittest.mock import patch
import test_production_snapshot as fixture


class ReviewCancellationTests(unittest.TestCase):
    def exercise(self, phase, committed=False):
        for sig in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(phase=phase, signal=sig):
                case = fixture.ProductionSnapshotTests(); case.setUp()
                agent = fixture.agent
                before = {s:signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
                prior_calls = []
                prior = lambda signum, frame: prior_calls.append(signum)
                for s in before: signal.signal(s, prior)
                fired = False
                def cancel():
                    nonlocal fired
                    if not fired:
                        fired = True
                        signal.raise_signal(sig)
                real_json, real_chunks, real_sync = agent.output_json, agent.output_chunks, os.fsync
                snapshot = []
                def child(argv, **kwargs):
                    snapshot.append(Path(argv[2]))
                    case.finish(argv, **kwargs)
                    if phase == 'child': cancel()
                def read_json(path, **kwargs):
                    value = real_json(path, **kwargs)
                    if phase == 'json': cancel()
                    return value
                def chunks(path, limit, **kwargs):
                    for chunk in real_chunks(path, limit, **kwargs):
                        if phase == 'artifact' and Path(path).name == 'art.bin': cancel()
                        yield chunk
                def sync(fd):
                    real_sync(fd)
                    directory = stat.S_ISDIR(os.fstat(fd).st_mode)
                    if phase == ('directory_sync' if directory else 'file_sync'): cancel()
                try:
                    expected = RuntimeError if committed else InterruptedError
                    message = '^RECEIPT_COMMITTED_RECOVERY_REQUIRED$' if committed else '^REVIEW_CANCELLED$'
                    with patch.object(agent, 'run_review_child', side_effect=child), \
                         patch.object(agent, 'output_json', side_effect=read_json), \
                         patch.object(agent, 'output_chunks', side_effect=chunks), \
                         patch.object(agent.os, 'fsync', side_effect=sync):
                        with self.assertRaisesRegex(expected, message): case.run_agent()
                    self.assertTrue(fired)
                    self.assertEqual(prior_calls, [])
                    self.assertTrue(all(signal.getsignal(s) is prior for s in before))
                    self.assertFalse(snapshot[0].parent.exists())
                    final = case.output/'money-factory-receipt.json'
                    self.assertEqual(final.exists(), committed)
                    self.assertFalse(list(case.output.glob('.mf-receipt-*.tmp')))
                    if committed:
                        self.assertEqual(json.loads(final.read_text())['status'], 'REVIEW_REQUIRED')
                    self.assertTrue((case.output/'package/manifest.json').exists())
                    self.assertEqual(case.job.read_bytes(), case.body)
                finally:
                    for s, handler in before.items(): signal.signal(s, handler)
                    case.doCleanups()

    def test_cancel_after_child_exit_never_receipts(self): self.exercise('child')
    def test_cancel_during_result_validation_never_receipts(self): self.exercise('json')
    def test_cancel_during_artifact_hashing_never_receipts(self): self.exercise('artifact')
    def test_cancel_during_receipt_file_sync_never_commits(self): self.exercise('file_sync')
    def test_cancel_after_commit_preserves_receipt_and_requires_recovery(self): self.exercise('directory_sync', True)

    def test_run_restores_handlers_on_validation_failure(self):
        case = fixture.ProductionSnapshotTests(); case.setUp()
        before = {s:signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        try:
            case.job.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'REVIEW_ONLY_REQUIRED'): case.run_agent()
            self.assertEqual(before, {s:signal.getsignal(s) for s in before})
        finally: case.doCleanups()

    def test_run_nonmain_thread_rejected_before_read_or_spawn(self):
        errors = []
        def run():
            try: fixture.agent.run('/missing-job', '/missing-root', '/missing-font', '/missing-output')
            except BaseException as error: errors.append(str(error))
        with patch.object(fixture.agent.subprocess, 'Popen') as spawn:
            thread = threading.Thread(target=run); thread.start(); thread.join(timeout=2)
            self.assertFalse(thread.is_alive()); spawn.assert_not_called()
        self.assertEqual(errors, ['REVIEW_MAIN_THREAD_REQUIRED'])

    def test_child_cancel_during_handler_restoration_cannot_return_success(self):
        agent = fixture.agent
        before = {s:signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        real_signal = signal.signal
        fired = False
        def restore(sig, handler):
            nonlocal fired
            if sig == signal.SIGTERM and handler == before[sig] and not fired:
                fired = True
                signal.raise_signal(signal.SIGTERM)
            return real_signal(sig, handler)
        try:
            with patch.object(agent.signal, 'signal', side_effect=restore):
                with self.assertRaisesRegex(InterruptedError, '^REVIEW_CANCELLED$'):
                    agent.run_review_child([sys.executable, '-c', 'pass'])
            self.assertTrue(fired)
            self.assertEqual(before, {s:signal.getsignal(s) for s in before})
        finally:
            for sig, handler in before.items(): real_signal(sig, handler)

    def test_cancel_before_child_spawn_restores_handlers_and_skips_work(self):
        case = fixture.ProductionSnapshotTests(); case.setUp()
        agent = fixture.agent
        before = {s:signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        real_capture = agent.capture_job
        def capture(path):
            body = real_capture(path)
            signal.raise_signal(signal.SIGINT)
            return body
        try:
            with patch.object(agent, 'capture_job', side_effect=capture), \
                 patch.object(agent, 'run_review_child') as child:
                with self.assertRaisesRegex(InterruptedError, '^REVIEW_CANCELLED$'): case.run_agent()
                child.assert_not_called()
            self.assertFalse(case.output.exists())
            self.assertEqual(before, {s:signal.getsignal(s) for s in before})
        finally: case.doCleanups()

    def test_cancel_during_final_handler_restoration_retains_committed_receipt(self):
        case = fixture.ProductionSnapshotTests(); case.setUp()
        agent = fixture.agent
        before = {s:signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        real_signal = signal.signal
        fired = False
        def restore(sig, handler):
            nonlocal fired
            if sig == signal.SIGINT and handler == before[sig] and not fired:
                fired = True
                signal.raise_signal(signal.SIGINT)
            return real_signal(sig, handler)
        try:
            with patch.object(agent, 'run_review_child', side_effect=case.finish), \
                 patch.object(agent.signal, 'signal', side_effect=restore):
                with self.assertRaisesRegex(RuntimeError, '^RECEIPT_COMMITTED_RECOVERY_REQUIRED$'):
                    case.run_agent()
            self.assertTrue(fired)
            self.assertEqual(json.loads((case.output/'money-factory-receipt.json').read_text())['status'], 'REVIEW_REQUIRED')
            self.assertEqual(before, {s:signal.getsignal(s) for s in before})
        finally:
            for sig, handler in before.items(): real_signal(sig, handler)
            case.doCleanups()


if __name__ == '__main__': unittest.main()
