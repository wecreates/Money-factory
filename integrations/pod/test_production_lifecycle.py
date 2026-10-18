"""Actual MF -> pinned Node supervisor -> fixture Python lifecycle tests."""
import json
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch


FIXTURE = '''#!/usr/bin/env python3
import os,signal,subprocess,sys,time
from pathlib import Path
p=Path(os.environ['POD_TEST_ROOT'])
(p/'node').write_text(str(os.getppid()))
(p/'snapshot').write_text(sys.argv[sys.argv.index('--input')+1])
if os.environ['POD_TEST_MODE']=='tree':
 child=subprocess.Popen([sys.executable,'-c',"import os,signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path(os.environ['POD_TEST_ROOT'],'descendant').write_text(str(os.getpid()));time.sleep(30)"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 while not (p/'descendant').exists():time.sleep(.01)
def stop(sig,frame):
 (p/'terminated').write_text(str(sig));sys.exit(0)
signal.signal(signal.SIGTERM,stop)
(p/'ready').write_text(str(os.getpid()))
time.sleep(30)
'''


def stopped(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].strip().startswith('Z')
    except FileNotFoundError:
        return False  # A missing proc mount is not evidence of process exit.


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('lifecycle_agent', Path(__file__).with_name('production_agent.py'))
        self.agent = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.agent)

    def test_spawn_failure_restores_signal_handlers(self):
        before = {sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
        with self.assertRaises(FileNotFoundError):
            self.agent.run_review_child(['/missing-pod-fixture-executable'])
        self.assertEqual(before, {sig:signal.getsignal(sig) for sig in before})

    def test_nonmain_thread_fails_before_spawn(self):
        errors = []
        def run():
            try: self.agent.run_review_child(['unused'])
            except RuntimeError as e: errors.append(str(e))
        with patch.object(self.agent.subprocess, 'Popen') as spawn:
            thread = threading.Thread(target=run); thread.start(); thread.join(timeout=2)
            self.assertFalse(thread.is_alive()); spawn.assert_not_called()
        self.assertEqual(errors, ['REVIEW_MAIN_THREAD_REQUIRED'])

    def test_timeout_reaps_uncooperative_direct_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp)/'pid'
            code = "import os,signal,sys,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(30)"
            with patch.object(self.agent, 'REVIEW_STOP_SECONDS', .1):
                with self.assertRaises(subprocess.TimeoutExpired):
                    self.agent.run_review_child([sys.executable, '-c', code, str(marker)], timeout=.5)
            self.assertTrue(stopped(int(marker.read_text())))


@unittest.skipUnless(os.environ.get('CONTENT_CONTROL_ROOT'), 'Content Control checkout required')
class ProductionLifecycleTests(unittest.TestCase):
    def exercise(self, sig=None, mode='wait', timeout=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root/'fixture-python'; exe.write_text(FIXTURE); exe.chmod(0o755)
            job = root/'job.json'
            job.write_text(json.dumps(dict(platform='kdp', publication_enabled=False, paid_generation_enabled=False)))
            font = root/'font'; font.write_bytes(b'fixture')
            agent = Path(__file__).with_name('production_agent.py').resolve()
            code = '''import importlib.util,signal,sys
s=importlib.util.spec_from_file_location('agent',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m.REVIEW_TIMEOUT_SECONDS=1
before={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
try:m.run(*sys.argv[2:])
except BaseException as e:
 assert all(signal.getsignal(sig)==handler for sig,handler in before.items())
 print(type(e).__name__,flush=True)
else:raise AssertionError('cancelled review succeeded')
'''
            env = dict(os.environ, POD_PYTHON=str(exe), POD_TEST_ROOT=tmp, POD_TEST_MODE=mode)
            proc = subprocess.Popen([sys.executable, '-c', code, str(agent), str(job),
                env['CONTENT_CONTROL_ROOT'], str(font), str(root/'out')], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            pids = []
            try:
                end = time.monotonic()+5
                while not (root/'ready').exists() and time.monotonic()<end:
                    time.sleep(.01)
                self.assertTrue((root/'ready').exists(), 'fixture failed to start')
                for name in ('ready', 'node', 'descendant'):
                    if (root/name).exists(): pids.append(int((root/name).read_text()))
                if sig is not None: proc.send_signal(sig)
                stdout, stderr = proc.communicate(timeout=9)
                self.assertEqual(proc.returncode, 0, stderr)
                self.assertIn('TimeoutExpired' if timeout else 'InterruptedError', stdout)
                self.assertEqual((root/'terminated').read_text(), '15')
                for pid in pids:
                    end = time.monotonic()+1
                    while not stopped(pid) and time.monotonic()<end: time.sleep(.01)
                    self.assertTrue(stopped(pid), f'fixture process {pid} remains running')
                self.assertFalse(Path((root/'snapshot').read_text()).parent.exists())
                self.assertFalse((root/'out/money-factory-receipt.json').exists())
                self.assertTrue(job.exists())
            finally:
                if proc.poll() is None: proc.kill()
                for name in ('ready', 'descendant', 'node'):
                    if (root/name).exists():
                        try: os.kill(int((root/name).read_text()), signal.SIGKILL)
                        except ProcessLookupError: pass
                proc.communicate(timeout=3)

    def test_sigterm_forwarded_even_when_python_exits_zero(self):
        self.exercise(signal.SIGTERM)

    def test_sigint_forwarded_even_when_python_exits_zero(self):
        self.exercise(signal.SIGINT)

    def test_cancellation_waits_for_stubborn_descendant_cleanup(self):
        self.exercise(signal.SIGTERM, mode='tree')

    def test_timeout_uses_cooperative_supervisor_cleanup(self):
        self.exercise(timeout=True)


if __name__ == '__main__': unittest.main()
