"""Read-only operational alert snapshot for the bounded local agent queue.

This monitor never starts, retries, stops, deploys, or publishes work.  It
exposes durable queue failures and missing/stale consumers so an external
operator can deliver alerts without parsing prompts or adapter receipts.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3


REQUIRED_TABLES = {'jobs', 'attempts', 'worker_runs', 'automatic_retry_events'}
TERMINAL_ALERT_STATES = {'blocked', 'failed', 'interrupted'}
RESOURCE_FIELDS = (
    'timeout_seconds', 'workers', 'max_tokens', 'worker_memory_mb',
    'shared_model_memory_mb', 'render_memory_mb', 'render_cpu',
)
JOB_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')
RUN_ID = re.compile(r'[0-9a-f]{32}')
WORKER_CONFIG_FIELDS = {'max_jobs', 'watch_seconds', 'poll_seconds', 'auto_retry'}
NORMAL_EXIT_REASONS = {'job_limit', 'watch_deadline', 'drained', 'stop_requested'}


def _file_sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _database_identity(root):
    """Bind the main database and any WAL bytes used by a read snapshot."""
    database = root / 'queue.sqlite3'
    files = {}
    for path in (database, Path(str(database) + '-wal')):
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError('Queue database storage must use regular files')
        files[path.name] = {'size': path.stat().st_size, 'sha256': _file_sha256(path)}
    if database.name not in files:
        raise ValueError('Existing nonsymlink queue database required')
    encoded = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    return {'files': files, 'sha256': hashlib.sha256(encoded).hexdigest()}


def _consumer_lock_held(root):
    if os.name != 'posix':
        return None
    import fcntl
    path = root / 'consumer.lock'
    if not path.exists():
        return False
    if path.is_symlink() or not path.is_file():
        raise ValueError('Queue consumer lock must be a regular file')
    descriptor = os.open(path, os.O_RDONLY)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True
    finally:
        os.close(descriptor)


def _safe_spec(row):
    try:
        spec = json.loads(row['spec'])
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError('Stored queue job specification is invalid') from error
    if (not isinstance(row['id'], str) or JOB_ID.fullmatch(row['id']) is None
            or not isinstance(spec, dict)
            or set(spec) != {'id', 'adapter', 'request', 'max_attempts',
                             'publication_enabled', 'paid_generation_enabled'}
            or spec.get('id') != row['id']
            or spec.get('adapter') not in {
                'openclaw', 'ruflo', 'content-control-cycle', 'content-control-video'
            }
            or not isinstance(spec.get('request'), dict)
            or spec.get('max_attempts') != row['max_attempts']
            or spec.get('publication_enabled') is not False
            or spec.get('paid_generation_enabled') is not False):
        raise ValueError('Stored queue job envelope is inconsistent')
    limits = {'max_attempts': row['max_attempts']}
    for name in RESOURCE_FIELDS:
        value = spec['request'].get(name)
        if value is not None:
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError('Stored queue resource limit is invalid')
            limits[name] = value
    return spec['adapter'], limits


def _worker_config(value):
    try:
        config = json.loads(value)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError('Stored worker run configuration is invalid') from error
    if (not isinstance(config, dict) or set(config) != WORKER_CONFIG_FIELDS
            or type(config['max_jobs']) is not int or not 1 <= config['max_jobs'] <= 1000
            or type(config['watch_seconds']) is not int
            or not 0 <= config['watch_seconds'] <= 86400
            or type(config['poll_seconds']) not in (int, float)
            or not math.isfinite(config['poll_seconds'])
            or not .2 <= config['poll_seconds'] <= 60
            or type(config['auto_retry']) is not bool):
        raise ValueError('Stored worker run configuration is invalid')
    return config


def _validate_run(run, known_job_ids):
    if not isinstance(run['id'], str) or RUN_ID.fullmatch(run['id']) is None:
        raise ValueError('Stored worker run identifier is invalid')
    config = _worker_config(run['config'])
    state = run['state']
    finished = run['finished']
    reason = run['exit_reason']
    active_job = run['active_job']
    if (state not in {'watching', 'executing', 'finished', 'interrupted', 'error'}
            or type(run['processed']) is not int or run['processed'] < 0
            or type(run['started']) not in (int, float)
            or type(run['heartbeat']) not in (int, float)
            or not math.isfinite(run['started']) or not math.isfinite(run['heartbeat'])
            or run['heartbeat'] < run['started']
            or (finished is not None
                and (type(finished) not in (int, float) or not math.isfinite(finished)
                     or finished < run['heartbeat']))
            or (active_job is not None
                and (not isinstance(active_job, str) or active_job not in known_job_ids))
            or (run['stop_requested'] is not None
                and (type(run['stop_requested']) not in (int, float)
                     or not math.isfinite(run['stop_requested'])
                     or run['stop_requested'] < run['started']
                     or (finished is not None and run['stop_requested'] > finished)))):
        raise ValueError('Stored worker run state is invalid')
    if state in {'watching', 'executing'}:
        if finished is not None or reason is not None:
            raise ValueError('Active worker run has terminal fields')
        if (state == 'watching' and active_job is not None) or (state == 'executing' and active_job is None):
            raise ValueError('Active worker run job binding is inconsistent')
    else:
        if finished is None:
            raise ValueError('Terminal worker run lacks a finish timestamp')
        allowed = (NORMAL_EXIT_REASONS if state == 'finished'
                   else {'interrupted', 'consumer_lost'} if state == 'interrupted'
                   else {'error'})
        if reason not in allowed:
            raise ValueError('Terminal worker run exit reason is inconsistent')
        if state in {'finished', 'error'} and active_job is not None:
            raise ValueError('Terminal worker run retains an active job')
    return config


def _alert(code, severity, **details):
    return {'code': code, 'severity': severity, **details}


def inspect_queue(root, *, now=None):
    """Return one side-effect-free snapshot from an existing queue database."""
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Existing nonsymlink queue directory required')
    before_identity = _database_identity(root)
    database = root / 'queue.sqlite3'
    observed = datetime.now(timezone.utc) if now is None else now
    if not isinstance(observed, datetime) or observed.tzinfo is None:
        raise ValueError('Timezone-aware observation time required')
    timestamp = observed.timestamp()
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED_TABLES <= tables:
            raise ValueError('Queue database schema is incomplete')
        jobs = list(connection.execute(
            'SELECT id,state,attempts,max_attempts,spec FROM jobs ORDER BY created,id'))
        runs = list(connection.execute(
            'SELECT * FROM worker_runs ORDER BY started DESC,id DESC'))
        retry_events = connection.execute(
            'SELECT COUNT(*) FROM automatic_retry_events').fetchone()[0]
    finally:
        connection.close()
    lock_held = _consumer_lock_held(root)
    after_identity = _database_identity(root)
    if after_identity != before_identity:
        raise ValueError('Queue database changed while monitoring')
    alerts = []
    job_rows = []
    counts = {}
    for row in jobs:
        state = row['state']
        if state not in {'queued', 'running', 'succeeded', 'blocked', 'failed', 'interrupted'}:
            raise ValueError('Stored queue job state is invalid')
        if (type(row['attempts']) is not int or type(row['max_attempts']) is not int
                or not 0 <= row['attempts'] <= row['max_attempts'] <= 3):
            raise ValueError('Stored queue attempt counters are invalid')
        adapter, limits = _safe_spec(row)
        counts[state] = counts.get(state, 0) + 1
        job_rows.append({'id': row['id'], 'adapter': adapter, 'state': state,
                         'attempts': row['attempts'], 'resource_limits': limits})
        if state in TERMINAL_ALERT_STATES:
            alerts.append(_alert('job_' + state, 'error', job_id=row['id'],
                                 attempts=row['attempts'], max_attempts=row['max_attempts']))
        if state != 'succeeded' and row['attempts'] >= row['max_attempts']:
            alerts.append(_alert('attempt_limit_exhausted', 'error', job_id=row['id'],
                                 attempts=row['attempts'], max_attempts=row['max_attempts']))
        if state == 'running' and lock_held is False:
            alerts.append(_alert('running_job_without_consumer', 'critical', job_id=row['id']))

    known_job_ids = {row['id'] for row in jobs}
    run_configs = []
    for run in runs:
        run_configs.append(_validate_run(run, known_job_ids))
    unfinished = [run for run in runs if run['finished'] is None]
    if len(unfinished) > 1 or (unfinished and runs and unfinished[0]['id'] != runs[0]['id']):
        raise ValueError('Worker run history has inconsistent active ownership')

    run = runs[0] if runs else None
    run_report = None
    active = False
    if run is not None:
        config = run_configs[0]
        heartbeat_age = max(0.0, timestamp - run['heartbeat'])
        freshness_window = max(5.0, config['poll_seconds'] * 3)
        active = run['finished'] is None and lock_held is True
        heartbeat_fresh = active and heartbeat_age <= freshness_window
        run_report = {
            'id': run['id'], 'state': run['state'], 'active_job': run['active_job'],
            'processed': run['processed'], 'started': run['started'],
            'heartbeat': run['heartbeat'], 'finished': run['finished'],
            'exit_reason': run['exit_reason'], 'stop_requested': run['stop_requested'],
            'heartbeat_age_seconds': heartbeat_age,
            'heartbeat_fresh': heartbeat_fresh,
            'resource_limits': {
                key: config[key] for key in ('max_jobs', 'watch_seconds', 'poll_seconds', 'auto_retry')
                if key in config
            },
        }
        if run['finished'] is None and lock_held is False:
            alerts.append(_alert('worker_interrupted_unrecovered', 'critical', run_id=run['id']))
        elif active and not heartbeat_fresh:
            alerts.append(_alert('worker_heartbeat_stale', 'critical', run_id=run['id']))
        if run['stop_requested'] is not None and run['finished'] is None:
            alerts.append(_alert('stop_request_pending', 'warning', run_id=run['id']))

    failed_runs = [run for run in runs if run['state'] in {'error', 'interrupted'}]
    for state in ('error', 'interrupted'):
        retained = [run for run in failed_runs if run['state'] == state]
        if retained:
            alerts.append(_alert('retained_worker_' + state, 'error',
                                 count=len(retained), latest_run_id=retained[0]['id']))

    if counts.get('running', 0) and not active and lock_held is True:
        alerts.append(_alert('running_jobs_without_tracked_worker', 'critical',
                             running_jobs=counts['running']))

    if counts.get('queued', 0) and not active:
        alerts.append(_alert('queued_jobs_without_active_consumer', 'warning',
                             queued_jobs=counts['queued']))
    alerts.sort(key=lambda item: (item['severity'], item['code'], item.get('job_id', ''),
                                  item.get('run_id', '')))
    status = 'ATTENTION_REQUIRED' if alerts else ('IDLE' if not jobs else 'HEALTHY')
    return {
        'schema_version': 1,
        'status': status,
        'observed_at': observed.isoformat(),
        'queue_database_sha256': before_identity['files']['queue.sqlite3']['sha256'],
        'queue_storage_sha256': before_identity['sha256'],
        'queue_storage_files': before_identity['files'],
        'consumer_lock_held': lock_held,
        'worker_run': run_report,
        'job_counts': counts,
        'jobs': job_rows,
        'automatic_retry_events': retry_events,
        'alerts': alerts,
        'alert_delivery_configured': False,
        'deployed_monitor_verified': False,
        'twenty_four_hour_soak_verified': False,
        'scope': ('Read-only local queue state, attempt ceilings, and foreground liveness only; '
                  'no model quality, VPN, audiovisual, deployed alert delivery, or 24-hour acceptance.'),
        'publication_enabled': False,
        'paid_generation_enabled': False,
        'production_ready': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue', required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect_queue(args.queue)
    except (OSError, ValueError, sqlite3.Error) as error:
        result = {
            'schema_version': 1, 'status': 'BLOCKED',
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'blocker': str(error) if isinstance(error, ValueError) else type(error).__name__,
            'alerts': [_alert('monitor_blocked', 'critical')],
            'alert_delivery_configured': False, 'deployed_monitor_verified': False,
            'twenty_four_hour_soak_verified': False,
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_ready': False,
        }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 2 if result['status'] in {'ATTENTION_REQUIRED', 'BLOCKED'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
