"""Prepare and independently verify one source-pinned unpublished queued video.

The workflow invokes the existing queue worker in a separate process between
these phases. No capacity override, deployment, publishing or retry is provided.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from integrations.agent_capacity import collect_snapshot
from integrations.local_agent_queue import Queue, canonical, validate
from integrations.content_control.runtime_doctor import describe_source
from integrations.content_control.video_job import check_completed, digest

JOB_ID = 'hosted-episode1-review'


def write_json(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def prepare(output, content_control_root, source_commit):
    if not re.fullmatch('[0-9a-f]{40}', source_commit):
        raise ValueError('An immutable 40-character Content Control commit is required')
    source = describe_source(content_control_root, expected_commit=source_commit)
    root = Path(output)
    root.mkdir(parents=False, exist_ok=False)
    write_json(root / 'source.json', source)
    # Observational evidence only. The actual adapter collects a new snapshot
    # under its shared host admission lease immediately before production.
    write_json(root / 'host-observation.json', collect_snapshot())
    job = {'id': JOB_ID, 'adapter': 'content-control-video',
           'request': {'operation': 'produce-episode1-review',
                       'source_commit': source['source_commit'],
                       'source_manifest_sha256': source['source_manifest_sha256'],
                       'timeout_seconds': 900, 'publication_enabled': False,
                       'paid_generation_enabled': False},
           'max_attempts': 1, 'publication_enabled': False, 'paid_generation_enabled': False}
    write_json(root / 'job.json', job)
    queue = Queue(root / 'queue')
    try:
        queue.enqueue(job)
    finally:
        queue.close()
    return {'status': 'QUEUED', 'id': JOB_ID, 'publication_enabled': False}


def verify(output):
    root = Path(output)
    report = {'schema_version': 1, 'observed_at': datetime.now(timezone.utc).isoformat(),
              'status': 'BLOCKED', 'publication_enabled': False, 'paid_generation_enabled': False,
              'production_approved': False, 'full_av_review': False, 'persistent_worker_verified': False,
              'scope': 'One real queued packet, reopened SQLite and file identities; no unattended service or actual PC/VPS verified',
              'persistence_scope': 'Closed local SQLite and packet; archive retention requires a successful workflow artifact upload'}
    try:
        source = json.loads((root / 'source.json').read_text())
        job = json.loads((root / 'job.json').read_text())
        validate(job)
        if not (root / 'queue/queue.sqlite3').is_file():
            raise ValueError('Queue database missing')
        queue = Queue(root / 'queue')
        try:
            state = queue.get(JOB_ID)
            health = queue.health()
        finally:
            queue.close()
        report['queue_state'] = state
        report['worker_health'] = health
        if hashlib.sha256(canonical(job).encode()).hexdigest() != state['digest']:
            raise ValueError('Saved request differs from durable queue identity')
        if hashlib.sha256(canonical(source['source_files']).encode()).hexdigest() != source['source_manifest_sha256']:
            raise ValueError('Source manifest bytes do not match their identity')
        if state['state'] != 'succeeded' or state['attempts'] != 1 or len(state['receipts']) != 1:
            raise ValueError('Exactly one successful durable attempt is required')
        completed = state['receipts'][0]
        if completed['number'] != 1 or completed['state'] != 'succeeded' or completed['finished'] is None:
            raise ValueError('Durable attempt completion is inconsistent')
        if health['consumer_lock_held'] is not False or not health['run'] or health['run']['finished'] is None:
            raise ValueError('Worker must finish and release ownership before checkpoint verification')
        outer = completed['receipt']
        if (outer.get('status') != 'PASS' or outer.get('review_status') != 'AWAITING_REVIEW'
                or outer.get('publication_enabled') is not False or outer.get('paid_generation_enabled') is not False
                or outer.get('production_approved') is not False or outer.get('full_av_review') is not False
                or outer.get('production_ready') is not False or outer.get('artifact_directory') != 'review'
                or outer.get('source_inputs_unchanged') is not True
                or outer.get('capacity', {}).get('admitted_workers') != 1):
            raise ValueError('Adapter did not verify an admitted unpublished packet')
        if (outer.get('source_commit') != source['source_commit']
                or outer.get('source_manifest_sha256') != source['source_manifest_sha256']
                or job['request']['source_commit'] != source['source_commit']
                or job['request']['source_manifest_sha256'] != source['source_manifest_sha256']):
            raise ValueError('Queue source identity mismatch')
        attempt = root / 'queue/attempts' / JOB_ID / '1'
        if json.loads((attempt / 'video-adapter-receipt.json').read_text()) != outer:
            raise ValueError('Adapter file and durable receipt differ')
        packet = attempt / 'review'
        receipt = check_completed(packet, source)
        if (outer.get('candidate_sha256') != receipt['candidate_sha256']
                or outer.get('pipeline_receipt_sha256') != digest(packet / 'run.json')):
            raise ValueError('Durable receipt does not bind final packet')
        report.update(status='QUEUED_PACKET_VERIFIED', review_status='AWAITING_REVIEW',
                      candidate_sha256=receipt['candidate_sha256'],
                      source_commit=source['source_commit'], source_manifest_sha256=source['source_manifest_sha256'],
                      pipeline_receipt_sha256=digest(packet / 'run.json'),
                      queue_database_sha256=digest(root / 'queue/queue.sqlite3'),
                      packet_path='queue/attempts/' + JOB_ID + '/1/review')
    except (OSError, ValueError, KeyError, TypeError) as error:
        report['blocker'] = str(error) if isinstance(error, ValueError) else type(error).__name__
    write_json(root / 'hosted-queue-verification.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    plan = commands.add_parser('prepare')
    plan.add_argument('--content-control-root', required=True)
    plan.add_argument('--source-commit', required=True)
    commands.add_parser('verify')
    args = parser.parse_args(argv)
    result = (prepare(args.output, args.content_control_root, args.source_commit)
              if args.command == 'prepare' else verify(args.output))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 2 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
