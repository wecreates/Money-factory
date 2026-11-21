"""Queue/guardian crash integration: real processes, synthetic task, no inference."""
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
from integrations.local_agent_queue import Queue, work
# Required dependency: importing fails if the guardian implementation is absent.
from integrations.owned_process import owned_process

ROOT = Path(__file__).resolve().parents[1]


def eventually(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.02)
    return predicate()


def running(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1][0] != 'Z'
    except (FileNotFoundError, ProcessLookupError):
        return False


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux/WSL process ownership regression')
class QueueGuardianRecoveryTests(unittest.TestCase):
    def test_crash_recovers_without_replay_and_retains_budget_until_cleanup(self):
        spec = {'id': 'storyboard', 'adapter': 'ruflo', 'max_attempts': 2,
                'publication_enabled': False, 'paid_generation_enabled': False,
                'request': {'publication_enabled': False, 'endpoint': 'http://127.0.0.1:11434',
                            'model': 'fixture', 'workers': 1, 'max_tokens': 80, 'timeout_seconds': 5,
                            'worker_memory_mb': 512, 'shared_model_memory_mb': 1024,
                            'render_memory_mb': 0, 'render_cpu': 0,
                            'tasks': [{'id': 'outline', 'prompt': 'Write three storyboard beats.'}]}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = Queue(root / 'queue')
            queue.enqueue(spec)
            worker = root / 'worker.py'
            worker.write_text('''import os,sys,time,json,subprocess
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid]))
time.sleep(60)
''')
            # This executor intentionally uses a fixture, never an adapter admission
            # override or model request. The separate adapter tests cover dispatch.
            code = '''import sys
from pathlib import Path
from integrations.local_agent_queue import Queue,work
from integrations.owned_process import owned_process
from integrations.agent_capacity import _admission_lock_at
root=Path(sys.argv[1]);queue=Queue(root/'queue')
def execute(attempt):
    with _admission_lock_at(root/'admission') as lease:
        with owned_process([sys.executable,str(root/'worker.py'),str(root/'pids')],timeout=60,lease_fd=lease) as process:
            (root/'guardian').write_text(str(process.pid))
            process.wait()
    return {'status':'PASS','fixture_only':True}
work(queue,executor=execute)
'''
            parent = subprocess.Popen([sys.executable, '-c', code, str(root)], cwd=ROOT)
            guardian, pids = None, []
            try:
                def ready():
                    nonlocal guardian, pids
                    try:
                        pids = json.loads((root / 'pids').read_text())
                        guardian = int((root / 'guardian').read_text())
                        return True
                    except (FileNotFoundError, ValueError):
                        return False
                self.assertTrue(eventually(ready), 'Fixture did not reach the crash boundary')
                os.kill(guardian, signal.SIGSTOP)
                parent.kill()
                parent.wait(timeout=5)
                recovered = work(queue, executor=lambda _: self.fail('Interrupted work replayed automatically'))
                self.assertEqual(recovered['recovered_interrupted_ids'], ['storyboard'])
                self.assertEqual(queue.get('storyboard')['state'], 'interrupted')
                self.assertTrue(running(pids[0]))
                with self.assertRaises(AdmissionBusy):
                    with _admission_lock_at(root / 'admission'):
                        self.fail('Consumer death released a still-running child budget')
                os.kill(guardian, signal.SIGCONT)
                self.assertTrue(eventually(lambda: all(not running(pid) for pid in pids)))
                def released():
                    try:
                        with _admission_lock_at(root / 'admission'):
                            return True
                    except AdmissionBusy:
                        return False
                self.assertTrue(eventually(released), 'Guardian retained lease after cleanup')
                queue.retry('storyboard')
                work(queue, executor=lambda _: {'status': 'PASS', 'fixture_only': True})
                result = queue.get('storyboard')
                self.assertEqual(result['attempts'], 2)
                self.assertEqual([r['state'] for r in result['receipts']], ['interrupted', 'succeeded'])
                self.assertTrue(result['receipts'][1]['receipt']['fixture_only'])
            finally:
                if guardian is not None:
                    try:
                        os.kill(guardian, signal.SIGCONT)
                    except ProcessLookupError:
                        pass
                if parent.poll() is None:
                    parent.kill()
                    parent.wait(timeout=5)
                for pid in pids:
                    if running(pid):
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                queue.close()


if __name__ == '__main__':
    unittest.main()
