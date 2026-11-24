"""Create a closed real-adapter retry packet with process-level receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import time
from urllib.parse import quote

from integrations.agent_capacity import shared_admission_lock
from integrations.local_agent_queue import Queue, canonical


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def hold_lock(receipt_path, release_path, timeout):
    started = time.time()
    lock_path = Path.home() / '.cyzor' / 'agent-admission.lock'
    report = {'schema_version': 1, 'pid': os.getpid(), 'parent_pid': os.getppid(),
              'started_epoch': started, 'acquired': False, 'released': False,
              'publication_enabled': False, 'paid_generation_enabled': False}
    try:
        with shared_admission_lock():
            acquired = time.time(); info = lock_path.stat()
            fields = {'device': info.st_dev, 'inode': info.st_ino,
                      'mode': stat.S_IMODE(info.st_mode), 'size': info.st_size}
            report.update(acquired=True, acquired_epoch=acquired,
                          lock_identity={**fields,
                              'identity_sha256': hashlib.sha256(canonical(fields).encode()).hexdigest(),
                              'path_sha256': hashlib.sha256(str(lock_path.resolve()).encode()).hexdigest(),
                              'content_sha256': digest(lock_path)})
            write_json(receipt_path, report)
            deadline = time.monotonic() + timeout
            while not Path(release_path).is_file():
                if time.monotonic() >= deadline:
                    raise TimeoutError('Lock-holder release deadline expired')
                time.sleep(.02)
        report.update(released=True, released_epoch=time.time())
        write_json(receipt_path, report)
        return 0
    except BaseException as error:
        report.update(error_type=type(error).__name__, finished_epoch=time.time())
        write_json(receipt_path, report)
        return 2


def worker_command(root, content_root, local_python):
    return [sys.executable, '-m', 'integrations.local_agent_queue',
            '--queue', str(root / 'runtime'), 'work', '--max-jobs', '1',
            '--watch-seconds', '0', '--poll-seconds', '1', '--auto-retry',
            '--content-control-root', str(content_root),
            '--video-python', str(local_python), '--picture-python', str(local_python)]


def sanitized_command():
    return ['python', '-m', 'integrations.local_agent_queue', '--queue',
            '$EVIDENCE_ROOT/runtime', 'work', '--max-jobs', '1',
            '--watch-seconds', '0', '--poll-seconds', '1', '--auto-retry',
            '--content-control-root', '$CONTENT_CONTROL_ROOT',
            '--video-python', '$LOCAL_PYTHON', '--picture-python', '$LOCAL_PYTHON']


def run_worker(number, root, content_root, local_python, request_timeout):
    command = worker_command(root, content_root, local_python)
    started = time.time()
    process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[2],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=request_timeout + 30)
    finished = time.time()
    if stderr:
        raise RuntimeError('Queue worker wrote unexpected stderr')
    stdout_path = root / f'process/worker-{number}-stdout.json'
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open('xb') as stream:
        stream.write(stdout); stream.flush(); os.fsync(stream.fileno())
    result = json.loads(stdout)
    retry_queued = result['processed'][0]['automatic_retry_queued']
    receipt = {
        'schema_version': 1, 'run_number': number, 'pid': process.pid,
        'parent_pid': os.getpid(), 'started_epoch': started, 'finished_epoch': finished,
        'sanitized_command': sanitized_command(),
        'sanitized_command_sha256': hashlib.sha256(canonical(sanitized_command()).encode()).hexdigest(),
        'actual_command_sha256': hashlib.sha256(canonical(command).encode()).hexdigest(),
        'bounded_parameters': {'auto_retry': True, 'max_jobs': 1, 'poll_seconds': 1,
                               'watch_seconds': 0, 'request_timeout_seconds': request_timeout},
        'exit_code': process.returncode,
        'stdout': stdout_path.relative_to(root).as_posix(),
        'stdout_sha256': digest(stdout_path),
        'automatic_retry_queued': retry_queued,
        'publication_enabled': False, 'paid_generation_enabled': False,
    }
    write_json(root / f'process/worker-{number}.json', receipt)
    return receipt, result


def database_rows(path):
    uri = 'file:' + quote(str(Path(path).resolve()), safe='/') + '?mode=ro&immutable=1'
    connection = sqlite3.connect(uri, uri=True); connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        return (
            [dict(row) for row in connection.execute('SELECT * FROM jobs')],
            [dict(row) for row in connection.execute('SELECT * FROM attempts ORDER BY number')],
            [dict(row) for row in connection.execute('SELECT * FROM automatic_retry_events ORDER BY from_attempt')],
        )
    finally:
        connection.close()


def create_packet(root, content_root, local_python, source_commit, source_manifest):
    root = Path(root).absolute(); content_root = Path(content_root).resolve(strict=True)
    local_python = Path(local_python).absolute()
    if root.exists() or not local_python.is_file() or not os.access(local_python, os.X_OK):
        raise ValueError('Require a new evidence root and executable local Python')
    root.mkdir(parents=True)
    started = time.time()
    job = {
        'id': 'c12-real-admission-retry-20261124v2', 'adapter': 'content-control-video',
        'request': {'operation': 'produce-episode1-review', 'source_commit': source_commit,
                    'source_manifest_sha256': source_manifest, 'timeout_seconds': 120,
                    'publication_enabled': False, 'paid_generation_enabled': False},
        'max_attempts': 2, 'publication_enabled': False, 'paid_generation_enabled': False,
    }
    write_json(root / 'job.json', job)
    queue = Queue(root / 'runtime')
    try:
        queue.enqueue(job)
    finally:
        queue.close()

    release = root / 'process/release.signal'
    holder_receipt = root / 'process/lock-holder.json'
    holder_command = [sys.executable, '-m', 'integrations.local_queue.run_retry_evidence',
                      '--hold-lock', '--receipt', str(holder_receipt), '--release', str(release),
                      '--hold-timeout', '30']
    holder = subprocess.Popen(holder_command, cwd=Path(__file__).resolve().parents[2],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    first = second = None
    try:
        deadline = time.monotonic() + 10
        while True:
            if holder_receipt.is_file() and json.loads(holder_receipt.read_text()).get('acquired') is True:
                break
            if holder.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('Separate lock holder did not acquire admission')
            time.sleep(.02)
        first, first_stdout = run_worker(1, root, content_root, local_python, 120)
        if first['exit_code'] != 2 or first['automatic_retry_queued'] is not True:
            raise RuntimeError('First worker did not durably queue one automatic retry')
        write_json(release, {'release': True, 'created_epoch': time.time()})
        if holder.wait(timeout=10) != 0:
            raise RuntimeError('Lock holder did not release cleanly')
        release.unlink()
        second, second_stdout = run_worker(2, root, content_root, local_python, 120)
        if second['exit_code'] != 2 or second['automatic_retry_queued'] is not False:
            raise RuntimeError('Second worker did not stop at the immutable attempt bound')
    finally:
        if holder.poll() is None:
            write_json(release, {'release': True, 'created_epoch': time.time()})
            try: holder.wait(timeout=5)
            except subprocess.TimeoutExpired: holder.kill(); holder.wait()
        if release.exists(): release.unlink()

    consumer_lock = root / 'runtime/consumer.lock'
    if consumer_lock.exists(): consumer_lock.unlink()
    holder_data = json.loads(holder_receipt.read_text())
    launcher = {
        'schema_version': 1, 'pid': os.getpid(), 'parent_pid': os.getppid(),
        'started_epoch': started, 'finished_epoch': time.time(),
        'lock_holder_pid': holder.pid, 'worker_pids': [first['pid'], second['pid']],
        'worker_run_ids': [first_stdout['worker']['id'], second_stdout['worker']['id']],
        'holder_sanitized_command': ['python', '-m', 'integrations.local_queue.run_retry_evidence',
                                     '--hold-lock', '--receipt', '$EVIDENCE_ROOT/process/lock-holder.json',
                                     '--release', '$EVIDENCE_ROOT/process/release.signal',
                                     '--hold-timeout', '30'],
        'holder_exit_code': holder.returncode,
        'publication_enabled': False, 'paid_generation_enabled': False,
    }
    write_json(root / 'process/launcher.json', launcher)
    readme = (
        '# Real bounded automatic-retry evidence — 2026-11-24 (v2)\n\n'
        'A separate process acquired the real per-user OS admission lock. The first bounded '\
        'durable-queue worker invoked the real content-control-video adapter, retained a '\
        'retryable AdmissionBusy receipt, and durably queued one automatic retry. After the '\
        'holder released the lock, a second bounded worker consumed that retry and ran live '\
        'offline Node/npm/FFmpeg/font/runtime prerequisite subprocess checks. It stopped '\
        'non-retryably on missing transcription/picture environments and cached ASR.\n\n'
        'The SQLite database, adapter receipts, launcher/holder/worker process receipts, '\
        'worker stdout, and immutable job are hash-bound by evidence.json. Verification opens '\
        'SQLite with mode=ro and query_only, rejects extra files, recomputes hashes and the job '\
        'digest, and checks exact attempt/event/run rows, limits, ordering, receipt equality, '\
        'process exits, and disabled publication/paid flags.\n\n'
        'This is bounded local retry evidence only—not successful media production, full AV '\
        'review, actual-PC/VPN/VPS acceptance, a 24-hour soak, or production readiness.\n')
    (root / 'README.md').write_text(readme)

    jobs, attempts, retries = database_rows(root / 'runtime/queue.sqlite3')
    evidence = {
        'schema_version': 2, 'observed_epoch': time.time(),
        'job_digest': hashlib.sha256(canonical(job).encode()).hexdigest(),
        'publication_enabled': False, 'paid_generation_enabled': False,
        'production_ready': False,
        'limits': {'automatic_retry_events': 1, 'attempts_used': 2,
                   'job_max_attempts': 2, 'request_timeout_seconds': 120,
                   'worker_max_jobs': 1, 'worker_process_exit': 2},
        'automatic_retry': {'from_attempt': retries[0]['from_attempt'],
                            'created_epoch': retries[0]['created'],
                            'reason': retries[0]['reason']},
        'attempts': [
            {'number': row['number'], 'started_epoch': row['started'],
             'finished_epoch': row['finished'],
             'receipt': f"runtime/attempts/{job['id']}/{row['number']}/video-adapter-receipt.json",
             'retryable': row['number'] == 1}
            for row in attempts],
        'claims_not_made': ['successful media production', 'full audiovisual acceptance',
                            'actual-PC/VPN/VPS acceptance', '24-hour soak acceptance',
                            'unattended production readiness'],
    }
    evidence['artifacts'] = {
        path.relative_to(root).as_posix(): digest(path)
        for path in sorted(root.rglob('*'))
        if path.is_file() and path.name != 'evidence.json'
    }
    write_json(root / 'evidence.json', evidence)
    from integrations.local_queue.verify_retry_evidence import verify
    result = verify(root)
    print(json.dumps(result, indent=2))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hold-lock', action='store_true')
    parser.add_argument('--receipt'); parser.add_argument('--release')
    parser.add_argument('--hold-timeout', type=int, default=30)
    parser.add_argument('--output'); parser.add_argument('--content-control-root')
    parser.add_argument('--local-python', default=sys.executable)
    parser.add_argument('--source-commit'); parser.add_argument('--source-manifest-sha256')
    args = parser.parse_args(argv)
    if args.hold_lock:
        if not args.receipt or not args.release or not 1 <= args.hold_timeout <= 60:
            parser.error('Bounded holder receipt, release and timeout are required')
        return hold_lock(args.receipt, args.release, args.hold_timeout)
    required = (args.output, args.content_control_root, args.source_commit, args.source_manifest_sha256)
    if not all(required): parser.error('Output, source checkout, commit and manifest are required')
    create_packet(args.output, args.content_control_root, args.local_python,
                  args.source_commit, args.source_manifest_sha256)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
