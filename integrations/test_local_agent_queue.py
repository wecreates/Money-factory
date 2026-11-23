"""Real process-death/SQLite tests; adapter invocations are explicitly fake."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from integrations.local_agent_queue import Queue, work
from integrations.content_control.cycle_job import brief_digest

ROOT = Path(__file__).resolve().parents[1]


def job(name='storyboard', adapter='openclaw', attempts=3):
    request = {'tool': 'openclaw', 'operation': 'run-text', 'publication_enabled': False,
               'paid_generation_enabled': False, 'model': 'local-model', 'model_url': 'http://127.0.0.1:11434',
               'prompt': 'Write three short storyboard beats.', 'timeout_seconds': 5,
               'worker_memory_mb': 512, 'shared_model_memory_mb': 1024, 'render_memory_mb': 0, 'render_cpu': 0}
    if adapter == 'ruflo':
        request = {'publication_enabled': False, 'endpoint': 'http://127.0.0.1:11434', 'model': 'local-model',
                   'workers': 1, 'max_tokens': 80, 'timeout_seconds': 5, 'worker_memory_mb': 512,
                   'shared_model_memory_mb': 1024, 'render_memory_mb': 0, 'render_cpu': 0,
                   'tasks': [{'id': 'outline', 'prompt': 'Write three short storyboard beats.'}]}
    return {'id': name, 'adapter': adapter, 'request': request, 'max_attempts': attempts,
            'publication_enabled': False, 'paid_generation_enabled': False}


@unittest.skipUnless(os.name == 'posix', 'Foreground execution uses POSIX ownership; Windows requires WSL2')
class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'queue'
        self.queue = Queue(self.root)
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            child.stderr.close()
        self.queue.close()
        self.tmp.cleanup()

    def child(self, code):
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        child = subprocess.Popen([sys.executable, '-c', code, str(self.root)], cwd=ROOT,
                                 env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.children.append(child)
        return child

    def wait_marker(self, child, marker):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (self.root / marker).exists():
                return
            if child.poll() is not None:
                self.fail(child.stderr.read().decode())
            time.sleep(.02)
        self.fail('Child did not reach crash boundary')

    def test_idempotent_enqueues_and_immutable_id(self):
        first = self.queue.enqueue(job())
        self.assertEqual(self.queue.enqueue(job())['digest'], first['digest'])
        changed = job(); changed['request']['prompt'] = 'Different task'
        with self.assertRaises(ValueError):
            self.queue.enqueue(changed)
        self.assertEqual(self.queue.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)

    def test_batch_cli_enqueues_in_manifest_order_and_replay_preserves_history(self):
        path = Path(self.tmp.name) / 'batch.json'
        path.write_text(json.dumps([job('z-first'), job('a-second')]))
        command = [sys.executable, '-m', 'integrations.local_agent_queue', '--queue',
                   str(self.root), 'enqueue-batch', str(path)]
        first = json.loads(subprocess.check_output(command, cwd=ROOT, text=True))
        self.assertEqual([row['id'] for row in first], ['z-first', 'a-second'])
        claimed_id = min(first, key=lambda row: (row['created'], row['id']))['id']
        report = work(self.queue, executor=lambda _: {'status': 'PASS'})
        self.assertEqual([row['id'] for row in report['processed']], [claimed_id])
        replay = json.loads(subprocess.check_output(command, cwd=ROOT, text=True))
        self.assertEqual([row['digest'] for row in replay], [row['digest'] for row in first])
        for row in replay:
            self.assertEqual(row['state'], 'succeeded' if row['id'] == claimed_id else 'queued')
            self.assertNotIn('receipts', row)
        self.assertEqual(len(self.queue.get(claimed_id)['receipts']), 1)

    def test_batch_rejects_conflicts_and_rolls_back_new_inserts(self):
        self.queue.enqueue(job())
        changed = job(attempts=1)
        with self.assertRaisesRegex(ValueError, 'different immutable payload'):
            self.queue.enqueue_batch([job('new'), changed])
        for specs in ([], [job('duplicate'), job('duplicate')], [job(str(i)) for i in range(17)]):
            with self.assertRaises(ValueError):
                self.queue.enqueue_batch(specs)
        self.assertEqual(self.queue.db.execute('SELECT id FROM jobs').fetchall()[0]['id'], 'storyboard')
        self.assertEqual(self.queue.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)

    def test_new_cycle_visual_preflight_rolls_back_batch(self):
        brief = json.loads((ROOT / 'integrations/content_control/examples/rewards-card-brief.json').read_text())
        invalid = job('unsupported-visual', adapter='content-control-cycle')
        invalid['request'] = {'operation': 'produce-content-cycle', 'brief': brief,
                              'brief_sha256': brief_digest(brief), 'timeout_seconds': 300,
                              'publication_enabled': False, 'paid_generation_enabled': False}
        with self.assertRaisesRegex(ValueError, 'balance'):
            self.queue.enqueue_batch([job('valid'), invalid])
        self.assertEqual(self.queue.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0)

    def test_success_survives_restart_and_never_runs_twice(self):
        self.queue.enqueue(job())
        work(self.queue, executor=lambda _: {'status': 'PASS', 'text': 'fixture only'})
        other = Queue(self.root)
        try:
            report = work(other, executor=lambda _: self.fail('Completed job replayed'))
            self.assertEqual(report['processed'], [])
            receipt = other.get('storyboard')['receipts'][0]['receipt']
            self.assertEqual(receipt['text'], 'fixture only')
        finally:
            other.close()

    def test_retry_bound_and_receipt_history(self):
        self.queue.enqueue(job(attempts=2))
        work(self.queue, executor=lambda _: {'status': 'BLOCKED', 'reason': 'fixture capacity unknown'})
        self.queue.retry('storyboard')
        work(self.queue, executor=lambda _: {'status': 'FAIL', 'reason': 'fixture failed'})
        with self.assertRaises(ValueError):
            self.queue.retry('storyboard')
        result = self.queue.get('storyboard')
        self.assertEqual([r['state'] for r in result['receipts']], ['blocked', 'failed'])
        self.assertEqual(result['attempts'], 2)

    def test_retry_does_not_reset_running_or_successful_job(self):
        self.queue.enqueue(job())
        with self.queue.consumer():
            attempt = self.queue.claim()
            with self.assertRaises(ValueError):
                self.queue.retry('storyboard')
            self.queue.finish(attempt, {'status': 'PASS'})
        with self.assertRaises(ValueError):
            self.queue.retry('storyboard')

    def test_process_kill_recovery_does_not_replay_unknown_work(self):
        self.queue.enqueue(job())
        child = self.child('''
import sys,time
from pathlib import Path
from integrations.local_agent_queue import Queue,work
q=Queue(sys.argv[1])
def execute(attempt):
    d=q.root/'attempts'/attempt['id']/str(attempt['number']);d.mkdir(parents=True)
    (d/'raw.json').write_text('{"fixture":"possibly finished"}')
    (q.root/'running').write_text('ready')
    time.sleep(60)
work(q,executor=execute)
''')
        self.wait_marker(child, 'running')
        child.kill(); child.wait(timeout=5)
        report = work(self.queue, executor=lambda _: self.fail('Interrupted inference automatically replayed'))
        self.assertEqual(report['recovered_interrupted_ids'], ['storyboard'])
        result = self.queue.get('storyboard')
        self.assertEqual(result['state'], 'interrupted')
        self.assertEqual(result['receipts'][0]['receipt']['status'], 'INTERRUPTED')
        self.assertTrue((self.root/'attempts/storyboard/1/raw.json').exists())
        self.queue.retry('storyboard')
        work(self.queue, executor=lambda _: {'status': 'PASS', 'text': 'second explicit attempt'})
        self.assertEqual(self.queue.get('storyboard')['attempts'], 2)
        self.assertEqual(self.queue.get('storyboard')['receipts'][0]['state'], 'interrupted')

    def test_live_consumer_cannot_be_recovered_or_double_claimed(self):
        self.queue.enqueue(job())
        child = self.child('''
import sys,time
from integrations.local_agent_queue import Queue
q=Queue(sys.argv[1])
with q.consumer():
    q.claim()
    (q.root/'locked').write_text('ready')
    time.sleep(60)
''')
        self.wait_marker(child, 'locked')
        with self.assertRaisesRegex(RuntimeError, 'Another foreground consumer'):
            work(self.queue, executor=lambda _: self.fail('Double dispatch'))
        self.assertEqual(self.queue.get('storyboard')['state'], 'running')

    def test_death_after_durable_receipt_does_not_replay(self):
        self.queue.enqueue(job())
        child = self.child('''
import sys,time
from integrations.local_agent_queue import Queue
q=Queue(sys.argv[1])
with q.consumer():
    a=q.claim();q.finish(a,{'status':'PASS','text':'durable fixture'})
    (q.root/'committed').write_text('ready')
    time.sleep(60)
''')
        self.wait_marker(child, 'committed')
        child.kill(); child.wait(timeout=5)
        self.assertEqual(work(self.queue, executor=lambda _: self.fail('Receipt replay'))['processed'], [])
        self.assertEqual(self.queue.get('storyboard')['state'], 'succeeded')

    def test_partial_transaction_rolls_back_after_process_death(self):
        self.queue.enqueue(job())
        child = self.child('''
import sys,time
from integrations.local_agent_queue import Queue
q=Queue(sys.argv[1]);q.db.execute('BEGIN IMMEDIATE')
q.db.execute("UPDATE jobs SET state='running',attempts=1")
(q.root/'uncommitted').write_text('ready')
time.sleep(60)
''')
        self.wait_marker(child, 'uncommitted')
        child.kill(); child.wait(timeout=5)
        self.assertEqual(self.queue.get('storyboard')['state'], 'queued')
        self.assertEqual(self.queue.get('storyboard')['attempts'], 0)
        work(self.queue, executor=lambda _: {'status': 'PASS'})
        self.assertEqual(self.queue.get('storyboard')['attempts'], 1)

    def test_exception_stays_failed_and_redacts_exception_text(self):
        self.queue.enqueue(job())
        def fail(_):
            raise RuntimeError('sensitive exception text')
        work(self.queue, executor=fail)
        result = self.queue.get('storyboard')
        self.assertEqual(result['state'], 'failed')
        self.assertNotIn('sensitive', json.dumps(result))

    def test_shutdown_interrupt_is_recovered_not_claimed_as_failure(self):
        self.queue.enqueue(job())
        def stop(_):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            work(self.queue, executor=stop)
        self.assertEqual(self.queue.get('storyboard')['state'], 'running')
        work(self.queue, executor=lambda _: self.fail('No automatic retry'))
        self.assertEqual(self.queue.get('storyboard')['state'], 'interrupted')

    def test_adapter_boundary_preserves_existing_dispatch(self):
        self.queue.enqueue(job())
        with patch('integrations.openclaw.worker.dispatch', return_value={'status': 'BLOCKED'}) as dispatch:
            work(self.queue)
        request, runtime = dispatch.call_args.args
        self.assertEqual(Path(request['output']), self.root/'attempts/storyboard/1/adapter-receipt.json')
        self.assertIs(request['publication_enabled'], False)
        self.assertIs(request['paid_generation_enabled'], False)
        self.assertEqual(self.queue.get('storyboard')['state'], 'blocked')

    def test_ruflo_uses_existing_guarded_run_batch(self):
        self.queue.enqueue(job(adapter='ruflo'))
        with patch('integrations.ruflo.local_batch.run_batch', return_value={'status': 'BLOCKED'}) as run:
            work(self.queue, ruflo_runtime='/operator/pinned/runtime')
        self.assertEqual(run.call_args.args[1], '/operator/pinned/runtime')
        self.assertEqual(run.call_args.args[0]['workers'], 1)

    def test_validation_rejects_escape_paid_remote_and_unknown_options(self):
        variants = []
        for field, value in [('id', '../escape'), ('max_attempts', 4), ('publication_enabled', True), ('paid_generation_enabled', True), ('adapter', 'shell')]:
            spec = job(); spec[field] = value; variants.append(spec)
        for field, value in [('output', '/tmp/arbitrary'), ('model_url', 'https://example.com'), ('operation', 'doctor'), ('command', 'whoami')]:
            spec = job(); spec['request'][field] = value; variants.append(spec)
        for spec in variants:
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    self.queue.enqueue(spec)

    def test_contradictory_adapter_receipt_is_failed_closed(self):
        self.queue.enqueue(job())
        work(self.queue, executor=lambda _: {'status': 'PASS', 'publication_enabled': True})
        self.assertEqual(self.queue.get('storyboard')['state'], 'failed')
        self.assertIs(self.queue.get('storyboard')['receipts'][0]['receipt']['publication_enabled'], False)

    def test_rejects_unknown_ruflo_task_fields(self):
        spec = job(adapter='ruflo')
        spec['request']['tasks'][0]['command'] = 'not permitted'
        with self.assertRaises(ValueError):
            self.queue.enqueue(spec)

    def test_recovery_and_claim_require_consumer_ownership(self):
        with self.assertRaises(RuntimeError): self.queue.recover()
        with self.assertRaises(RuntimeError): self.queue.claim()


if __name__ == '__main__':
    unittest.main()
