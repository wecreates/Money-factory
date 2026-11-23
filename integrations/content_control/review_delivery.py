"""Read-only delivery of a durably completed, unpublished queued video.

A video left behind by an interrupted attempt is never a deliverable. SQLite,
the adapter receipt, the producer receipt and every artifact must agree.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from zipfile import BadZipFile

from integrations.local_agent_queue import canonical, validate
from integrations.content_control.runtime_doctor import SOURCES
from integrations.content_control.video_job import check_completed, digest

MAX_JSON = 4 * 1024 * 1024
MAX_FILE = 512 * 1024 * 1024
MAX_PACKET = 1024 * 1024 * 1024
FLAGS = dict.fromkeys(('publication_enabled', 'paid_generation_enabled', 'production_ready',
                       'production_approved', 'full_av_review'), False)


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
        if (spec['id'] != job_id or spec['adapter'] not in ('content-control-video', 'content-control-cycle')
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
    fresh = spec['adapter'] == 'content-control-cycle'
    adapter_path = attempt / ('cycle-adapter-receipt.json' if fresh else 'video-adapter-receipt.json')
    with regular(adapter_path, limit=MAX_JSON).open('rb') as stream:
        adapter_raw = stream.read(MAX_JSON + 1)
    adapter = parse_json(adapter_raw.decode('utf-8'))
    if canonical(adapter) != canonical(stored):
        raise ValueError('Adapter receipt differs from durable completion')
    if (stored.get('status') != 'PASS' or stored.get('review_status') != 'AWAITING_REVIEW'
            or any(stored.get(flag) is not False for flag in FLAGS)
            or stored.get('operation') != spec['request']['operation']):
        raise ValueError('Completion is not an unpublished review')
    provenance = {'job_id': job_id, 'job_digest': job['digest'], 'attempt': latest['number'],
                  'completed_at_unix': latest['finished'], 'candidate_sha256': stored.get('candidate_sha256'),
                  'pipeline_receipt_sha256': stored.get('pipeline_receipt_sha256'),
                  'adapter_receipt_sha256': hashlib.sha256(adapter_raw).hexdigest(), **FLAGS,
                  'scope': 'Verified durable queue completion; delivery is not creative or publishing approval'}
    if fresh:
        return verify_cycle_delivery(attempt, spec['request'], stored, provenance)
    if (stored.get('artifact_directory') != 'review' or stored.get('source_inputs_unchanged') is not True
            or any(stored.get(key) != spec['request'][key] for key in ('source_commit', 'source_manifest_sha256'))):
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
    provenance.update(source_commit=spec['request']['source_commit'],
                      source_manifest_sha256=spec['request']['source_manifest_sha256'])
    return review, provenance


def verify_cycle_delivery(attempt, request, stored, provenance):
    from integrations.content_control.cycle_job import check_completed as check_cycle, production_input
    from integrations.content_control.cycle_review import inspect_cycle

    raw, lineage = production_input(request)
    brief_sha = hashlib.sha256(raw).hexdigest()
    minimum = request.get('minimum_duration_seconds')
    if (stored.get('artifact_directory') != 'cycle' or stored.get('brief_sha256') != request['brief_sha256']
            or stored.get('production_brief_sha256') != brief_sha):
        raise ValueError('Cycle completion does not bind the immutable brief')
    stored_minimum = stored.get('minimum_duration_seconds')
    if stored_minimum != minimum or type(stored_minimum) is not type(minimum):
        raise ValueError('Cycle completion does not bind the queued minimum duration')
    cycle_dir = regular(attempt / 'cycle', directory=True)
    snapshot = inspect_cycle(cycle_dir)
    if (snapshot['candidate_sha256'] != stored['candidate_sha256']
            or snapshot['files_sha256']['cycle.json'] != stored['pipeline_receipt_sha256']
            or snapshot['cycle'].get('revision_lineage') != lineage):
        raise ValueError('Candidate, cycle receipt or revision changed after completion')
    cycle = check_cycle(cycle_dir, brief_sha, minimum_duration=minimum)
    archive_sha = snapshot['files_sha256']['delivery/review-package.zip']
    if cycle != snapshot['cycle'] or archive_sha != cycle.get('archive_sha256'):
        raise ValueError('Review archive or cycle changed after completion')
    provenance.update(adapter='content-control-cycle', brief_sha256=request['brief_sha256'],
                      production_brief_sha256=brief_sha, package_sha256=cycle['package_sha256'],
                      review_archive_sha256=archive_sha)
    if minimum is not None:
        provenance['minimum_duration_seconds'] = minimum
    return cycle_dir / 'delivery', provenance


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
        except (ValueError, OSError, KeyError, TypeError, BadZipFile, RuntimeError) as error:
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
    if provenance.get('adapter') == 'content-control-cycle':
        return export_cycle(review, provenance, queue_root, output_dir)
    from integrations.content_control.review_package import package_review
    return package_review(review, output_dir,
                          expected_run_sha256=provenance['pipeline_receipt_sha256'],
                          expected_candidate_sha256=provenance['candidate_sha256'],
                          provenance=provenance)


def export_cycle(review, provenance, queue_root, output_dir):
    from integrations.content_control.cycle_checkpoint import _publish_restore
    from integrations.content_control.review_package import LIMIT, no_symlinks

    output = Path(os.path.abspath(output_dir))
    no_symlinks(output)
    if output.exists() or output.is_relative_to(Path(os.path.abspath(queue_root))):
        raise ValueError('Fresh export directory outside the queue required')
    source = regular(review / 'review-package.zip', limit=LIMIT)
    report = {'schema_version': 1, 'status': 'AWAITING_REVIEW', **FLAGS,
              'candidate_sha256': provenance['candidate_sha256'], 'archive': source.name,
              'archive_sha256': provenance['review_archive_sha256'], 'entrypoint': 'index.html',
              'provenance': provenance}
    with tempfile.TemporaryDirectory(prefix='.cycle-export-', dir=output.parent) as directory:
        stage = Path(directory) / 'review'; stage.mkdir(mode=0o700)
        archive = stage / source.name
        with source.open('rb') as incoming, archive.open('xb') as outgoing:
            remaining = LIMIT
            while chunk := incoming.read(1024 * 1024):
                remaining -= len(chunk)
                if remaining < 0:
                    raise ValueError('Review archive grew past delivery limit')
                outgoing.write(chunk)
        if digest(archive) != report['archive_sha256']:
            raise ValueError('Review archive changed during export')
        (stage / 'package.json').write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
        _publish_restore(stage, output)
    return report


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
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, BadZipFile, RuntimeError) as error:
        print(json.dumps({'status': 'DELIVERY_BLOCKED', 'reason': str(error),
                          'publication_enabled': False, 'paid_generation_enabled': False,
                          'production_ready': False, 'production_approved': False}, indent=2))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if args.command == 'export' or report.get('delivery_ready') else 2


if __name__ == '__main__':
    raise SystemExit(main())
