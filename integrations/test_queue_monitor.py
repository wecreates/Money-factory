"""Queue monitor tests use only synthetic adapter receipts and requests."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from integrations.local_agent_queue import Queue, work
from integrations import queue_monitor
from integrations.queue_monitor import inspect_queue


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromtimestamp(1000, timezone.utc)


def job(name='storyboard', attempts=2):
    return {
        'id': name,
        'adapter': 'openclaw',
        'request': {
            'tool': 'openclaw', 'operation': 'run-text',
            'publication_enabled': False, 'paid_generation_enabled': False,
            'model': 'local-model', 'model_url': 'http://127.0.0.1:11434',
            'prompt': 'Synthetic fixture prompt.', 'timeout_seconds': 5,
            'worker_memory_mb': 512, 'shared_model_memory_mb': 1024,
            'render_memory_mb': 0, 'render_cpu': 0,
        },
        'max_attempts': attempts,
        'publication_enabled': False,
        'paid_generation_enabled': False,
    }


@unittest.skipUnless(os.name == 'posix', 'Consumer ownership inspection requires POSIX flock')
class QueueMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'queue'
        self.queue = Queue(self.root)

    def tearDown(self):
        self.queue.close()

    def test_queued_work_alerts_without_exposing_prompt_and_read_is_side_effect_free(self):
        self.queue.enqueue(job())
        before = (hashlib.sha256((self.root / 'queue.sqlite3').read_bytes()).hexdigest(),
                  (self.root / 'queue.sqlite3').stat().st_mtime_ns)
        result = inspect_queue(self.root, now=NOW)
        after = (hashlib.sha256((self.root / 'queue.sqlite3').read_bytes()).hexdigest(),
                 (self.root / 'queue.sqlite3').stat().st_mtime_ns)
        self.assertEqual(before, after)
        self.assertEqual(result['status'], 'ATTENTION_REQUIRED')
        self.assertIn('queued_jobs_without_active_consumer',
                      [item['code'] for item in result['alerts']])
        self.assertEqual(result['jobs'][0]['resource_limits']['timeout_seconds'], 5)
        self.assertEqual(result['jobs'][0]['resource_limits']['worker_memory_mb'], 512)
        self.assertNotIn('prompt', json.dumps(result))
        self.assertFalse(result['alert_delivery_configured'])
        self.assertFalse(result['publication_enabled'])
        self.assertFalse(result['paid_generation_enabled'])

    def test_succeeded_queue_is_healthy_but_does_not_claim_deployed_monitoring(self):
        self.queue.enqueue(job())
        work(self.queue, executor=lambda _: {
            'status': 'PASS', 'publication_enabled': False,
            'paid_generation_enabled': False,
        })
        result = inspect_queue(self.root)
        self.assertEqual(result['status'], 'HEALTHY')
        self.assertEqual(result['job_counts'], {'succeeded': 1})
        self.assertEqual(result['alerts'], [])
        self.assertFalse(result['deployed_monitor_verified'])
        self.assertFalse(result['twenty_four_hour_soak_verified'])

    def test_blocked_exhausted_job_retains_two_actionable_alerts(self):
        self.queue.enqueue(job(attempts=1))
        work(self.queue, executor=lambda _: {
            'status': 'BLOCKED', 'reason': 'synthetic fixture',
            'publication_enabled': False, 'paid_generation_enabled': False,
        })
        result = inspect_queue(self.root)
        codes = [item['code'] for item in result['alerts']]
        self.assertIn('job_blocked', codes)
        self.assertIn('attempt_limit_exhausted', codes)
        self.assertNotIn('synthetic fixture', json.dumps(result))

    def test_running_job_without_consumer_is_critical(self):
        self.queue.enqueue(job())
        with self.queue.consumer():
            self.queue.claim()
        result = inspect_queue(self.root)
        self.assertIn('running_job_without_consumer',
                      [item['code'] for item in result['alerts']])

    def test_running_job_with_untracked_lock_owner_is_critical(self):
        self.queue.enqueue(job())
        with self.queue.consumer():
            self.queue.claim()
            result = inspect_queue(self.root)
        self.assertIn('running_jobs_without_tracked_worker',
                      [item['code'] for item in result['alerts']])

    def test_cli_blocks_missing_queue_without_creating_it(self):
        missing = Path(self.temp.name) / 'missing'
        result = subprocess.run(
            [sys.executable, '-m', 'integrations.queue_monitor', '--queue', str(missing)],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['status'], 'BLOCKED')
        self.assertFalse(missing.exists())

    def test_corrupt_stored_envelope_fails_closed(self):
        self.queue.enqueue(job())
        self.queue.db.execute("UPDATE jobs SET spec='{}'")
        with self.assertRaisesRegex(ValueError, 'envelope is inconsistent'):
            inspect_queue(self.root)

    def test_job_and_run_identifiers_are_validated_without_echoing_them(self):
        self.queue.enqueue(job())
        malicious = 'secret/job?token=value'
        self.queue.db.execute('UPDATE jobs SET id=?', (malicious,))
        with self.assertRaises(ValueError) as error:
            inspect_queue(self.root)
        self.assertNotIn(malicious, str(error.exception))

        self.queue.close()
        self.queue = Queue(self.root)
        self.queue.db.execute('DELETE FROM jobs')
        with self.queue.consumer():
            run_id = self.queue.start_run({
                'max_jobs': 1, 'watch_seconds': 0, 'poll_seconds': 1,
                'auto_retry': False,
            })
            self.queue.db.execute('UPDATE worker_runs SET id=? WHERE id=?',
                                  (malicious, run_id))
        with self.assertRaises(ValueError) as error:
            inspect_queue(self.root)
        self.assertNotIn(malicious, str(error.exception))

    def test_worker_config_requires_exact_typed_bounded_fields(self):
        valid = {'max_jobs': 1, 'watch_seconds': 0, 'poll_seconds': 1,
                 'auto_retry': False}
        with self.queue.consumer():
            run_id = self.queue.start_run(valid)
        variants = [
            {**valid, 'secret': 'do-not-project'},
            {**valid, 'max_jobs': True}, {**valid, 'max_jobs': 1001},
            {**valid, 'watch_seconds': -1}, {**valid, 'watch_seconds': True},
            {**valid, 'poll_seconds': .1}, {**valid, 'poll_seconds': float('nan')},
            {**valid, 'auto_retry': 0},
        ]
        for config in variants:
            with self.subTest(config=config):
                self.queue.db.execute('UPDATE worker_runs SET config=? WHERE id=?',
                                      (json.dumps(config), run_id))
                with self.assertRaisesRegex(ValueError, 'configuration is invalid'):
                    inspect_queue(self.root)

    def test_corrupt_worker_heartbeat_fails_closed(self):
        with self.queue.consumer():
            run_id = self.queue.start_run({
                'max_jobs': 1, 'watch_seconds': 0, 'poll_seconds': 1,
                'auto_retry': False,
            })
            self.queue.db.execute(
                "UPDATE worker_runs SET heartbeat='bad' WHERE id=?", (run_id,))
        with self.assertRaisesRegex(ValueError, 'run state is invalid'):
            inspect_queue(self.root)

    def test_retained_finished_error_and_interrupted_runs_alert(self):
        config = {'max_jobs': 1, 'watch_seconds': 0, 'poll_seconds': 1,
                  'auto_retry': False}
        with self.queue.consumer():
            errored = self.queue.start_run(config)
            self.queue.update_run(errored, processed=0, finished=True, reason='error')
            interrupted = self.queue.start_run(config)
            self.queue.update_run(interrupted, processed=0, finished=True,
                                  reason='interrupted')
        result = inspect_queue(self.root)
        codes = [item['code'] for item in result['alerts']]
        self.assertIn('retained_worker_error', codes)
        self.assertIn('retained_worker_interrupted', codes)
        self.assertEqual(result['status'], 'ATTENTION_REQUIRED')

    def test_terminal_state_finish_and_reason_invariants_fail_closed(self):
        config = {'max_jobs': 1, 'watch_seconds': 0, 'poll_seconds': 1,
                  'auto_retry': False}
        with self.queue.consumer():
            run_id = self.queue.start_run(config)
            self.queue.update_run(run_id, processed=0, finished=True,
                                  reason='job_limit')
        original = dict(self.queue.db.execute(
            'SELECT state,finished,exit_reason FROM worker_runs WHERE id=?',
            (run_id,)).fetchone())
        cases = (
            ('finished', None, 'job_limit', 'finish timestamp'),
            ('watching', original['finished'], 'job_limit', 'terminal fields'),
            ('finished', original['finished'], 'error', 'exit reason'),
            ('error', original['finished'], 'job_limit', 'exit reason'),
        )
        for state, finished, reason, message in cases:
            with self.subTest(state=state, finished=finished, reason=reason):
                self.queue.db.execute(
                    'UPDATE worker_runs SET state=?,finished=?,exit_reason=? WHERE id=?',
                    (state, finished, reason, run_id))
                with self.assertRaisesRegex(ValueError, message):
                    inspect_queue(self.root)
                self.queue.db.execute(
                    'UPDATE worker_runs SET state=?,finished=?,exit_reason=? WHERE id=?',
                    (original['state'], original['finished'], original['exit_reason'], run_id))

    def test_database_identity_change_during_query_fails_closed(self):
        self.queue.enqueue(job())
        identity = queue_monitor._database_identity(self.root)
        changed = json.loads(json.dumps(identity))
        changed['sha256'] = '0' * 64
        with patch.object(queue_monitor, '_database_identity',
                          side_effect=[identity, changed]):
            with self.assertRaisesRegex(ValueError, 'changed while monitoring'):
                inspect_queue(self.root)

    def test_retained_real_queue_snapshot_binds_monitor_and_database(self):
        proof = json.loads((ROOT / 'integrations/queue-monitor-proof-20261124.json').read_text())
        source = ROOT / 'integrations/queue_monitor.py'
        database = (ROOT / 'integrations/local_queue/evidence/'
                    'c12-real-admission-retry-20261124-v2/runtime/queue.sqlite3')
        self.assertEqual(proof['monitor_source_sha256'],
                         hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(proof['result']['queue_database_sha256'],
                         hashlib.sha256(database.read_bytes()).hexdigest())
        raw = json.dumps(proof['result'], indent=2, sort_keys=True, allow_nan=False) + '\n'
        self.assertEqual(proof['raw_output_sha256'], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(proof['result']['status'], 'ATTENTION_REQUIRED')
        self.assertFalse(proof['acceptance_limits']['alert_delivery_configured'])
        self.assertFalse(proof['acceptance_limits']['twenty_four_hour_soak_verified'])


if __name__ == '__main__':
    unittest.main()
