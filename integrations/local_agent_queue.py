"""Durable foreground queue for bounded local text and unpublished video adapters.

SQLite receipts are authoritative. A crashed RUNNING attempt is INTERRUPTED,
never silently replayed: adapter execution may have finished before its receipt.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import threading
import uuid

MAX_JSON = 4 * 1024 * 1024
MAX_JOB_BYTES = 150000
MAX_BATCH_JOBS = 16


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def validate(spec):
    if not isinstance(spec, dict) or set(spec) != {'id', 'adapter', 'request', 'max_attempts', 'publication_enabled', 'paid_generation_enabled'}:
        raise ValueError('Require the exact documented queue envelope')
    if not isinstance(spec['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', spec['id']):
        raise ValueError('Invalid immutable job ID')
    if spec['publication_enabled'] is not False or spec['paid_generation_enabled'] is not False:
        raise ValueError('Publishing and paid generation must remain false')
    if type(spec['max_attempts']) is not int or not 1 <= spec['max_attempts'] <= 3:
        raise ValueError('Require one to three attempts')
    request = spec['request']
    if not isinstance(request, dict) or len(canonical(spec).encode()) > MAX_JOB_BYTES:
        raise ValueError('Invalid or oversized request')
    if spec['adapter'] == 'openclaw':
        from integrations.openclaw.worker import validate as validate_adapter
        if request.get('operation') != 'run-text' or 'output' in request:
            raise ValueError('Queue permits run-text only and owns receipt paths')
        validate_adapter(request)
    elif spec['adapter'] == 'ruflo':
        from integrations.ruflo.local_batch import validate as validate_adapter
        if set(request) != {'publication_enabled', 'endpoint', 'model', 'workers', 'max_tokens', 'timeout_seconds', 'worker_memory_mb', 'shared_model_memory_mb', 'render_memory_mb', 'render_cpu', 'tasks'}:
            raise ValueError('Unknown or missing Ruflo request fields')
        validate_adapter(request)
        if any(set(task) != {'id', 'prompt'} for task in request['tasks']):
            raise ValueError('Unknown Ruflo task options')
    elif spec['adapter'] == 'content-control-cycle':
        from integrations.content_control.cycle_job import validate as validate_adapter
        validate_adapter(request)
    elif spec['adapter'] == 'content-control-video':
        from integrations.content_control.video_job import validate as validate_adapter
        validate_adapter(request)
    else:
        raise ValueError('Only documented bounded local adapters are supported')
    return spec


class Queue:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError('Queue directory must be an operator-owned local directory')
        database = self.root / 'queue.sqlite3'
        if database.is_symlink():
            raise ValueError('Symlink database is forbidden')
        fd = os.open(database, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(database, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, digest TEXT NOT NULL, spec TEXT NOT NULL,
                state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_runs (
                id TEXT PRIMARY KEY, state TEXT NOT NULL, started REAL NOT NULL,
                heartbeat REAL NOT NULL, finished REAL, stop_requested REAL,
                active_job TEXT, processed INTEGER NOT NULL, config TEXT NOT NULL,
                exit_reason TEXT);
            CREATE TABLE IF NOT EXISTS attempts (
                job_id TEXT NOT NULL REFERENCES jobs(id), number INTEGER NOT NULL,
                state TEXT NOT NULL, started REAL NOT NULL, finished REAL,
                receipt TEXT, PRIMARY KEY(job_id, number));
        ''')

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    @contextmanager
    def consumer(self):
        if os.name != 'posix':
            raise RuntimeError('Queue execution requires POSIX ownership locks; use WSL2 on Windows')
        import fcntl
        lock = self.root / 'consumer.lock'
        if lock.is_symlink():
            raise ValueError('Symlink lock is forbidden')
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('Another foreground consumer owns this queue') from exc
            self._owned = True
            yield
        finally:
            self._owned = False
            os.close(fd)

    def _require_owner(self):
        if not getattr(self, '_owned', False):
            raise RuntimeError('Recovery, claim and completion require consumer ownership')

    def enqueue(self, spec):
        self.enqueue_batch([spec])
        return self.get(spec['id'])

    def enqueue_batch(self, specs):
        if not isinstance(specs, list) or not 1 <= len(specs) <= MAX_BATCH_JOBS:
            raise ValueError(f'Require a list of one to {MAX_BATCH_JOBS} job envelopes')
        entries = {}
        for spec in specs:
            validate(spec)
            job_id = spec['id']
            if job_id in entries:
                raise ValueError('Duplicate job ID in batch')
            payload = canonical(spec)
            entries[job_id] = (spec, payload, hashlib.sha256(payload.encode()).hexdigest())
        with self.transaction():
            for job_id, (spec, payload, digest) in entries.items():
                existing = self.db.execute('SELECT digest FROM jobs WHERE id=?', (job_id,)).fetchone()
                if existing:
                    if existing['digest'] != digest:
                        raise ValueError('Job ID already exists with a different immutable payload')
                    continue
                if spec['adapter'] == 'content-control-cycle':
                    from integrations.content_control.cycle_editorial import compile_editorial
                    compile_editorial(spec['request']['brief'], validate_visual_shapes=True)
                now = time.time()
                self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',
                                (job_id, digest, payload, 'queued', 0, spec['max_attempts'], now, now))
            return [self.get(job_id, include_receipts=False) for job_id in entries]

    def get(self, job_id, *, include_receipts=True):
        row = self.db.execute('SELECT id,digest,state,attempts,max_attempts,created,updated FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown job ID')
        result = dict(row)
        if not include_receipts:
            return result
        result['receipts'] = [dict(r) for r in self.db.execute(
            'SELECT number,state,started,finished,receipt FROM attempts WHERE job_id=? ORDER BY number', (job_id,))]
        for attempt in result['receipts']:
            attempt['receipt'] = json.loads(attempt['receipt']) if attempt['receipt'] else None
        return result

    def recover(self):
        self._require_owner()
        now = time.time()
        receipt = canonical({'status': 'INTERRUPTED', 'reason': 'Consumer stopped before durable completion; adapter outcome is unknown. Review raw attempt artifacts before explicit retry.', 'publication_enabled': False, 'paid_generation_enabled': False, 'production_ready': False})
        with self.transaction():
            ids = [r[0] for r in self.db.execute("SELECT id FROM jobs WHERE state='running'")]
            self.db.execute("UPDATE attempts SET state='interrupted',finished=?,receipt=? WHERE state='running'", (now, receipt))
            self.db.execute("UPDATE jobs SET state='interrupted',updated=? WHERE state='running'", (now,))
        return ids

    def claim(self, run_id=None, deadline=None):
        self._require_owner()
        with self.transaction():
            if deadline is not None and time.monotonic() >= deadline:
                return None
            if run_id is not None:
                run = self.db.execute('SELECT stop_requested FROM worker_runs WHERE id=? AND finished IS NULL', (run_id,)).fetchone()
                if run is None or run['stop_requested'] is not None:
                    return None
            row = self.db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created,id LIMIT 1").fetchone()
            if row is None:
                return None
            number = row['attempts'] + 1
            if number > row['max_attempts']:
                raise RuntimeError('Attempt limit invariant violated')
            now = time.time()
            self.db.execute("UPDATE jobs SET state='running',attempts=?,updated=? WHERE id=?", (number, now, row['id']))
            self.db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?)', (row['id'], number, 'running', now, None, None))
            if run_id is not None:
                self.db.execute("UPDATE worker_runs SET state='executing',active_job=?,heartbeat=? WHERE id=?", (row['id'], now, run_id))
        return {'id': row['id'], 'number': number, 'spec': json.loads(row['spec'])}

    def finish(self, attempt, receipt):
        self._require_owner()
        if not isinstance(receipt, dict):
            raise ValueError('Adapter receipt must be an object')
        if receipt.get('publication_enabled', False) is not False or receipt.get('paid_generation_enabled', False) is not False:
            raise ValueError('Adapter receipt contradicts disabled publishing or paid generation')
        payload = canonical(receipt)
        if len(payload.encode()) > MAX_JSON:
            raise ValueError('Receipt exceeds durable storage limit')
        state = {'PASS': 'succeeded', 'BLOCKED': 'blocked'}.get(receipt.get('status'), 'failed')
        now = time.time()
        with self.transaction():
            row = self.db.execute('SELECT state,attempts FROM jobs WHERE id=?', (attempt['id'],)).fetchone()
            if not row or row['state'] != 'running' or row['attempts'] != attempt['number']:
                raise ValueError('Attempt is no longer the active claim')
            self.db.execute('UPDATE attempts SET state=?,finished=?,receipt=? WHERE job_id=? AND number=?', (state, now, payload, attempt['id'], attempt['number']))
            self.db.execute('UPDATE jobs SET state=?,updated=? WHERE id=?', (state, now, attempt['id']))

    def retry(self, job_id):
        with self.transaction():
            row = self.db.execute('SELECT state,attempts,max_attempts FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row or row['state'] not in ('blocked', 'failed', 'interrupted'):
                raise ValueError('Only a completed blocked/failed or reviewed interrupted job can be retried')
            if row['attempts'] >= row['max_attempts']:
                raise ValueError('Attempt limit reached; previous receipts are retained')
            self.db.execute("UPDATE jobs SET state='queued',updated=? WHERE id=?", (time.time(), job_id))
        return self.get(job_id)


    def start_run(self, config):
        self._require_owner()
        now = time.time()
        run_id = uuid.uuid4().hex
        with self.transaction():
            # Owning the OS consumer lock proves these earlier runs have ended.
            self.db.execute("UPDATE worker_runs SET state='interrupted',finished=?,exit_reason='consumer_lost' WHERE finished IS NULL", (now,))
            self.db.execute('INSERT INTO worker_runs VALUES (?,?,?,?,?,?,?,?,?,?)',
                (run_id, 'watching', now, now, None, None, None, 0, canonical(config), None))
        return run_id

    def update_run(self, run_id, *, processed, finished=False, reason=None):
        self._require_owner()
        now = time.time()
        state = 'finished' if finished else 'watching'
        if finished and reason in ('interrupted', 'error'):
            state = reason
        self.db.execute('UPDATE worker_runs SET state=?,heartbeat=?,finished=?,active_job=NULL,processed=?,exit_reason=? WHERE id=?',
                        (state, now, now if finished else None, processed, reason, run_id))

    def request_stop(self, run_id=None):
        with self.transaction():
            row = self.db.execute('SELECT id FROM worker_runs WHERE finished IS NULL ORDER BY started DESC LIMIT 1').fetchone()
            if row is None or (run_id is not None and row['id'] != run_id):
                return {'status': 'NO_ACTIVE_MATCH', 'run_id': run_id, 'stopped': False}
            target = row['id']
            self.db.execute('UPDATE worker_runs SET stop_requested=COALESCE(stop_requested,?) WHERE id=?', (time.time(), target))
        return {'status': 'STOP_REQUESTED', 'run_id': target, 'stopped': False,
                'scope': 'Finish the current bounded attempt; do not claim another job'}

    def stop_requested(self, run_id):
        row = self.db.execute('SELECT stop_requested FROM worker_runs WHERE id=?', (run_id,)).fetchone()
        return row is not None and row['stop_requested'] is not None

    def consumer_lock_held(self):
        if os.name != 'posix':
            return None
        if getattr(self, '_owned', False):
            return True
        import fcntl
        path = self.root / 'consumer.lock'
        if not path.exists():
            return False
        if path.is_symlink():
            raise ValueError('Symlink consumer lock is forbidden')
        fd = os.open(path, os.O_RDWR)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return False
            except BlockingIOError:
                return True
        finally:
            os.close(fd)

    def health(self, run_id=None):
        row = self.db.execute('SELECT * FROM worker_runs WHERE id=?', (run_id,)).fetchone() if run_id else self.db.execute('SELECT * FROM worker_runs ORDER BY started DESC LIMIT 1').fetchone()
        run = dict(row) if row else None
        held = self.consumer_lock_held()
        if run:
            run['config'] = json.loads(run['config'])
            run['heartbeat_age_seconds'] = max(0, time.time() - run['heartbeat'])
            run['heartbeat_fresh'] = run['finished'] is None and run['heartbeat_age_seconds'] <= max(5, run['config']['poll_seconds'] * 3)
            run['observed_state'] = 'interrupted_unrecovered' if run['finished'] is None and held is False else run['state']
        return {'run': run, 'consumer_lock_held': held,
                'job_counts': {r['state']: r['n'] for r in self.db.execute('SELECT state,COUNT(*) n FROM jobs GROUP BY state')},
                'scope': 'Foreground process liveness and queue state only; not model, VPN, video quality, or production health',
                'publication_enabled': False, 'paid_generation_enabled': False, 'production_ready': False}


class RunHeartbeat:
    """Independent bounded-rate pulse while an adapter blocks the main thread."""
    def __init__(self, queue, run_id, interval):
        self.database = queue.root / 'queue.sqlite3'
        self.run_id, self.interval = run_id, interval
        self.stop = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.pulse, daemon=True)

    def pulse(self):
        db = None
        try:
            db = sqlite3.connect(self.database, timeout=1, isolation_level=None)
            db.execute('PRAGMA synchronous=FULL')
            while not self.stop.wait(self.interval):
                db.execute('UPDATE worker_runs SET heartbeat=? WHERE id=? AND finished IS NULL', (time.time(), self.run_id))
        except Exception as exc:
            self.error = type(exc).__name__
        finally:
            if db is not None:
                db.close()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=2)


def execute_adapter(queue, attempt, *, ruflo_runtime=None, openclaw_runtime=None, content_control_root=None, video_python=None, picture_python=None, cycle_voice_python=None, cycle_voice_root=None, cycle_transcription_python=None):
    spec = attempt['spec']
    validate(spec)  # Revalidate persisted input immediately before execution.
    directory = queue.root / 'attempts' / attempt['id'] / str(attempt['number'])
    directory.mkdir(parents=True, mode=0o700)  # Never reuse or overwrite an attempt.
    request = spec['request']
    if spec['adapter'] == 'content-control-cycle':
        from integrations.content_control.cycle_job import run_job
        return run_job(request, directory, voice_python=cycle_voice_python, voice_root=cycle_voice_root,
                       transcription_python=cycle_transcription_python)
    if spec['adapter'] == 'content-control-video':
        from integrations.content_control.video_job import run_job
        return run_job(request, directory, content_control_root=content_control_root,
                       video_python=video_python, picture_python=picture_python)
    if spec['adapter'] == 'ruflo':
        if ruflo_runtime is None:
            return {'status': 'BLOCKED', 'reason': 'Explicit pinned Ruflo runtime path required', 'publication_enabled': False, 'paid_generation_enabled': False}
        from integrations.ruflo.local_batch import run_batch
        return run_batch(request, ruflo_runtime)
    # Existing module imports agent_capacity using its script-style path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from integrations.openclaw.worker import dispatch
    return dispatch({**request, 'output': str(directory / 'adapter-receipt.json')},
                    Path(openclaw_runtime) if openclaw_runtime else directory / 'runtime')


def work(queue, *, max_jobs=1, watch_seconds=0, poll_seconds=1, executor=None, **runtimes):
    if type(max_jobs) is not int or not 1 <= max_jobs <= 1000 or type(watch_seconds) is not int or not 0 <= watch_seconds <= 86400:
        raise ValueError('Bound work to 1..1000 jobs and 0..86400 foreground watch seconds')
    if type(poll_seconds) not in (int, float) or not math.isfinite(poll_seconds) or not .2 <= poll_seconds <= 60:
        raise ValueError('Polling interval must be finite, between .2 and 60 seconds')
    processed = []
    deadline = time.monotonic() + watch_seconds
    with queue.consumer():
        recovered = queue.recover()
        run_id = queue.start_run({'max_jobs': max_jobs, 'watch_seconds': watch_seconds, 'poll_seconds': poll_seconds})
        reason = 'job_limit'
        try:
            with RunHeartbeat(queue, run_id, poll_seconds) as heartbeat:
                while len(processed) < max_jobs:
                    if heartbeat.error:
                        raise RuntimeError('Worker heartbeat could not persist')
                    if queue.stop_requested(run_id):
                        reason = 'stop_requested'
                        break
                    if watch_seconds and time.monotonic() >= deadline:
                        reason = 'watch_deadline'
                        break
                    # Stop and claim are serialized in the same SQLite transaction.
                    attempt = queue.claim(run_id, deadline if watch_seconds else None)
                    if attempt is None:
                        if queue.stop_requested(run_id):
                            reason = 'stop_requested'
                            break
                        if not watch_seconds or time.monotonic() >= deadline:
                            reason = 'watch_deadline' if watch_seconds else 'drained'
                            break
                        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
                        continue
                    try:
                        receipt = executor(attempt) if executor else execute_adapter(queue, attempt, **runtimes)
                        queue.finish(attempt, receipt)
                    except Exception as exc:
                        queue.finish(attempt, {'status': 'ERROR', 'reason': 'Adapter failed before durable completion', 'exception_type': type(exc).__name__, 'publication_enabled': False, 'paid_generation_enabled': False, 'production_ready': False})
                    completed = queue.get(attempt['id'])
                    processed.append({key: completed[key] for key in ('id', 'state', 'attempts')})
                    queue.update_run(run_id, processed=len(processed))
        except BaseException as exc:
            reason = 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'error'
            raise
        finally:
            queue.update_run(run_id, processed=len(processed), finished=True, reason=reason)
    return {'processed': processed, 'recovered_interrupted_ids': recovered,
            'worker': queue.health(run_id)['run'],
            'publication_enabled': False, 'paid_generation_enabled': False, 'production_ready': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    enqueue = commands.add_parser('enqueue'); enqueue.add_argument('file')
    enqueue_batch = commands.add_parser('enqueue-batch')
    enqueue_batch.add_argument('file', help='JSON array of up to 16 validated job envelopes')
    status = commands.add_parser('status'); status.add_argument('--id')
    retry = commands.add_parser('retry'); retry.add_argument('id')
    commands.add_parser('health')
    stop = commands.add_parser('stop'); stop.add_argument('--run-id')
    run = commands.add_parser('work')
    run.add_argument('--max-jobs', type=int, default=1)
    run.add_argument('--watch-seconds', type=int, default=0)
    run.add_argument('--poll-seconds', type=float, default=1)
    run.add_argument('--ruflo-runtime'); run.add_argument('--openclaw-runtime')
    run.add_argument('--content-control-root'); run.add_argument('--video-python'); run.add_argument('--picture-python')
    run.add_argument('--cycle-voice-python'); run.add_argument('--cycle-voice-root'); run.add_argument('--cycle-transcription-python')
    args = parser.parse_args(argv)
    queue = Queue(args.queue)
    try:
        if args.command in ('enqueue', 'enqueue-batch'):
            batch = args.command == 'enqueue-batch'
            limit = MAX_JOB_BYTES * MAX_BATCH_JOBS + 4096 if batch else MAX_JOB_BYTES
            with open(args.file, 'rb') as handle:
                raw = handle.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('Oversized job file')
            request = json.loads(raw)
            report = queue.enqueue_batch(request) if batch else queue.enqueue(request)
        elif args.command == 'retry':
            report = queue.retry(args.id)
        elif args.command == 'health':
            report = queue.health()
        elif args.command == 'stop':
            report = queue.request_stop(args.run_id)
        elif args.command == 'status':
            report = queue.get(args.id) if args.id else [dict(r) for r in queue.db.execute('SELECT id,state,attempts,max_attempts FROM jobs ORDER BY created,id')]
        else:
            report = work(queue, max_jobs=args.max_jobs, watch_seconds=args.watch_seconds, poll_seconds=args.poll_seconds,
                          ruflo_runtime=args.ruflo_runtime, openclaw_runtime=args.openclaw_runtime,
                          content_control_root=args.content_control_root, video_python=args.video_python, picture_python=args.picture_python,
                          cycle_voice_python=args.cycle_voice_python, cycle_voice_root=args.cycle_voice_root,
                          cycle_transcription_python=args.cycle_transcription_python)
        print(json.dumps(report, indent=2))
        if args.command == 'work':
            return 2 if report['recovered_interrupted_ids'] or any(job['state'] != 'succeeded' for job in report['processed']) else 0
        return 0
    finally:
        queue.close()


if __name__ == '__main__':
    raise SystemExit(main())
