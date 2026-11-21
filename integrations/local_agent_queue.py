"""Durable foreground queue for the existing bounded local text adapters.

SQLite receipts are authoritative. A crashed RUNNING attempt is INTERRUPTED,
never silently replayed: local inference may have finished before its receipt.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

MAX_JSON = 4 * 1024 * 1024


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
    if not isinstance(request, dict) or len(canonical(spec).encode()) > 150000:
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
    else:
        raise ValueError('Only existing OpenClaw and Ruflo local text adapters are supported')
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
        validate(spec)
        payload = canonical(spec)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.transaction():
            existing = self.db.execute('SELECT digest FROM jobs WHERE id=?', (spec['id'],)).fetchone()
            if existing:
                if existing['digest'] != digest:
                    raise ValueError('Job ID already exists with a different immutable payload')
                return self.get(spec['id'])
            now = time.time()
            self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',
                            (spec['id'], digest, payload, 'queued', 0, spec['max_attempts'], now, now))
        return self.get(spec['id'])

    def get(self, job_id):
        row = self.db.execute('SELECT id,digest,state,attempts,max_attempts,created,updated FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown job ID')
        result = dict(row)
        result['receipts'] = [dict(r) for r in self.db.execute(
            'SELECT number,state,started,finished,receipt FROM attempts WHERE job_id=? ORDER BY number', (job_id,))]
        for attempt in result['receipts']:
            attempt['receipt'] = json.loads(attempt['receipt']) if attempt['receipt'] else None
        return result

    def recover(self):
        self._require_owner()
        now = time.time()
        receipt = canonical({'status': 'INTERRUPTED', 'reason': 'Consumer stopped before durable completion; inference outcome is unknown. Review raw attempt artifacts before explicit retry.', 'publication_enabled': False, 'paid_generation_enabled': False, 'production_ready': False})
        with self.transaction():
            ids = [r[0] for r in self.db.execute("SELECT id FROM jobs WHERE state='running'")]
            self.db.execute("UPDATE attempts SET state='interrupted',finished=?,receipt=? WHERE state='running'", (now, receipt))
            self.db.execute("UPDATE jobs SET state='interrupted',updated=? WHERE state='running'", (now,))
        return ids

    def claim(self):
        self._require_owner()
        with self.transaction():
            row = self.db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created,id LIMIT 1").fetchone()
            if row is None:
                return None
            number = row['attempts'] + 1
            if number > row['max_attempts']:
                raise RuntimeError('Attempt limit invariant violated')
            now = time.time()
            self.db.execute("UPDATE jobs SET state='running',attempts=?,updated=? WHERE id=?", (number, now, row['id']))
            self.db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?)', (row['id'], number, 'running', now, None, None))
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


def execute_adapter(queue, attempt, *, ruflo_runtime=None, openclaw_runtime=None):
    spec = attempt['spec']
    validate(spec)  # Revalidate persisted input immediately before execution.
    directory = queue.root / 'attempts' / attempt['id'] / str(attempt['number'])
    directory.mkdir(parents=True, mode=0o700)  # Never reuse or overwrite an attempt.
    request = spec['request']
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


def work(queue, *, max_jobs=1, watch_seconds=0, executor=None, **runtimes):
    if type(max_jobs) is not int or not 1 <= max_jobs <= 1000 or type(watch_seconds) is not int or not 0 <= watch_seconds <= 86400:
        raise ValueError('Bound work to 1..1000 jobs and 0..86400 foreground watch seconds')
    processed = []
    deadline = time.monotonic() + watch_seconds
    with queue.consumer():
        recovered = queue.recover()
        while len(processed) < max_jobs:
            attempt = queue.claim()
            if attempt is None:
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(1, max(0, deadline - time.monotonic())))
                continue
            try:
                receipt = executor(attempt) if executor else execute_adapter(queue, attempt, **runtimes)
                queue.finish(attempt, receipt)
            except Exception as exc:
                # Do not persist potentially sensitive exception strings or overwrite raw adapter artifacts.
                queue.finish(attempt, {'status': 'ERROR', 'reason': 'Adapter failed before durable completion', 'exception_type': type(exc).__name__, 'publication_enabled': False, 'paid_generation_enabled': False, 'production_ready': False})
            processed.append(queue.get(attempt['id']))
    return {'processed': processed, 'recovered_interrupted_ids': recovered,
            'publication_enabled': False, 'paid_generation_enabled': False, 'production_ready': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    enqueue = commands.add_parser('enqueue'); enqueue.add_argument('file')
    status = commands.add_parser('status'); status.add_argument('--id')
    retry = commands.add_parser('retry'); retry.add_argument('id')
    run = commands.add_parser('work')
    run.add_argument('--max-jobs', type=int, default=1)
    run.add_argument('--watch-seconds', type=int, default=0)
    run.add_argument('--ruflo-runtime'); run.add_argument('--openclaw-runtime')
    args = parser.parse_args(argv)
    queue = Queue(args.queue)
    try:
        if args.command == 'enqueue':
            with open(args.file, 'rb') as handle:
                raw = handle.read(150001)
            if len(raw) > 150000:
                raise ValueError('Oversized job file')
            report = queue.enqueue(json.loads(raw))
        elif args.command == 'retry':
            report = queue.retry(args.id)
        elif args.command == 'status':
            report = queue.get(args.id) if args.id else [dict(r) for r in queue.db.execute('SELECT id,state,attempts,max_attempts FROM jobs ORDER BY created,id')]
        else:
            report = work(queue, max_jobs=args.max_jobs, watch_seconds=args.watch_seconds,
                          ruflo_runtime=args.ruflo_runtime, openclaw_runtime=args.openclaw_runtime)
        print(json.dumps(report, indent=2))
        if args.command == 'work':
            return 2 if report['recovered_interrupted_ids'] or any(job['state'] != 'succeeded' for job in report['processed']) else 0
        return 0
    finally:
        queue.close()


if __name__ == '__main__':
    raise SystemExit(main())
