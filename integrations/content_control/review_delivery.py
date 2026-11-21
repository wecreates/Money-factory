"""Read-only delivery of a durably completed, unpublished queued video.

A video left behind by an interrupted attempt is never a deliverable. SQLite,
the adapter receipt, the producer receipt and every artifact must agree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from integrations.local_agent_queue import canonical, validate
from integrations.content_control.runtime_doctor import SOURCES
from integrations.content_control.video_job import check_completed, digest

MAX_JSON = 4 * 1024 * 1024
MAX_FILE = 512 * 1024 * 1024
MAX_PACKET = 1024 * 1024 * 1024


def regular(path, *, directory=False, limit=MAX_FILE):
    path = Path(path).absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('Symlinks are not permitted in queue delivery paths')
    if directory:
        if not path.is_dir():
            raise ValueError('Required queue directory is missing')
    elif not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Required delivery file is missing or oversized')
    return path


def parse_json(raw):
    if len(raw.encode('utf-8')) > MAX_JSON:
        raise ValueError('Oversized delivery metadata')
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate metadata key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite metadata')))
    if not isinstance(value, dict):
        raise ValueError('Delivery metadata must be an object')
    return value


def read_json(path):
    return parse_json(regular(path, limit=MAX_JSON).read_text())


def read_job(queue_root, job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', job_id):
        raise ValueError('Invalid immutable job ID')
    root = regular(queue_root, directory=True)
    database = regular(root / 'queue.sqlite3', limit=MAX_PACKET)
    # Unlike Queue(), this reader neither creates a missing DB nor migrates it.
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        job = connection.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if job is None:
            raise ValueError('Unknown job ID')
        job = dict(job)
        spec = parse_json(job['spec'])
        validate(spec)
        if (spec['id'] != job_id or spec['adapter'] != 'content-control-video'
                or hashlib.sha256(canonical(spec).encode()).hexdigest() != job['digest']
                or spec['max_attempts'] != job['max_attempts']):
            raise ValueError('Immutable video request identity mismatch')
        attempts = [dict(row) for row in connection.execute(
            'SELECT * FROM attempts WHERE job_id=? ORDER BY number', (job_id,))]
        if (len(attempts) != job['attempts'] or job['attempts'] > job['max_attempts']
                or [row['number'] for row in attempts] != list(range(1, job['attempts'] + 1))):
            raise ValueError('Attempt history is inconsistent')
        return root, job, spec, attempts
    finally:
        connection.close()


def verify_delivery(queue_root, job_id):
    root, job, spec, attempts = read_job(queue_root, job_id)
    if job['state'] != 'succeeded' or not attempts or attempts[-1]['state'] != 'succeeded':
        raise ValueError('Only a durably succeeded video attempt can be delivered')
    latest = attempts[-1]
    if latest['finished'] is None or latest['receipt'] is None:
        raise ValueError('Completion receipt is missing')
    stored = parse_json(latest['receipt'])
    attempt = regular(root / 'attempts' / job_id / str(latest['number']), directory=True)
    adapter = read_json(attempt / 'video-adapter-receipt.json')
    if canonical(adapter) != canonical(stored):
        raise ValueError('Adapter receipt differs from durable completion')
    if (stored.get('status') != 'PASS' or stored.get('review_status') != 'AWAITING_REVIEW'
            or stored.get('artifact_directory') != 'review' or stored.get('source_inputs_unchanged') is not True
            or any(stored.get(flag) is not False for flag in ('publication_enabled', 'paid_generation_enabled',
                       'production_ready', 'production_approved', 'full_av_review'))
            or any(stored.get(key) != spec['request'][key] for key in ('source_commit', 'source_manifest_sha256', 'operation'))):
        raise ValueError('Completion is not a source-bound unpublished review')
    review = regular(attempt / 'review', directory=True)
    run_path = regular(review / 'run.json', limit=MAX_JSON)
    run = read_json(run_path)
    if digest(run_path) != stored.get('pipeline_receipt_sha256'):
        raise ValueError('Producer receipt changed after completion')
    sources = run.get('source_sha256')
    if (not isinstance(sources, dict) or set(sources) != set(SOURCES)
            or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in sources.values())
            or hashlib.sha256(canonical(sources).encode()).hexdigest() != spec['request']['source_manifest_sha256']):
        raise ValueError('Producer source manifest does not match immutable request')
    artifacts = run.get('artifacts_sha256')
    if not isinstance(artifacts, dict) or not 4 <= len(artifacts) <= 100:
        raise ValueError('Invalid artifact inventory')
    total = 0
    for name, expected in artifacts.items():
        if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name)
                or name == 'run.json' or not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
            raise ValueError('Invalid artifact identity')
        total += regular(review / name).stat().st_size
    if total > MAX_PACKET:
        raise ValueError('Review packet exceeds delivery limit')
    check_completed(review, {'source_files': sources})
    if (run['candidate_sha256'] != stored.get('candidate_sha256')
            or digest(run_path) != stored['pipeline_receipt_sha256']):
        raise ValueError('Candidate or producer receipt identity changed')
    from integrations.content_control.review_package import inspect_packet
    inspect_packet(review, stored['pipeline_receipt_sha256'], stored['candidate_sha256'])
    provenance = {
        'job_id': job_id, 'job_digest': job['digest'], 'attempt': latest['number'],
        'completed_at_unix': latest['finished'], 'source_commit': spec['request']['source_commit'],
        'source_manifest_sha256': spec['request']['source_manifest_sha256'],
        'candidate_sha256': stored['candidate_sha256'],
        'pipeline_receipt_sha256': stored['pipeline_receipt_sha256'],
        'adapter_receipt_sha256': digest(attempt / 'video-adapter-receipt.json'),
        'publication_enabled': False, 'paid_generation_enabled': False,
        'production_approved': False, 'production_ready': False, 'full_av_review': False,
        'scope': 'Verified durable queue completion; delivery is not creative or publishing approval',
    }
    return review, provenance


def status(queue_root, job_id):
    _, job, _, attempts = read_job(queue_root, job_id)
    report = {key: job[key] for key in ('id', 'state', 'attempts', 'max_attempts')}
    report.update(delivery_ready=False, publication_enabled=False, paid_generation_enabled=False,
                  production_approved=False, production_ready=False, full_av_review=False)
    if job['state'] == 'succeeded':
        try:
            _, provenance = verify_delivery(queue_root, job_id)
            report.update(delivery_ready=True, provenance=provenance,
                          next_action='Export the verified private review package, then review the full video with audio')
        except (ValueError, OSError, KeyError, TypeError) as error:
            report.update(delivery_error=str(error), next_action='Inspect changed or missing artifacts; do not deliver this result')
    else:
        actions = {
            'queued': 'Run the bounded queue worker with the selected local runtimes',
            'running': 'Wait for the bounded attempt; use queue health to check worker liveness',
            'interrupted': 'Inspect partial logs and uncertain execution before explicitly retrying',
            'blocked': 'Resolve the recorded prerequisite or capacity blocker before explicitly retrying',
            'failed': 'Inspect the retained failure receipt before explicitly retrying',
        }
        report['next_action'] = actions.get(job['state'], 'Inspect the queue state')
        if attempts and attempts[-1]['receipt']:
            receipt = parse_json(attempts[-1]['receipt'])
            report['last_reason'] = receipt.get('blocker') or receipt.get('reason') or receipt.get('exception_type')
        report['retry_attempts_remaining'] = max(0, job['max_attempts'] - job['attempts'])
        if job['state'] in ('blocked', 'failed', 'interrupted') and report['retry_attempts_remaining'] == 0:
            report['next_action'] += '; the attempt limit is exhausted, so retain this history and prepare a separately reviewed new job'
    return report


def export_review(queue_root, job_id, output_dir):
    review, provenance = verify_delivery(queue_root, job_id)
    from integrations.content_control.review_package import package_review
    return package_review(review, output_dir,
                          expected_run_sha256=provenance['pipeline_receipt_sha256'],
                          expected_candidate_sha256=provenance['candidate_sha256'],
                          provenance=provenance)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue', required=True)
    parser.add_argument('--id', required=True, help='Immutable queued video ID')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    export = commands.add_parser('export')
    export.add_argument('--output', required=True, help='New private review package directory')
    args = parser.parse_args(argv)
    try:
        report = status(args.queue, args.id) if args.command == 'status' else export_review(args.queue, args.id, args.output)
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as error:
        print(json.dumps({'status': 'DELIVERY_BLOCKED', 'reason': str(error),
                          'publication_enabled': False, 'paid_generation_enabled': False,
                          'production_ready': False, 'production_approved': False}, indent=2))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if args.command == 'export' or report.get('delivery_ready') else 2


if __name__ == '__main__':
    raise SystemExit(main())
