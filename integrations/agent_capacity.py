"""Read-only local agent capacity planning. Never launches agents or exposes ports."""
import argparse
import ctypes
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform

MIB = 1024 * 1024


def _number(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'{name} must be a finite number >= {minimum}')
    return value


def _memory_available_mb():
    if platform.system() == 'Windows':
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ('total_phys', 'avail_phys', 'total_page', 'avail_page', 'total_virtual', 'avail_virtual', 'avail_extended')]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.avail_phys / MIB
    if platform.system() == 'Linux':
        values = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
        # MemFree omits reclaimable cache and is not a substitute for MemAvailable.
        return int(values['MemAvailable'].split()[0]) / 1024
    return None


def _cgroup_v2_limits(root=Path('/sys/fs/cgroup'), membership=Path('/proc/self/cgroup')):
    """Read current cgroup and ancestor limits; unknown bounded usage fails closed."""
    root = Path(root)
    if not (root / 'cgroup.controllers').exists():
        return None, None, ['cgroup_v2_unavailable']
    controllers = set((root / 'cgroup.controllers').read_text().split())
    relative = next((line.split(':', 2)[2] for line in membership.read_text().splitlines() if line.startswith('0::')), '/')
    root = root.resolve()
    current = (root / relative.lstrip('/')).resolve()
    if current != root and root not in current.parents:
        return None, None, ['cgroup_membership_outside_mount']
    if not current.is_dir():
        current = root  # A cgroup namespace can expose its own group at mount root.
    cpu_limits, memory_limits, warnings = [], [], []
    for directory in (current, *current.parents):
        if directory != root and root not in directory.parents:
            break
        try:
            cpu_file = directory / 'cpu.max'
            # The hierarchy root has no parent and therefore no max controls.
            # Establish controller support before treating that absence as
            # unbounded; unreadable existing files remain errors.
            if directory == root and 'cpu' in controllers and not cpu_file.exists():
                quota, period = 'max', '1'
            else:
                quota, period = cpu_file.read_text().split()
            if quota != 'max':
                cpu_limits.append(int(quota) / int(period))
        except (OSError, ValueError, ZeroDivisionError):
            warnings.append('cgroup_cpu_unreadable')
        try:
            memory_file = directory / 'memory.max'
            if directory == root and 'memory' in controllers and not memory_file.exists():
                maximum = 'max'
            else:
                maximum = memory_file.read_text().strip()
            if maximum != 'max':
                used = int((directory / 'memory.current').read_text())
                memory_limits.append(max(0, int(maximum) - used) / MIB)
        except (OSError, ValueError):
            warnings.append('cgroup_memory_unreadable')
    return min(cpu_limits, default=None), min(memory_limits, default=None), sorted(set(warnings))


def collect_snapshot():
    warnings = []
    cpus = os.cpu_count()
    try:
        cpus = min(cpus or 1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass
    try:
        available = _memory_available_mb()
    except (OSError, KeyError, ValueError, AttributeError):
        available = None
    if platform.system() == 'Linux':
        try:
            quota, memory, notices = _cgroup_v2_limits()
            warnings.extend(notices)
            if quota is not None:
                cpus = min(cpus or quota, quota)
            if memory is not None:
                available = min(available, memory) if available is not None else memory
            # Unknown container limits must not turn host totals into capacity.
            if notices:
                cpus, available = None, None
        except (OSError, ValueError):
            warnings.append('cgroup_limits_unavailable')
            cpus, available = None, None
    return {
        'schema_version': 1,
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'current_execution_host_only',
        'platform': platform.system(),
        'effective_cpu_cores': cpus,
        'memory_available_mb': available,
        'warnings': warnings,
        'vpn_capacity_verified': False,
        'model_execution_verified': False,
        'publication_enabled': False,
    }


def recommend_capacity(snapshot, *, worker_memory_mb, requested_workers, cpu_per_worker=1,
                       reserve_memory_mb=2048, reserve_cpu=2, max_workers=8, now=None,
                       shared_model_memory_mb=0, render_memory_mb=0, render_cpu=0):
    """Budget recommendation, not a reservation or proof that a model is installed.

    Use shared_model_memory_mb for additional model memory beyond OS headroom.
    The caller must enforce the result across all workers/frameworks and resample
    before each new batch. Model throughput can require a lower concurrency.
    """
    for name, value, minimum in (
        ('worker_memory_mb', worker_memory_mb, 1), ('requested_workers', requested_workers, 0),
        ('cpu_per_worker', cpu_per_worker, .01), ('reserve_memory_mb', reserve_memory_mb, 0),
        ('reserve_cpu', reserve_cpu, 0), ('max_workers', max_workers, 1),
        ('shared_model_memory_mb', shared_model_memory_mb, 0),
        ('render_memory_mb', render_memory_mb, 0), ('render_cpu', render_cpu, 0)):
        _number(value, name, minimum)
    if not isinstance(requested_workers, int) or not isinstance(max_workers, int):
        raise ValueError('worker counts must be integers')
    base = {'admitted_workers': 0, 'requested_workers': requested_workers,
            'status': 'BLOCKED', 'reasons': [], 'publication_enabled': False,
            'scope': 'resource_budget_only_not_model_readiness'}
    try:
        observed = datetime.fromisoformat(snapshot['observed_at'])
        age = ((now or datetime.now(timezone.utc)) - observed).total_seconds()
        if not 0 <= age <= 60:
            raise ValueError('stale snapshot')
        cpu = _number(snapshot['effective_cpu_cores'], 'effective_cpu_cores')
        memory = _number(snapshot['memory_available_mb'], 'memory_available_mb')
    except (KeyError, TypeError, ValueError):
        base['reasons'] = ['fresh_cpu_and_memory_snapshot_required']
        return base
    cpu_slots = max(0, math.floor((cpu - reserve_cpu - render_cpu) / cpu_per_worker))
    memory_slots = max(0, math.floor((memory - reserve_memory_mb - shared_model_memory_mb - render_memory_mb) / worker_memory_mb))
    admitted = min(cpu_slots, memory_slots, requested_workers, max_workers)
    base.update(admitted_workers=admitted, cpu_slots=cpu_slots, memory_slots=memory_slots,
                status='WITHIN_BUDGET' if admitted else 'BLOCKED',
                reserves={'os_memory_mb': reserve_memory_mb, 'os_cpu': reserve_cpu,
                          'unallocated_shared_model_memory_mb': shared_model_memory_mb,
                          'render_memory_mb': render_memory_mb, 'render_cpu': render_cpu})
    if admitted < requested_workers:
        base['reasons'].append('request_exceeds_reserved_resource_budget')
    return base


class AdmissionBusy(RuntimeError):
    """Another local framework currently owns the per-user execution budget."""


@contextmanager
def _admission_lock_at(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        # Windows byte-range locks require one existing byte. The lock file is
        # persistent and never unlinked, preventing separate inode lock domains.
        if os.fstat(fd).st_size == 0:
            os.write(fd, b'0')
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise AdmissionBusy('Another local agent batch owns the shared host budget') from exc
        yield
    finally:
        try:
            if locked:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def shared_admission_lock():
    """Nonblocking per-user lock shared by every checkout and agent framework.

    Hold through fresh capacity sampling and the complete batch/turn. OS lock
    release handles process termination; no PID-file stale-lock guessing occurs.
    """
    return _admission_lock_at(Path.home() / '.cyzor' / 'agent-admission.lock')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-memory-mb', type=float, required=True, help='Measured/estimated incremental memory per worker; not model size')
    parser.add_argument('--requested-workers', type=int, default=4)
    parser.add_argument('--reserve-memory-mb', type=float, default=2048, help='OS headroom plus shared model memory not already allocated')
    parser.add_argument('--shared-model-memory-mb', type=float, default=0, help='Additional memory needed for unloaded shared model')
    parser.add_argument('--render-memory-mb', type=float, default=0)
    parser.add_argument('--render-cpu', type=float, default=0)
    parser.add_argument('--reserve-cpu', type=float, default=2)
    parser.add_argument('--cpu-per-worker', type=float, default=1)
    args = parser.parse_args()
    snapshot = collect_snapshot()
    try:
        recommendation = recommend_capacity(snapshot, **vars(args))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({'snapshot': snapshot, 'recommendation': recommendation}, indent=2))
    return 0 if recommendation['admitted_workers'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
