"""Read-only verification for a closed real-adapter automatic-retry packet."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Missing or unsafe evidence artifact')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('Evidence artifact must be a JSON object')
    return value


def _false_flags(value):
    return (value.get('publication_enabled') is False
            and value.get('paid_generation_enabled') is False)


def verify(root):
    supplied_root = Path(root)
    if supplied_root.is_symlink():
        raise ValueError('Evidence root must be a real directory')
    root = supplied_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Evidence root must be a real directory')
    evidence = read_json(root / 'evidence.json')
    if evidence.get('schema_version') != 2 or not _false_flags(evidence):
        raise ValueError('Unsupported or unsafe evidence manifest')

    artifacts = evidence.get('artifacts')
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError('Artifact hash manifest is required')
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink evidence artifacts are forbidden')
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if relative != 'evidence.json':
                actual.add(relative)
    if actual != set(artifacts):
        raise ValueError('Evidence artifact set differs from manifest')
    for relative, expected in artifacts.items():
        if (not isinstance(relative, str) or relative.startswith('/') or '..' in Path(relative).parts
                or not isinstance(expected, str) or len(expected) != 64
                or digest(root / relative) != expected):
            raise ValueError('Evidence artifact hash mismatch')

    job = read_json(root / 'job.json')
    job_digest = hashlib.sha256(canonical(job).encode()).hexdigest()
    if job_digest != evidence.get('job_digest') or not _false_flags(job):
        raise ValueError('Immutable job identity or safety flags mismatch')
    if (job.get('adapter') != 'content-control-video' or job.get('max_attempts') != 2
            or job.get('request', {}).get('timeout_seconds') != 120
            or not _false_flags(job['request'])):
        raise ValueError('Job limits differ from the reviewed scenario')

    database = root / 'runtime/queue.sqlite3'
    before = digest(database)
    uri = 'file:' + quote(str(database.resolve()), safe='/') + '?mode=ro&immutable=1'
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        if connection.execute('PRAGMA query_only').fetchone()[0] != 1:
            raise ValueError('SQLite connection is not query-only')
        jobs = connection.execute('SELECT * FROM jobs').fetchall()
        attempts = connection.execute('SELECT * FROM attempts ORDER BY job_id,number').fetchall()
        retries = connection.execute('SELECT * FROM automatic_retry_events ORDER BY job_id,from_attempt').fetchall()
        runs = connection.execute('SELECT * FROM worker_runs ORDER BY started,id').fetchall()
    finally:
        connection.close()
    if digest(database) != before or before != artifacts['runtime/queue.sqlite3']:
        raise ValueError('Read-only verification changed the queue database')
    if len(jobs) != 1 or len(attempts) != 2 or len(retries) != 1 or len(runs) != 2:
        raise ValueError('Unexpected durable queue row counts')
    queued = jobs[0]
    if (queued['id'] != job['id'] or queued['digest'] != job_digest
            or json.loads(queued['spec']) != job or queued['state'] != 'blocked'
            or queued['attempts'] != 2 or queued['max_attempts'] != 2):
        raise ValueError('Durable job row does not match the immutable job')

    attempt_manifest = evidence.get('attempts')
    if not isinstance(attempt_manifest, list) or len(attempt_manifest) != 2:
        raise ValueError('Two attempt records are required')
    for row, expected in zip(attempts, attempt_manifest, strict=True):
        receipt_path = root / expected['receipt']
        receipt = read_json(receipt_path)
        if (row['job_id'] != job['id'] or row['number'] != expected['number']
                or row['state'] != 'blocked' or row['finished'] is None
                or json.loads(row['receipt']) != receipt
                or row['started'] != expected['started_epoch']
                or row['finished'] != expected['finished_epoch']
                or not _false_flags(receipt) or receipt.get('status') != 'BLOCKED'):
            raise ValueError('Attempt row, receipt or safety flags mismatch')
    first_receipt = read_json(root / attempt_manifest[0]['receipt'])
    second_receipt = read_json(root / attempt_manifest[1]['receipt'])
    if (attempt_manifest[0].get('retryable') is not True
            or first_receipt.get('retryable') is not True
            or first_receipt.get('blocker') != 'AdmissionBusy'):
        raise ValueError('First attempt did not explicitly authorize retry')
    runtime = second_receipt.get('runtime_prerequisites', {})
    expected_checks = {'cached_asr': False, 'caption_font': True, 'ffmpeg': True,
                       'node': True, 'npm_packages': True, 'picture_python': False,
                       'transcription_python': False}
    if (attempt_manifest[1].get('retryable') is not False or 'retryable' in second_receipt
            or second_receipt.get('blocker') != 'Video runtime prerequisites are blocked'
            or runtime.get('status') != 'BLOCKED' or runtime.get('checks') != expected_checks
            or runtime.get('blockers') != ['transcription_python', 'picture_python', 'cached_asr']):
        raise ValueError('Second blocker must not authorize another retry')

    retry = retries[0]
    expected_retry = evidence.get('automatic_retry')
    if (retry['job_id'] != job['id'] or retry['from_attempt'] != 1
            or retry['reason'] != 'adapter_marked_retryable'
            or retry['created'] != expected_retry.get('created_epoch')):
        raise ValueError('Automatic-retry event mismatch')

    launcher = read_json(root / 'process/launcher.json')
    holder = read_json(root / 'process/lock-holder.json')
    workers = [read_json(root / f'process/worker-{number}.json') for number in (1, 2)]
    if (launcher.get('pid') == holder.get('pid') or holder.get('parent_pid') != launcher.get('pid')
            or holder.get('acquired') is not True
            or holder.get('released') is not True
            or not all(_false_flags(value) for value in (launcher, holder, *workers))):
        raise ValueError('Separate acquired lock-holder process is not evidenced')
    identity = holder.get('lock_identity')
    if not isinstance(identity, dict):
        raise ValueError('Lock identity is missing')
    identity_fields = {key: identity[key] for key in ('device', 'inode', 'mode', 'size')}
    if hashlib.sha256(canonical(identity_fields).encode()).hexdigest() != identity.get('identity_sha256'):
        raise ValueError('Lock identity hash mismatch')
    if (identity.get('content_sha256') != hashlib.sha256(b'0').hexdigest()
            or not isinstance(identity.get('path_sha256'), str)
            or len(identity['path_sha256']) != 64):
        raise ValueError('Unexpected admission-lock bytes')

    run_ids = []
    expected_command = ['python', '-m', 'integrations.local_agent_queue', '--queue',
                        '$EVIDENCE_ROOT/runtime', 'work', '--max-jobs', '1',
                        '--watch-seconds', '0', '--poll-seconds', '1', '--auto-retry',
                        '--content-control-root', '$CONTENT_CONTROL_ROOT',
                        '--video-python', '$LOCAL_PYTHON', '--picture-python', '$LOCAL_PYTHON']
    for number, (worker, run) in enumerate(zip(workers, runs, strict=True), 1):
        stdout = read_json(root / worker['stdout'])
        config = json.loads(run['config'])
        if (worker.get('run_number') != number or worker.get('parent_pid') != launcher.get('pid')
                or worker.get('pid') in (launcher.get('pid'), holder.get('pid'))
                or worker.get('exit_code') != 2 or worker.get('stdout_sha256') != digest(root / worker['stdout'])
                or worker.get('sanitized_command') != expected_command
                or worker.get('sanitized_command_sha256') != hashlib.sha256(canonical(expected_command).encode()).hexdigest()
                or not isinstance(worker.get('actual_command_sha256'), str)
                or len(worker['actual_command_sha256']) != 64
                or worker.get('bounded_parameters') != {'auto_retry': True, 'max_jobs': 1,
                                                         'poll_seconds': 1, 'watch_seconds': 0,
                                                         'request_timeout_seconds': 120}
                or config != {'auto_retry': True, 'max_jobs': 1, 'poll_seconds': 1, 'watch_seconds': 0}
                or stdout.get('publication_enabled') is not False
                or stdout.get('paid_generation_enabled') is not False
                or stdout.get('production_ready') is not False
                or stdout.get('processed', [{}])[0].get('state') != 'blocked'
                or stdout.get('worker', {}).get('id') != run['id']
                or run['processed'] != 1 or run['state'] != 'finished' or run['exit_reason'] != 'job_limit'):
            raise ValueError('Worker command, exit, limits or durable run mismatch')
        run_ids.append(run['id'])
    if workers[0]['pid'] == workers[1]['pid'] or launcher.get('worker_pids') != [w['pid'] for w in workers]:
        raise ValueError('Worker process identities are not distinct and bound')
    if launcher.get('worker_run_ids') != run_ids or launcher.get('lock_holder_pid') != holder.get('pid'):
        raise ValueError('Launcher child-process bindings mismatch')
    if not (launcher['started_epoch'] <= holder['acquired_epoch'] <= attempts[0]['started']
            <= attempts[0]['finished'] <= retry['created'] <= holder['released_epoch']
            <= attempts[1]['started'] <= attempts[1]['finished'] <= launcher['finished_epoch']):
        raise ValueError('Process, attempt and retry event ordering mismatch')
    if not (workers[0]['started_epoch'] <= attempts[0]['started'] <= attempts[0]['finished']
            <= workers[0]['finished_epoch'] <= holder['released_epoch']
            and workers[1]['started_epoch'] <= attempts[1]['started'] <= attempts[1]['finished']
            <= workers[1]['finished_epoch'] <= launcher['finished_epoch']):
        raise ValueError('Worker process and durable attempt ordering mismatch')
    if workers[0]['automatic_retry_queued'] is not True or workers[1]['automatic_retry_queued'] is not False:
        raise ValueError('Worker retry decisions mismatch')
    if evidence.get('limits') != {'automatic_retry_events': 1, 'attempts_used': 2,
                                  'job_max_attempts': 2, 'request_timeout_seconds': 120,
                                  'worker_max_jobs': 1, 'worker_process_exit': 2}:
        raise ValueError('Evidence limits mismatch')
    return {'status': 'PASS', 'job_id': job['id'], 'attempts': 2,
            'automatic_retry_events': 1, 'worker_process_exits': [2, 2],
            'publication_enabled': False, 'paid_generation_enabled': False,
            'production_ready': False,
            'scope': 'Bounded local queue retry evidence only; not media, host or soak acceptance'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence_root')
    args = parser.parse_args(argv)
    print(json.dumps(verify(args.evidence_root), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
