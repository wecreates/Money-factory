"""Real process ownership tests; media bytes and approvals here are synthetic."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from integrations.agent_capacity import _admission_lock_at, AdmissionBusy
from integrations.content_control.video_job import validate, digest, check_completed, run_job, producer_module, guarded_runner

ROOT = Path(__file__).resolve().parents[2]


def wait_until(test, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if test(): return True
        time.sleep(.02)
    return test()


def alive(pid):
    try: return Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1][0] != 'Z'
    except (FileNotFoundError, ProcessLookupError): return False


class VideoJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request = {'operation': 'produce-episode1-review', 'source_commit': 'a'*40,
                        'source_manifest_sha256': 'b'*64, 'timeout_seconds': 900,
                        'publication_enabled': False, 'paid_generation_enabled': False}

    def test_only_fixed_source_bound_operation_and_bounded_deadline_are_accepted(self):
        validate(self.request)
        for patch in ({'command': 'anything'}, {'output': '/tmp/overwrite'},
                      {'content_control_root': '/tmp/other'}, {'publication_enabled': True},
                      {'paid_generation_enabled': 0}, {'source_commit': 'main'},
                      {'source_manifest_sha256': 'z'*64}, {'timeout_seconds': True},
                      {'timeout_seconds': 1801}, {'operation': 'publish'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate(dict(self.request, **patch))

    def test_missing_operator_runtime_blocks_and_never_overwrites_attempt_receipt(self):
        result = run_job(self.request, self.root)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertFalse(result['production_ready'])
        before = (self.root / 'video-adapter-receipt.json').read_bytes()
        with self.assertRaises(FileExistsError): run_job(self.request, self.root)
        self.assertEqual(before, (self.root / 'video-adapter-receipt.json').read_bytes())

    def test_queue_interpreter_must_support_receipt_hashing_before_render(self):
        with patch.object(sys, 'version_info', (3, 10)):
            result = run_job(self.request, self.root)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('Python 3.11', result['blocker'])

    def test_only_pre_execution_admission_contention_is_retryable(self):
        source = self.root / 'source'; (source / 'scripts').mkdir(parents=True)
        with patch('integrations.content_control.video_job.shared_admission_lock',
                   side_effect=AdmissionBusy('busy')):
            result = run_job(self.request, self.root,
                             content_control_root=source,
                             video_python=sys.executable,
                             picture_python=sys.executable)
        self.assertTrue(result['retryable'])
        self.assertEqual(result['blocker'], 'AdmissionBusy')

        other = self.root / 'other'; other.mkdir()
        blocked = run_job(self.request, other)
        self.assertNotIn('retryable', blocked)

    def packet(self):
        for name in ('video.mp4', 'captions.vtt', 'encoded-verification.json', 'audio-verification.json'):
            (self.root / name).write_text('synthetic '+name)
        source = {'source_files': {'fixture': 'a'*64}}
        record = {'status': 'AWAITING_REVIEW', 'technical_status': 'PASS',
                  'publication_enabled': False, 'production_approved': False, 'full_av_review': False,
                  'source_inputs_unchanged': True, 'renderer_scratch_cleaned': True,
                  'source_sha256': source['source_files'], 'candidate_sha256': digest(self.root / 'video.mp4'),
                  'artifacts_sha256': {p.name: digest(p) for p in self.root.iterdir()}}
        (self.root / 'run.json').write_text(json.dumps(record))
        return record, source

    def test_changed_artifact_or_forged_approval_cannot_complete(self):
        record, source = self.packet()
        self.assertEqual(check_completed(self.root, source)['status'], 'AWAITING_REVIEW')
        for field in ('publication_enabled', 'production_approved', 'full_av_review'):
            (self.root / 'run.json').write_text(json.dumps(dict(record, **{field: True})))
            with self.assertRaises(ValueError): check_completed(self.root, source)
        (self.root / 'run.json').write_text(json.dumps(record))
        (self.root / 'video.mp4').write_text('changed after completion')
        with self.assertRaises(ValueError): check_completed(self.root, source)

    def test_loading_new_pinned_source_does_not_reuse_helpers_or_dirty_checkout(self):
        before = sys.dont_write_bytecode
        foreign = self.root / 'foreign'
        (foreign / 'scripts').mkdir(parents=True)
        (foreign / 'scripts/__init__.py').write_text('raise AssertionError("unverified package imported")')
        original_path = list(sys.path)
        self.addCleanup(lambda: setattr(sys, 'path', original_path))
        sys.path.append(str(foreign))
        for value in ('first', 'second'):
            root = self.root / value
            (root / 'scripts').mkdir(parents=True)
            (root / 'scripts/helper.py').write_text('VALUE=' + repr(value))
            (root / 'scripts/produce_episode1_review.py').write_text(
                'from scripts.helper import VALUE\ndef produce(*,command_runner=None):return VALUE\n')
            with producer_module(root) as module:
                self.assertEqual(module.produce(), value)
            self.assertFalse((root / 'scripts/__pycache__').exists())
        self.assertEqual(sys.dont_write_bytecode, before)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux/WSL stage execution')
    def test_stage_drops_credentials_and_runtime_hooks(self):
        log = self.root / 'environment.log'
        code = 'import os,json;print(json.dumps({k:os.getenv(k) for k in ["OPENAI_API_KEY","PYTHONPATH","NODE_OPTIONS","PUBLICATION_ENABLED","HF_HUB_OFFLINE","CYZOR_ASR_HF_HOME"]}))'
        env = dict(os.environ, OPENAI_API_KEY='fixture-secret', PYTHONPATH='/fixture',
                   NODE_OPTIONS='--fixture', CYZOR_ASR_HF_HOME='/trusted/asr-cache')
        with _admission_lock_at(self.root / 'lease') as lease:
            guarded_runner(lease, sorted(os.sched_getaffinity(0))[:2])(
                [sys.executable, '-c', code], cwd=self.root, log=log, deadline=time.monotonic()+5, env=env)
        result = json.loads(log.read_text())
        for field in ('OPENAI_API_KEY', 'PYTHONPATH', 'NODE_OPTIONS'): self.assertIsNone(result[field])
        self.assertEqual(result['PUBLICATION_ENABLED'], 'false')
        self.assertEqual(result['HF_HUB_OFFLINE'], '1')
        self.assertEqual(result['CYZOR_ASR_HF_HOME'], '/trusted/asr-cache')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux/WSL ownership regression')
    def test_stage_guardian_keeps_lease_after_consumer_death_until_nested_children_exit(self):
        worker = self.root / 'stage.py'
        worker.write_text('''import os,sys,time,json,subprocess
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid]))
time.sleep(60)
''')
        code = '''import os,sys,time
from contextlib import contextmanager
from pathlib import Path
from integrations.agent_capacity import _admission_lock_at
from integrations.content_control import video_job
r=Path(sys.argv[1])
original=video_job.owned_process
@contextmanager
def observed(*args,**kwargs):
    with original(*args,**kwargs) as process:
        (r/'guardian').write_text(str(process.pid))
        yield process
video_job.owned_process=observed
with _admission_lock_at(r/'lease') as lease:
    video_job.guarded_runner(lease,sorted(os.sched_getaffinity(0))[:2])(
        [sys.executable,str(r/'stage.py'),str(r/'pids')],cwd=r,
        log=r/'stage.log',deadline=time.monotonic()+60,env=os.environ.copy())
'''
        parent = subprocess.Popen([sys.executable, '-c', code, str(self.root)], cwd=ROOT)
        guardian = None; pids = []
        try:
            def ready():
                nonlocal guardian, pids
                try:
                    pids = json.loads((self.root / 'pids').read_text())
                    guardian = int((self.root / 'guardian').read_text())
                    return len(pids) == 2
                except (OSError, ValueError, IndexError): return False
            self.assertTrue(wait_until(ready), 'Nested stage did not start')
            expected_cpus = set(sorted(os.sched_getaffinity(0))[:2])
            self.assertEqual(os.sched_getaffinity(pids[0]), expected_cpus)
            self.assertEqual(os.sched_getaffinity(pids[1]), expected_cpus)
            os.kill(guardian, signal.SIGSTOP)
            parent.kill(); parent.wait(timeout=5)
            self.assertTrue(all(alive(pid) for pid in pids))
            with self.assertRaises(AdmissionBusy):
                with _admission_lock_at(self.root / 'lease'): pass
            os.kill(guardian, signal.SIGCONT)
            self.assertTrue(wait_until(lambda: all(not alive(pid) for pid in pids)))
            def released():
                try:
                    with _admission_lock_at(self.root / 'lease'): return True
                except AdmissionBusy: return False
            self.assertTrue(wait_until(released))
        finally:
            if guardian:
                try: os.kill(guardian, signal.SIGCONT)
                except ProcessLookupError: pass
            if parent.poll() is None: parent.kill(); parent.wait(timeout=5)
            for pid in pids:
                if alive(pid):
                    try: os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError: pass


if __name__ == '__main__': unittest.main()
