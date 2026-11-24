"""Synthetic verifier tests; these fixtures are never actual-host acceptance."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from integrations.verify_actual_host_soak import verify


SOURCE = '1' * 40
HOST = '2' * 64
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def stamp(value):
    return value.isoformat()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity():
    return {
        'schema_version': 1,
        'source_commit': SOURCE,
        'host_fingerprint_sha256': HOST,
        'publication_enabled': False,
        'paid_generation_enabled': False,
    }


class ActualHostSoakTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.finish = START + timedelta(hours=24)
        self.manifest = {
            **identity(),
            'started_at': stamp(START),
            'finished_at': stamp(self.finish),
            'observations': [
                {
                    **identity(),
                    'observed_at': stamp(START + timedelta(hours=hour)),
                    'effective_cpu_cores': 8,
                    'memory_available_mb': 8192,
                    'admitted_workers': 1,
                    'shared_worker_ceiling': 1,
                    'agent_processes': 1,
                    'queue_depth': hour % 3,
                    'active_workers': 1 if hour % 3 else 0,
                    'idle_worker_healthy': hour % 3 == 0,
                    'orphan_workers': 0,
                    'unexplained_failures': 0,
                    'capacity_status': 'WITHIN_BUDGET',
                }
                for hour in range(25)
            ],
            'framework_runs': {'ruflo': [], 'openclaw': []},
            'drills': {},
            'queue': {
                'durable': True,
                'duplicate_protection_verified': True,
                'retry_recovery_verified': True,
                'resource_ceiling_enforced': True,
                'alert_delivery_verified': True,
                'stop_path_verified': True,
            },
            'artifacts': {},
        }
        run_hours = {
            'ruflo': (.5, 5, 19, 23.5),
            'openclaw': (1.1, 6, 20, 23.75),
        }
        for framework in ('ruflo', 'openclaw'):
            for number, hour in enumerate(run_hours[framework], 1):
                relative = f'runs/{framework}-{number}.json'
                output = f'outputs/{framework}-{number}.txt'
                (self.root / output).parent.mkdir(parents=True, exist_ok=True)
                (self.root / output).write_text(
                    f'{framework} reviewed storyboard output {number}\n')
                receipt = {
                    **identity(),
                    'kind': 'framework_run',
                    'framework': framework,
                    'run_id': f'{framework}-run-{number:02d}',
                    'started_at': stamp(START + timedelta(hours=hour)),
                    'finished_at': stamp(START + timedelta(hours=hour, minutes=10)),
                    'capacity_observed_at': stamp(START + timedelta(hours=int(hour))),
                    'status': 'PASS',
                    'runtime_version': (
                        '3.56.7' if framework == 'ruflo' else '2026.11.6'),
                    'model_execution_verified': True,
                    'local_model_verified': True,
                    'loopback_model_endpoint_verified': True,
                    'remote_model_metadata': False,
                    'cloud_model_tag': False,
                    'useful_output_reviewed': True,
                    'model_id_sha256': 'a' * 64,
                    'output_artifact': output,
                    'output_sha256': digest(self.root / output),
                    'input_tokens': 12,
                    'output_tokens': 24,
                    'workers': 1,
                    'admitted_workers': 1,
                    'shared_worker_ceiling': 1,
                    'shared_admission_lock_verified': True,
                }
                write(self.root / relative, receipt)
                self.manifest['framework_runs'][framework].append(relative)
        drill_values = {
            'controlled_stop': {'owned_processes_stopped': True},
            'no_orphans': {'orphan_processes': 0},
            'restart': {'fresh_run_directory': True, 'model_execution_verified': True},
            'shared_contention': {
                'second_framework_blocked': True, 'executed_tasks': 0,
                'rerun_passed': True},
            'queue_recovery': {'queue_recovered': True, 'duplicate_count': 0},
            'alert_stop': {
                'alert_delivery_verified': True, 'stop_path_verified': True},
        }
        for number, (drill_type, values) in enumerate(drill_values.items(), 1):
            relative = f'drills/{drill_type}.json'
            receipt = {
                **identity(),
                'kind': 'host_drill',
                'drill_type': drill_type,
                'status': 'PASS',
                'observed_at': stamp(START + timedelta(hours=number)),
                **values,
            }
            write(self.root / relative, receipt)
            self.manifest['drills'][drill_type] = relative
        self.refresh()

    def tearDown(self):
        self.temporary.cleanup()

    def refresh(self):
        self.manifest['artifacts'] = {
            path.relative_to(self.root).as_posix(): digest(path)
            for path in self.root.rglob('*')
            if path.is_file() and path.name != 'soak.json'
        }
        write(self.root / 'soak.json', self.manifest)

    def check(self):
        return verify(self.root, SOURCE, now=self.finish + timedelta(minutes=1))

    def test_complete_packet_passes_without_claiming_actual_host_acceptance(self):
        result = self.check()
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(result['soak_evidence_packet_verified'])
        self.assertFalse(result['actual_host_acceptance_verified'])
        self.assertTrue(result['independent_quality_review_required'])
        self.assertEqual(result['framework_runs'], {'ruflo': 4, 'openclaw': 4})
        self.assertFalse(result['publication_enabled'])

    def test_tampered_or_extra_artifact_fails(self):
        path = self.root / self.manifest['framework_runs']['ruflo'][0]
        path.write_text(path.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.check()
        path.write_text(path.read_text().rstrip())
        self.refresh()
        write(self.root / 'unexpected.json', {})
        with self.assertRaisesRegex(ValueError, 'artifact set differs'):
            self.check()

    def test_short_window_and_observation_gap_fail(self):
        self.manifest['started_at'] = stamp(START + timedelta(hours=1))
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'at least 24 hours'):
            self.check()
        self.manifest['started_at'] = stamp(START)
        self.manifest['observations'][12]['observed_at'] = stamp(
            START + timedelta(hours=11, minutes=30))
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'gap exceeds one hour'):
            self.check()

    def test_framework_execution_and_useful_review_are_required(self):
        path = self.root / self.manifest['framework_runs']['openclaw'][1]
        receipt = json.loads(path.read_text())
        receipt['model_execution_verified'] = False
        write(path, receipt)
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'run receipt is incomplete'):
            self.check()

    def test_worker_liveness_or_explicit_healthy_idle_is_required_all_day(self):
        for row in self.manifest['observations']:
            row['active_workers'] = 0
            row['idle_worker_healthy'] = True
        self.refresh()
        self.assertEqual(self.check()['status'], 'PASS')
        self.manifest['observations'][12]['agent_processes'] = 0
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'agent_processes'):
            self.check()
        self.manifest['observations'][12]['agent_processes'] = 1
        self.manifest['observations'][12]['idle_worker_healthy'] = False
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'unsafe runtime state'):
            self.check()

    def test_run_workers_must_fit_correlated_authoritative_capacity(self):
        path = self.root / self.manifest['framework_runs']['ruflo'][0]
        receipt = json.loads(path.read_text())
        receipt['workers'] = 8
        write(path, receipt)
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'run receipt is incomplete'):
            self.check()

    def test_run_window_must_be_covered_by_its_named_capacity_observation(self):
        path = self.root / self.manifest['framework_runs']['ruflo'][1]
        receipt = json.loads(path.read_text())
        receipt['capacity_observed_at'] = stamp(START + timedelta(hours=4))
        write(path, receipt)
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'run receipt is incomplete'):
            self.check()

    def test_overlapping_framework_runs_cannot_exceed_shared_ceiling(self):
        ruflo = json.loads(
            (self.root / self.manifest['framework_runs']['ruflo'][0]).read_text())
        path = self.root / self.manifest['framework_runs']['openclaw'][0]
        openclaw = json.loads(path.read_text())
        openclaw['started_at'] = ruflo['started_at']
        openclaw['finished_at'] = ruflo['finished_at']
        openclaw['capacity_observed_at'] = ruflo['capacity_observed_at']
        write(path, openclaw)
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'exceed shared ceiling'):
            self.check()

    def test_copied_run_identity_fails_even_under_distinct_paths(self):
        paths = self.manifest['framework_runs']['ruflo'][:2]
        first = json.loads((self.root / paths[0]).read_text())
        second = json.loads((self.root / paths[1]).read_text())
        second['run_id'] = first['run_id']
        write(self.root / paths[1], second)
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'run receipt is incomplete'):
            self.check()

    def test_missing_or_tampered_reviewable_output_fails(self):
        receipt_path = self.root / self.manifest['framework_runs']['openclaw'][0]
        receipt = json.loads(receipt_path.read_text())
        output = self.root / receipt['output_artifact']
        output.unlink()
        with self.assertRaisesRegex(ValueError, 'artifact set differs'):
            self.check()
        output.write_text('changed but still readable output\n')
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'output artifact hash mismatch'):
            self.check()

    def test_safety_flags_and_authoritative_capacity_fail_closed(self):
        self.manifest['observations'][3]['publication_enabled'] = True
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'identity or safety'):
            self.check()
        self.manifest['observations'][3]['publication_enabled'] = False
        self.manifest['observations'][3]['capacity_status'] = 'UNKNOWN'
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'unsafe runtime state'):
            self.check()

    def test_all_drills_and_operational_queue_gates_are_required(self):
        path = self.root / self.manifest['drills']['no_orphans']
        receipt = json.loads(path.read_text())
        receipt['orphan_processes'] = 1
        write(path, receipt)
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'drill receipt is incomplete'):
            self.check()
        receipt['orphan_processes'] = 0
        write(path, receipt)
        self.manifest['queue']['alert_delivery_verified'] = False
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'alerts and stop path'):
            self.check()

    def test_source_host_and_future_time_are_bound(self):
        with self.assertRaisesRegex(ValueError, 'expected source commit'):
            verify(self.root, '3' * 40, now=self.finish + timedelta(minutes=1))
        self.manifest['finished_at'] = stamp(self.finish + timedelta(hours=2))
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'future'):
            verify(self.root, SOURCE, now=self.finish)


if __name__ == '__main__':
    unittest.main()
