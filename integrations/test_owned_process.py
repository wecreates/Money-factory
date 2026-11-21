"""Real subprocess recovery tests. Fixtures are not model inference evidence."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from integrations.agent_capacity import _admission_lock_at, AdmissionBusy
from integrations.owned_process import owned_process

ROOT = Path(__file__).resolve().parents[1]


def running(pid):
    try:
        # Zombies are no longer executing and cannot retain the admission FD.
        return Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1][0] != 'Z'
    except (FileNotFoundError, ProcessLookupError):
        return False


def eventually(predicate, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.02)
    return predicate()


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux/WSL process ownership tests')
class OwnedProcessTests(unittest.TestCase):
    def fixture(self, root, *, exit_parent=False):
        script = root / 'worker.py'
        marker = root / 'worker-pids.json'
        script.write_text(f'''#!{sys.executable}
import json, os, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
Path({str(marker)!r}).write_text(json.dumps([os.getpid(), child.pid]))
{'raise SystemExit(0)' if exit_parent else 'time.sleep(60)'}
''')
        script.chmod(0o700)
        return script, marker

    def terminate_owned(self, pids):
        for pid in pids:
            if running(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_success_preserves_output_and_exit_code(self):
        with owned_process([sys.executable, '-c', 'print("result")'], timeout=5,
                           stdout=subprocess.PIPE) as process:
            output, _ = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(output, b'result\n')

    def test_timeout_and_completed_parent_both_clean_descendant(self):
        for early_exit in (False, True):
            with self.subTest(early_exit=early_exit), tempfile.TemporaryDirectory() as tmp:
                script, marker = self.fixture(Path(tmp), exit_parent=early_exit)
                pids = []
                try:
                    with owned_process([str(script)], timeout=.5) as process:
                        self.assertTrue(eventually(marker.exists))
                        pids = json.loads(marker.read_text())
                        process.wait(timeout=5)
                        self.assertEqual(process.returncode, 0 if early_exit else 125)
                    self.assertTrue(eventually(lambda: all(not running(p) for p in pids)))
                finally:
                    self.terminate_owned(pids)

    def test_forced_parent_death_keeps_lease_until_guardian_cleans_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script, marker = self.fixture(root)
            lock, guardian_marker = root / 'admission.lock', root / 'guardian.pid'
            code = '''
import sys
from pathlib import Path
from integrations.agent_capacity import _admission_lock_at
from integrations.owned_process import owned_process
with _admission_lock_at(sys.argv[1]) as lease:
    with owned_process([sys.argv[2]], timeout=60, lease_fd=lease) as child:
        Path(sys.argv[3]).write_text(str(child.pid))
        child.wait()
'''
            parent = subprocess.Popen([sys.executable, '-c', code, str(lock), str(script), str(guardian_marker)], cwd=ROOT)
            pids, guardian = [], None
            try:
                self.assertTrue(eventually(lambda: marker.exists() and guardian_marker.exists()))
                pids = json.loads(marker.read_text())
                guardian = int(guardian_marker.read_text())
                # Freeze cleanup deliberately: a dead parent must NOT make the
                # same budget available while its worker is still running.
                os.kill(guardian, signal.SIGSTOP)
                parent.kill(); parent.wait(timeout=5)
                self.assertTrue(running(pids[0]))
                with self.assertRaises(AdmissionBusy):
                    with _admission_lock_at(lock):
                        self.fail('Lease released before guardian cleanup')
                os.kill(guardian, signal.SIGCONT)
                self.assertTrue(eventually(lambda: all(not running(p) for p in pids)))
                def released():
                    try:
                        with _admission_lock_at(lock):
                            return True
                    except AdmissionBusy:
                        return False
                self.assertTrue(eventually(released))
            finally:
                if guardian is not None:
                    try:
                        os.kill(guardian, signal.SIGCONT)
                    except ProcessLookupError:
                        pass
                if parent.poll() is None:
                    parent.kill(); parent.wait(timeout=5)
                self.terminate_owned(pids)

    def test_both_adapter_execution_paths_clean_on_parent_sigkill(self):
        for adapter in ('ruflo', 'openclaw'):
            with self.subTest(adapter=adapter), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                script, marker = self.fixture(root)
                code = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path('integrations').resolve()))
from agent_capacity import _admission_lock_at
with _admission_lock_at(sys.argv[3]) as lease:
    if sys.argv[1] == 'ruflo':
        from ruflo.local_batch import execute_task
        execute_task({'id':'fixture','prompt':'fixture'}, {'endpoint':'http://127.0.0.1:11434', 'model':'fixture', 'max_tokens':1, 'timeout_seconds':60}, Path(sys.argv[2]).parent, sys.argv[2], lease)
    else:
        from openclaw.worker import execute, environment
        root = Path(sys.argv[2]).parent
        execute([sys.argv[2]], root, environment(root), 60, lease_fd=lease)
'''
                parent = subprocess.Popen([sys.executable, '-c', code, adapter, str(script), str(root / 'lock')], cwd=ROOT)
                pids = []
                try:
                    self.assertTrue(eventually(marker.exists))
                    pids = json.loads(marker.read_text())
                    parent.kill(); parent.wait(timeout=5)
                    self.assertTrue(eventually(lambda: all(not running(p) for p in pids)))
                finally:
                    if parent.poll() is None:
                        parent.kill(); parent.wait(timeout=5)
                    self.terminate_owned(pids)

    def test_foreground_signals_stop_threads_before_releasing_lease_or_starting_more(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                script, marker = self.fixture(root)
                late, guard_marker, lock = root / 'late', root / 'guardian', root / 'lock'
                source = script.read_text().replace('child = subprocess.Popen',
                    f"job = json.load(sys.stdin)\nif job['id'] == 'late':\n    Path({str(late)!r}).touch()\n    raise SystemExit(0)\nPath({str(guard_marker)!r}).write_text(str(os.getppid()))\nchild = subprocess.Popen")
                script.write_text(source)
                code = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path('integrations').resolve()))
import agent_capacity as capacity
from ruflo import local_batch
# Fixture admission and model metadata only; real run_batch, thread pool,
# execute_task, guardian, lock and OS processes execute below.
capacity.shared_admission_lock = lambda: capacity._admission_lock_at(sys.argv[3])
capacity.collect_snapshot = lambda: {}
capacity.recommend_capacity = lambda *a, **k: {'admitted_workers': 1}
local_batch.verify_local_model = lambda job: None
batch = dict(publication_enabled=False, endpoint='http://127.0.0.1:11434',
    model='fixture', workers=1, max_tokens=1, timeout_seconds=60,
    worker_memory_mb=512, shared_model_memory_mb=0, render_memory_mb=0, render_cpu=0,
    tasks=[{'id':'first','prompt':'fixture'}, {'id':'late','prompt':'fixture'}])
local_batch.run_batch(batch, Path(sys.argv[1]).parent, node=sys.argv[1])
'''
                parent = subprocess.Popen([sys.executable, '-c', code, str(script), str(late), str(lock), str(guard_marker)],
                                          cwd=ROOT, stderr=subprocess.DEVNULL)
                pids, guardian = [], None
                try:
                    self.assertTrue(eventually(lambda: marker.exists() and guard_marker.exists()))
                    pids = json.loads(marker.read_text())
                    guardian = int(guard_marker.read_text())
                    os.kill(guardian, signal.SIGSTOP)
                    parent.send_signal(sig)
                    time.sleep(.1)
                    self.assertIsNone(parent.poll(), 'Parent must wait for guardian cleanup')
                    with self.assertRaises(AdmissionBusy):
                        with _admission_lock_at(lock):
                            self.fail('Interrupted batch released a live worker budget')
                    os.kill(guardian, signal.SIGCONT)
                    parent.wait(timeout=5)
                    self.assertNotEqual(parent.returncode, 0)
                    self.assertTrue(eventually(lambda: all(not running(p) for p in pids)))
                    self.assertFalse(late.exists(), 'Interrupted queued task executed')
                    with _admission_lock_at(lock):
                        pass
                finally:
                    if guardian is not None:
                        try:
                            os.kill(guardian, signal.SIGCONT)
                        except ProcessLookupError:
                            pass
                    if parent.poll() is None:
                        parent.kill(); parent.wait(timeout=5)
                    self.terminate_owned(pids)


if __name__ == '__main__':
    unittest.main()
