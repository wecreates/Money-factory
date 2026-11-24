import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from integrations.agent_capacity import (_cgroup_v2_limits, collect_snapshot, recommend_capacity,
                                         _admission_lock_at, AdmissionBusy)

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


class CapacityTests(unittest.TestCase):
    def snapshot(self, **values):
        return {'observed_at': NOW.isoformat(), 'effective_cpu_cores': 12,
                'memory_available_mb': 20000, **values}

    def budget(self, snapshot=None, **args):
        return recommend_capacity(snapshot or self.snapshot(), worker_memory_mb=1024,
                                  requested_workers=100, now=NOW, **args)

    def test_reserves_headroom_and_caps_requested_slots(self):
        result = self.budget()
        self.assertEqual(result['admitted_workers'], 8)
        self.assertIs(result['publication_enabled'], False)
        self.assertEqual(result['scope'], 'resource_budget_only_not_model_readiness')

    def test_shared_model_memory_is_reserved(self):
        self.assertEqual(self.budget(reserve_memory_mb=17000)['admitted_workers'], 2)

    def test_render_and_shared_model_reserves_are_separate(self):
        result = self.budget(shared_model_memory_mb=8000, render_memory_mb=5000, render_cpu=6)
        self.assertEqual(result['admitted_workers'], 4)
        self.assertEqual(result['reserves']['render_cpu'], 6)

    def test_low_memory_or_cpu_blocks(self):
        for snapshot in (self.snapshot(memory_available_mb=2047), self.snapshot(effective_cpu_cores=1.5)):
            self.assertEqual(self.budget(snapshot)['admitted_workers'], 0)

    def test_fractional_cpu_quota_is_not_rounded_up(self):
        self.assertEqual(self.budget(self.snapshot(effective_cpu_cores=3.5))['admitted_workers'], 1)

    def test_missing_unknown_nonfinite_and_stale_snapshots_block(self):
        for snapshot in ({'observed_at': NOW.isoformat()}, self.snapshot(memory_available_mb=None),
                         self.snapshot(effective_cpu_cores=float('inf')),
                         self.snapshot(observed_at=(NOW - timedelta(seconds=61)).isoformat()),
                         self.snapshot(observed_at=(NOW + timedelta(seconds=1)).isoformat()),
                         self.snapshot(observed_at='invalid')):
            self.assertEqual(self.budget(snapshot)['admitted_workers'], 0)

    def test_negative_or_nonfinite_worker_budgets_rejected(self):
        for amount in (0, -1, True, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                recommend_capacity(self.snapshot(), worker_memory_mb=amount, requested_workers=4, now=NOW)

    def test_request_can_be_smaller_than_capacity(self):
        self.assertEqual(recommend_capacity(self.snapshot(), worker_memory_mb=1024,
                         requested_workers=2, now=NOW)['admitted_workers'], 2)

    def test_nested_cgroup_uses_tightest_ancestor_headroom(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'cgroup'; child = root / 'worker'; child.mkdir(parents=True)
            (root / 'cgroup.controllers').write_text('cpu memory')
            (root / 'cpu.max').write_text('200000 100000')
            (root / 'memory.max').write_text(str(4096 * 1024**2))
            (root / 'memory.current').write_text(str(3072 * 1024**2))
            (child / 'cpu.max').write_text('350000 100000')
            (child / 'memory.max').write_text('max')
            membership = Path(tmp) / 'membership'; membership.write_text('0::/worker\n')
            self.assertEqual(_cgroup_v2_limits(root, membership), (2, 1024, []))
            (root / 'memory.current').unlink()
            self.assertIn('cgroup_memory_unreadable', _cgroup_v2_limits(root, membership)[2])

    def test_hierarchy_root_absent_max_controls_are_not_failed_measurements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'cgroup'; child = root / 'worker'; child.mkdir(parents=True)
            (root / 'cgroup.controllers').write_text('cpu memory')
            (child / 'cpu.max').write_text('150000 100000')
            (child / 'memory.max').write_text(str(4096 * 1024**2))
            (child / 'memory.current').write_text(str(1024 * 1024**2))
            membership = Path(tmp) / 'membership'; membership.write_text('0::/worker\n')
            self.assertEqual(_cgroup_v2_limits(root, membership), (1.5, 3072, []))
            # A bounded child without usage still fails; absent root limits do
            # not excuse a missing current-group measurement.
            (child / 'memory.current').unlink()
            self.assertIn('cgroup_memory_unreadable', _cgroup_v2_limits(root, membership)[2])
            # Controller support must be established, not inferred from a missing file.
            (root / 'cgroup.controllers').write_text('')
            self.assertIn('cgroup_cpu_unreadable', _cgroup_v2_limits(root, membership)[2])

    def test_unreadable_container_limits_do_not_use_host_totals(self):
        with patch('integrations.agent_capacity.platform.system', return_value='Linux'), \
             patch('integrations.agent_capacity._memory_available_mb', return_value=48000), \
             patch('integrations.agent_capacity._cgroup_v2_limits', return_value=(None, None, ['cgroup_v2_unavailable'])):
            result = collect_snapshot()
            self.assertIsNone(result['effective_cpu_cores'])
            self.assertIsNone(result['memory_available_mb'])
            self.assertIs(result['model_execution_verified'], False)
            self.assertEqual(result['scope'], 'current_execution_host_only')

    def test_explicit_operator_ceiling_bounds_missing_cgroup_mount(self):
        with patch('integrations.agent_capacity.platform.system', return_value='Linux'), \
             patch('integrations.agent_capacity.os.cpu_count', return_value=12), \
             patch('integrations.agent_capacity.os.sched_getaffinity', return_value=set(range(9))), \
             patch('integrations.agent_capacity._memory_available_mb', return_value=8192), \
             patch('integrations.agent_capacity._disk_available_mb', return_value=4096), \
             patch('integrations.agent_capacity._cgroup_v2_limits',
                   return_value=(None, None, ['cgroup_v2_unavailable'])):
            result = collect_snapshot(
                declared_cpu_cores=4, declared_memory_mb=6144,
                disk_path='/queue')
        self.assertEqual(result['effective_cpu_cores'], 4)
        self.assertEqual(result['memory_available_mb'], 6144)
        self.assertEqual(result['disk_available_mb'], 4096)
        self.assertEqual(result['resource_boundary'], 'operator_declared_ceiling')
        self.assertEqual(result['declared_ceiling'], {
            'cpu_cores': 4, 'memory_mb': 6144,
            'source': 'explicit_host_operator_configuration'})
        self.assertIn('using_explicit_operator_ceiling', result['warnings'])

    def test_missing_or_partial_operator_ceiling_still_fails_closed(self):
        with patch('integrations.agent_capacity.platform.system', return_value='Linux'), \
             patch('integrations.agent_capacity._memory_available_mb', return_value=48000), \
             patch('integrations.agent_capacity._cgroup_v2_limits',
                   return_value=(None, None, ['cgroup_v2_unavailable'])):
            result = collect_snapshot()
        self.assertIsNone(result['effective_cpu_cores'])
        self.assertIsNone(result['memory_available_mb'])
        self.assertEqual(result['resource_boundary'], 'unknown_linux_container')
        for values in ({'declared_cpu_cores': 2}, {'declared_memory_mb': 4096}):
            with self.assertRaisesRegex(ValueError, 'Both declared'):
                collect_snapshot(**values)

    def test_shared_lock_blocks_other_framework_and_recovers_after_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = str(Path(tmp) / 'agent-admission.lock')
            code = ('from integrations.agent_capacity import _admission_lock_at; '
                    'import sys; '
                    'lock = _admission_lock_at(sys.argv[1]); lock.__enter__(); '
                    'from pathlib import Path; Path(sys.argv[2]).write_text("held"); sys.stdin.read()')
            marker = Path(tmp) / 'held'
            child = subprocess.Popen([sys.executable, '-c', code, lock, str(marker)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(marker.exists(), 'Lock holder did not start within five seconds')
                # Both framework wrappers use this same lock implementation.
                with self.assertRaises(AdmissionBusy):
                    with _admission_lock_at(lock):
                        self.fail('Second framework entered a held budget')
                child.kill()
                child.wait(timeout=5)
                with _admission_lock_at(lock):
                    self.assertTrue(Path(lock).exists())
            finally:
                if child.poll() is None:
                    child.kill(); child.wait(timeout=5)
                child.stdin.close(); child.stdout.close()

    def test_shared_lock_releases_on_exception_and_keeps_same_inode(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'agent-admission.lock'
            with self.assertRaisesRegex(ValueError, 'task failed'):
                with _admission_lock_at(lock):
                    inode = lock.stat().st_ino
                    raise ValueError('task failed')
            with _admission_lock_at(lock):
                self.assertEqual(lock.stat().st_ino, inode)

    def test_cli_is_read_only_json_and_never_claims_remote_host(self):
        result = subprocess.run([sys.executable, '-m', 'integrations.agent_capacity',
                                 '--worker-memory-mb', '1024'], capture_output=True, text=True, timeout=10)
        self.assertIn(result.returncode, (0, 2))
        report = json.loads(result.stdout)
        self.assertEqual(report['snapshot']['scope'], 'current_execution_host_only')
        self.assertIs(report['snapshot']['vpn_capacity_verified'], False)


if __name__ == '__main__':
    unittest.main()
