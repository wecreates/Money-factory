"""Foreground operator behavior with real consumer processes and SQLite locks."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from integrations.local_agent_queue import Queue, work
from integrations.test_local_agent_queue import job

ROOT = Path(__file__).resolve().parents[1]


def eventually(check, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(.02)
    return check()


@unittest.skipUnless(os.name == 'posix', 'Foreground worker requires POSIX/WSL')
class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'queue'
        self.queue = Queue(self.root)
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        self.queue.close()
        self.temp.cleanup()

    def child(self, code):
        child = subprocess.Popen([sys.executable, '-c', code, str(self.root)], cwd=ROOT,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.children.append(child)
        return child

    def test_active_heartbeat_and_stop_finishes_only_current_job(self):
        self.queue.enqueue(job('first'))
        self.queue.enqueue(job('second'))
        child = self.child('''
import sys,time,json
from integrations.local_agent_queue import Queue,work
q=Queue(sys.argv[1])
def execute(a):
    (q.root/'started').write_text(a['id'])
    while not (q.root/'release').exists(): time.sleep(.02)
    return {'status':'PASS','fixture_only':True}
r=work(q,max_jobs=10,watch_seconds=20,poll_seconds=.2,executor=execute)
print(json.dumps(r))
''')
        self.assertTrue(eventually(lambda: (self.root/'started').exists()))
        first = self.queue.health()
        run_id = first['run']['id']
        self.assertEqual(first['run']['active_job'], 'first')
        self.assertTrue(first['consumer_lock_held'])
        self.assertTrue(eventually(lambda: self.queue.health()['run']['heartbeat'] > first['run']['heartbeat']))
        self.assertEqual(self.queue.request_stop(run_id)['status'], 'STOP_REQUESTED')
        self.assertIsNone(child.poll(), 'Stop must finish, not kill, the active bounded job')
        self.assertEqual(self.queue.get('second')['state'], 'queued')
        (self.root/'release').write_text('ready')
        output, error = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, error)
        result = json.loads(output)
        self.assertEqual(result['worker']['exit_reason'], 'stop_requested')
        self.assertEqual(result['worker']['processed'], 1)
        self.assertEqual(self.queue.get('first')['state'], 'succeeded')
        self.assertEqual(self.queue.get('second')['state'], 'queued')
        later = work(self.queue, executor=lambda _: {'status':'PASS'})
        self.assertNotEqual(later['worker']['id'], run_id)
        self.assertEqual(self.queue.get('second')['state'], 'succeeded')
        self.assertNotIn('receipts', later['processed'][0], 'Loop result stays small; full receipts remain in SQLite')

    def test_idle_stop_via_real_cli_is_targeted_and_persisted(self):
        child = self.child('''
import sys,json
from integrations.local_agent_queue import Queue,work
q=Queue(sys.argv[1]);print(json.dumps(work(q,watch_seconds=20,poll_seconds=.2)))
''')
        self.assertTrue(eventually(lambda: self.queue.health()['run'] is not None))
        run_id = self.queue.health()['run']['id']
        stale = self.queue.request_stop('old-run')
        self.assertEqual(stale['status'], 'NO_ACTIVE_MATCH')
        command = [sys.executable, '-m', 'integrations.local_agent_queue', '--queue', str(self.root), 'stop', '--run-id', run_id]
        response = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertFalse(json.loads(response.stdout)['stopped'])
        output, error = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, error)
        self.assertEqual(json.loads(output)['worker']['exit_reason'], 'stop_requested')
        health = self.queue.health()
        self.assertFalse(health['consumer_lock_held'])
        self.assertEqual(health['run']['state'], 'finished')

    def test_crashed_health_never_reports_running_without_consumer_lock(self):
        child = self.child('''
import sys
from integrations.local_agent_queue import Queue,work
work(Queue(sys.argv[1]),watch_seconds=20,poll_seconds=.2)
''')
        self.assertTrue(eventually(lambda: self.queue.health()['run'] is not None))
        run_id = self.queue.health()['run']['id']
        child.kill(); child.communicate(timeout=5)
        self.assertEqual(self.queue.health()['run']['observed_state'], 'interrupted_unrecovered')
        self.assertFalse(self.queue.health()['consumer_lock_held'])
        work(self.queue)
        self.assertEqual(self.queue.health(run_id)['run']['state'], 'interrupted')

    def test_watch_deadline_and_poll_bounds(self):
        report = work(self.queue, watch_seconds=1, poll_seconds=.2)
        self.assertEqual(report['worker']['exit_reason'], 'watch_deadline')
        for value in (0, .1, 61, float('nan'), float('inf'), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                work(self.queue, poll_seconds=value)

    def test_deadline_rechecked_after_sqlite_writer_contention(self):
        self.queue.enqueue(job())
        ready = threading.Event()
        release = threading.Event()
        def writer():
            db = sqlite3.connect(self.root/'queue.sqlite3', isolation_level=None)
            db.execute('BEGIN IMMEDIATE'); ready.set()
            release.wait(timeout=3)
            db.execute('COMMIT'); db.close()
        with self.queue.consumer():
            run_id = self.queue.start_run({'poll_seconds':.2})
            thread = threading.Thread(target=writer)
            thread.start(); self.assertTrue(ready.wait(timeout=2))
            timer = threading.Timer(.3, release.set); timer.start()
            try:
                self.assertIsNone(self.queue.claim(run_id, time.monotonic()+.1))
            finally:
                release.set(); thread.join(timeout=3); timer.join(timeout=3)
        self.assertEqual(self.queue.get('storyboard')['state'], 'queued')
        self.assertEqual(self.queue.get('storyboard')['attempts'], 0)

    def test_stop_committed_between_loop_check_and_claim_prevents_dispatch(self):
        self.queue.enqueue(job())
        with self.queue.consumer():
            run_id = self.queue.start_run({'poll_seconds':1})
            self.assertFalse(self.queue.stop_requested(run_id))
            other = Queue(self.root)
            try:
                other.request_stop(run_id)
            finally:
                other.close()
            self.assertIsNone(self.queue.claim(run_id))
        self.assertEqual(self.queue.get('storyboard')['state'], 'queued')

    def test_video_dispatch_preserves_source_and_operator_owned_paths(self):
        spec = {'id':'video-review','adapter':'content-control-video','max_attempts':1,
                'publication_enabled':False,'paid_generation_enabled':False,
                'request':{'operation':'produce-episode1-review','source_commit':'a'*40,
                           'source_manifest_sha256':'b'*64,'timeout_seconds':30,
                           'publication_enabled':False,'paid_generation_enabled':False}}
        self.queue.enqueue(spec)
        with patch('integrations.content_control.video_job.run_job', return_value={
                'status':'PASS','review_status':'AWAITING_REVIEW','production_ready':False,
                'publication_enabled':False,'paid_generation_enabled':False,'full_av_review':False}) as run:
            work(self.queue, content_control_root='/operator/content-control',
                 video_python='/operator/asr/bin/python', picture_python='/operator/render/bin/python')
        request, directory = run.call_args.args
        self.assertEqual(request, spec['request'])
        self.assertEqual(directory, self.root/'attempts/video-review/1')
        self.assertEqual(run.call_args.kwargs['content_control_root'], '/operator/content-control')
        self.assertEqual(run.call_args.kwargs['video_python'], '/operator/asr/bin/python')
        receipt = self.queue.get('video-review')['receipts'][0]['receipt']
        self.assertFalse(receipt['production_ready'])
        self.assertFalse(receipt['full_av_review'])
        changed = json.loads(json.dumps(spec));changed['id']='bad-video'
        changed['request']['content_control_root']='/job/must/not/control/path'
        with self.assertRaises(ValueError): self.queue.enqueue(changed)

    def test_success_health_is_not_production_or_model_health(self):
        self.queue.enqueue(job())
        result = work(self.queue, executor=lambda _: {'status':'PASS'})
        self.assertEqual(result['worker']['exit_reason'], 'job_limit')
        health = self.queue.health()
        self.assertFalse(health['production_ready'])
        self.assertFalse(health['publication_enabled'])
        self.assertIn('not model', health['scope'])


if __name__ == '__main__':
    unittest.main()
