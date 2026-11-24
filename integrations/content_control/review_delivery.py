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
from zipfile import BadZipFile, ZipFile

from integrations.local_agent_queue import canonical, validate
from integrations.content_control.runtime_doctor import SOURCES
from integrations.content_control.video_job import check_completed, digest

MAX_JSON = 4 * 1024 * 1024
MAX_FILE = 512 * 1024 * 1024
MAX_PACKET = 1024 * 1024 * 1024
FLAGS = dict.fromkeys(('publication_enabled', 'paid_generation_enabled', 'production_ready',
                       'production_approved', 'full_av_review'), False)
DELIVERY_REPORT_FIELDS = frozenset({
    'schema_version', 'status', *FLAGS, 'candidate_sha256', 'archive', 'archive_sha256',
    'entrypoint', 'entrypoint_sha256', 'package_sha256', 'files_sha256',
    'delivery_identity_sha256', 'provenance', 'scope',
})
CYCLE_PROVENANCE_REQUIRED = frozenset({
    'job_id', 'job_digest', 'attempt', 'completed_at_unix', 'candidate_sha256',
    'pipeline_receipt_sha256', 'adapter_receipt_sha256', *FLAGS, 'scope', 'adapter',
    'brief_sha256', 'production_brief_sha256', 'package_sha256', 'review_archive_sha256',
})
CYCLE_PROVENANCE_OPTIONAL = frozenset({'minimum_duration_seconds', 'verified_intake'})
PACKAGE_GATE_FIELDS = frozenset({
    'publication_enabled', 'paid_generation_enabled', 'production_approved', 'full_av_review',
    'production_ready', 'thumbnail_performance_verified', 'independent_transcription_verified',
    'review_required',
})
GATE_FIELD = re.compile(
    r'(?:publish|publication|paid|production|approval|approved|ready|full_av|playback|phone|listen|verified|review)',
    re.I)


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
        if (spec['id'] != job_id or spec['adapter'] not in (
                'content-control-video', 'content-control-cycle', 'content-control-external-media')
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
    adapter_names = {
        'content-control-cycle': 'cycle-adapter-receipt.json',
        'content-control-video': 'video-adapter-receipt.json',
        'content-control-external-media': 'external-media-adapter-receipt.json',
    }
    adapter_path = attempt / adapter_names[spec['adapter']]
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
    if spec['adapter'] == 'content-control-external-media':
        return verify_external_media_delivery(attempt, spec['request'], stored, provenance)
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
    if 'automated_review_sha256' in stored:
        from integrations.content_control.cycle_av_review import verify_automated_review
        expected = stored['automated_review_sha256']
        verify_automated_review(attempt / 'automated-review.json', expected, stored['candidate_sha256'],
                                run['caption_sha256'])
        provenance['automated_review_sha256'] = expected
    provenance.update(source_commit=spec['request']['source_commit'],
                      source_manifest_sha256=spec['request']['source_manifest_sha256'])
    return review, provenance


def verify_external_media_delivery(attempt, request, stored, provenance):
    """Bind durable queue completion back to the exact offline source packet."""
    from integrations.content_control.external_media_job import check_completed

    pinned = ('source_candidate_sha256', 'transformed_source_sha256', 'candidate_sha256',
              'external_receipt_sha256', 'prior_tool_receipt_sha256',
              'review_run_sha256', 'tool_commit')
    if (stored.get('artifact_directory') != 'review'
            or stored.get('package_directory') != 'delivery'
            or stored.get('source_inputs_unchanged') is not True
            or stored.get('provider_calls') != 0
            or any(stored.get(name) != request[name] for name in pinned)
            or stored.get('pipeline_receipt_sha256') != request['review_run_sha256']):
        raise ValueError('Completion is not a source-bound offline external-media review')
    completed = check_completed(attempt, request)
    if (completed['package_sha256'] != stored.get('package_sha256')
            or completed['archive_sha256'] != stored.get('archive_sha256')):
        raise ValueError('External-media review package changed after completion')
    provenance.update(
        adapter='content-control-external-media',
        source_candidate_sha256=request['source_candidate_sha256'],
        transformed_source_sha256=request['transformed_source_sha256'],
        external_receipt_sha256=request['external_receipt_sha256'],
        prior_tool_receipt_sha256=request['prior_tool_receipt_sha256'],
        tool_commit=request['tool_commit'],
        package_sha256=completed['package_sha256'],
        review_archive_sha256=completed['archive_sha256'],
        provider_calls=0,
    )
    return completed['review'], provenance


def verify_cycle_delivery(attempt, request, stored, provenance):
    from integrations.content_control.cycle_job import (
        check_completed as check_cycle, production_handoff, verify_attempt_intake,
    )
    from integrations.content_control.cycle_review import inspect_cycle

    raw, lineage, _, intake = production_handoff(request)
    brief_sha = hashlib.sha256(raw).hexdigest()
    minimum = request.get('minimum_duration_seconds')
    if (stored.get('artifact_directory') != 'cycle' or stored.get('brief_sha256') != request['brief_sha256']
            or stored.get('production_brief_sha256') != brief_sha):
        raise ValueError('Cycle completion does not bind the immutable brief')
    stored_minimum = stored.get('minimum_duration_seconds')
    if stored_minimum != minimum or type(stored_minimum) is not type(minimum):
        raise ValueError('Cycle completion does not bind the queued minimum duration')
    if stored.get('verified_intake') != intake:
        raise ValueError('Cycle completion does not bind the queued verified intake')
    cycle_dir = regular(attempt / 'cycle', directory=True)
    snapshot = inspect_cycle(cycle_dir)
    if (snapshot['candidate_sha256'] != stored['candidate_sha256']
            or snapshot['files_sha256']['cycle.json'] != stored['pipeline_receipt_sha256']
            or snapshot['cycle'].get('revision_lineage') != lineage):
        raise ValueError('Candidate, cycle receipt or revision changed after completion')
    cycle = check_cycle(cycle_dir, brief_sha, minimum_duration=minimum)
    verify_attempt_intake(attempt, intake, cycle)
    archive_sha = snapshot['files_sha256']['delivery/review-package.zip']
    if cycle != snapshot['cycle'] or archive_sha != cycle.get('archive_sha256'):
        raise ValueError('Review archive or cycle changed after completion')
    provenance.update(adapter='content-control-cycle', brief_sha256=request['brief_sha256'],
                      production_brief_sha256=brief_sha, package_sha256=cycle['package_sha256'],
                      review_archive_sha256=archive_sha)
    if minimum is not None:
        provenance['minimum_duration_seconds'] = minimum
    if intake is not None:
        provenance['verified_intake'] = intake
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
    expected = provenance.get('automated_review_sha256')
    return package_review(review, output_dir,
                          expected_run_sha256=provenance['pipeline_receipt_sha256'],
                          expected_candidate_sha256=provenance['candidate_sha256'],
                          provenance=provenance,
                          automated_review=(review.parent / 'automated-review.json', expected) if expected else None)


def export_cycle(review, provenance, queue_root, output_dir):
    from integrations.content_control.cycle_checkpoint import _publish_restore
    from integrations.content_control.review_package import LIMIT, SHA, no_symlinks

    output = Path(os.path.abspath(output_dir))
    no_symlinks(output)
    if output.exists() or output.is_relative_to(Path(os.path.abspath(queue_root))):
        raise ValueError('Fresh export directory outside the queue required')
    source = regular(review / 'review-package.zip', limit=LIMIT)
    package_path = regular(review / 'package.json', limit=MAX_JSON)
    package = read_json(package_path)
    files = package.get('files_sha256')
    if (digest(package_path) != provenance['package_sha256'] or not isinstance(files, dict)
            or not files or files.get('video.mp4') != provenance['candidate_sha256']):
        raise ValueError('Verified cycle package identity changed before export')
    for name, expected in files.items():
        if (not isinstance(name, str) or Path(name).name != name or name in ('.', '..')
                or not isinstance(expected, str) or not SHA.fullmatch(expected)):
            raise ValueError('Invalid verified cycle preview identity')

    entrypoint = 'review/index.html'
    preview_files = {'review/' + name: expected for name, expected in files.items()}
    preview_files['review/package.json'] = provenance['package_sha256']
    identity = {
        'job_id': provenance['job_id'], 'job_digest': provenance['job_digest'],
        'attempt': provenance['attempt'], 'candidate_sha256': provenance['candidate_sha256'],
        'package_sha256': provenance['package_sha256'],
        'archive_sha256': provenance['review_archive_sha256'],
        'entrypoint': entrypoint, 'entrypoint_sha256': files.get('index.html'),
        'files_sha256': preview_files, 'provenance': provenance, **FLAGS,
    }
    report = {'schema_version': 1, 'status': 'AWAITING_REVIEW', **FLAGS,
              'candidate_sha256': provenance['candidate_sha256'], 'archive': source.name,
              'archive_sha256': provenance['review_archive_sha256'], 'entrypoint': entrypoint,
              'entrypoint_sha256': files.get('index.html'),
              'package_sha256': provenance['package_sha256'],
              'files_sha256': preview_files,
              'delivery_identity_sha256': hashlib.sha256(canonical(identity).encode()).hexdigest(),
              'provenance': provenance,
              'scope': 'Exact unpublished private preview delivery; playback and creative acceptance remain unverified'}
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
        preview = stage / 'review'; preview.mkdir(mode=0o700)
        remaining = MAX_PACKET
        for name, expected in sorted({**files, 'package.json': provenance['package_sha256']}.items()):
            origin = regular(review / name, limit=MAX_FILE)
            remaining -= origin.stat().st_size
            if remaining < 0:
                raise ValueError('Private preview exceeds delivery limit')
            target = preview / name
            with origin.open('rb') as incoming, target.open('xb') as outgoing:
                while chunk := incoming.read(1024 * 1024):
                    outgoing.write(chunk)
            if digest(target) != expected:
                raise ValueError('Private preview changed during export: ' + name)
        if (digest(source) != report['archive_sha256']
                or digest(package_path) != provenance['package_sha256']):
            raise ValueError('Verified cycle delivery changed during export')
        (stage / 'package.json').write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
        _publish_restore(stage, output)
    return report


def verify_exported_cycle(output_dir, expected_delivery_identity_sha256):
    """Reopen a retained private cycle export without trusting its receipt.

    Export verifies the source queue at copy time.  This verifier is for the
    other side of that boundary: it rehashes the durable tree and the original
    archive later, without access to the queue or permission to rewrite it.
    Playback remains a separate human/device observation.
    """
    if (not isinstance(expected_delivery_identity_sha256, str)
            or not re.fullmatch('[0-9a-f]{64}', expected_delivery_identity_sha256)):
        raise ValueError('Trusted expected delivery identity is required')
    output = regular(output_dir, directory=True)
    if {path.name for path in output.iterdir()} != {'package.json', 'review-package.zip', 'review'}:
        raise ValueError('Private delivery root inventory changed')
    report = read_json(output / 'package.json')
    if set(report) != DELIVERY_REPORT_FIELDS:
        raise ValueError('Private delivery receipt schema is invalid')
    if (report.get('schema_version') != 1 or report.get('status') != 'AWAITING_REVIEW'
            or any(report.get(flag) is not False for flag in FLAGS)
            or report.get('archive') != 'review-package.zip'
            or report.get('entrypoint') != 'review/index.html'
            or report.get('scope') != 'Exact unpublished private preview delivery; playback and creative acceptance remain unverified'):
        raise ValueError('Private delivery receipt is not an unpublished cycle review')

    hashes = report.get('files_sha256')
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('Private delivery file inventory is invalid')
    for name, expected in hashes.items():
        if (not isinstance(name, str)
                or not re.fullmatch(r'review/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name)
                or not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
            raise ValueError('Private delivery file identity is invalid')
    preview = regular(output / 'review', directory=True)
    if {path.relative_to(output).as_posix() for path in preview.iterdir()} != set(hashes):
        raise ValueError('Private preview inventory changed')
    remaining = MAX_PACKET
    for name, expected in hashes.items():
        artifact = regular(output / name, limit=MAX_FILE)
        remaining -= artifact.stat().st_size
        if remaining < 0:
            raise ValueError('Private preview exceeds delivery limit')
        if digest(artifact) != expected:
            raise ValueError('Private preview identity changed: ' + name)

    candidate = report.get('candidate_sha256')
    package_sha = report.get('package_sha256')
    archive_sha = report.get('archive_sha256')
    entry_sha = report.get('entrypoint_sha256')
    if (not all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                for value in (candidate, package_sha, archive_sha, entry_sha))
            or hashes.get('review/video.mp4') != candidate
            or hashes.get('review/package.json') != package_sha
            or hashes.get(report['entrypoint']) != entry_sha):
        raise ValueError('Private delivery primary identities disagree')

    archive_path = regular(output / report['archive'], limit=MAX_PACKET)
    if digest(archive_path) != archive_sha:
        raise ValueError('Private delivery archive identity changed')
    expected_members = {name.removeprefix('review/'): value for name, value in hashes.items()}
    with ZipFile(archive_path) as archive:
        members = archive.infolist()
        if (len({info.filename for info in members}) != len(members)
                or {info.filename for info in members} != set(expected_members)
                or archive.testzip() is not None):
            raise ValueError('Private delivery archive inventory changed')
        remaining = MAX_PACKET
        for info in members:
            if (info.is_dir() or ((info.external_attr >> 16) & 0o170000) == 0o120000
                    or info.file_size > MAX_FILE):
                raise ValueError('Private delivery archive member is invalid')
            remaining -= info.file_size
            if remaining < 0:
                raise ValueError('Private delivery archive exceeds delivery limit')
            observed = hashlib.sha256()
            with archive.open(info) as stream:
                while chunk := stream.read(1024 * 1024):
                    observed.update(chunk)
            if observed.hexdigest() != expected_members[info.filename]:
                raise ValueError('Private delivery archive member changed: ' + info.filename)

    provenance = report.get('provenance')
    if (not isinstance(provenance, dict)
            or not CYCLE_PROVENANCE_REQUIRED <= set(provenance)
            or set(provenance) - CYCLE_PROVENANCE_REQUIRED - CYCLE_PROVENANCE_OPTIONAL
            or not isinstance(provenance.get('job_id'), str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', provenance['job_id'])
            or not isinstance(provenance.get('job_digest'), str)
            or not re.fullmatch('[0-9a-f]{64}', provenance['job_digest'])
            or type(provenance.get('attempt')) is not int or provenance['attempt'] < 1
            or type(provenance.get('completed_at_unix')) not in (int, float)
            or not 0 < provenance['completed_at_unix'] < float('inf')
            or provenance.get('adapter') != 'content-control-cycle'
            or provenance.get('candidate_sha256') != candidate
            or provenance.get('package_sha256') != package_sha
            or provenance.get('review_archive_sha256') != archive_sha
            or any(not isinstance(provenance.get(name), str)
                   or not re.fullmatch('[0-9a-f]{64}', provenance[name])
                   for name in ('pipeline_receipt_sha256', 'adapter_receipt_sha256',
                                'brief_sha256', 'production_brief_sha256'))
            or provenance.get('scope') != 'Verified durable queue completion; delivery is not creative or publishing approval'
            or any(provenance.get(flag) is not False for flag in FLAGS)):
        raise ValueError('Private delivery provenance is invalid')
    minimum = provenance.get('minimum_duration_seconds')
    if ('minimum_duration_seconds' in provenance
            and (type(minimum) not in (int, float) or not 0 < minimum < float('inf'))):
        raise ValueError('Private delivery provenance is invalid')
    intake = provenance.get('verified_intake')
    if ('verified_intake' in provenance
            and (not isinstance(intake, dict) or len(canonical(intake).encode()) > MAX_JSON)):
        raise ValueError('Private delivery provenance is invalid')

    source_package = read_json(output / 'review/package.json')
    source_hashes = source_package.get('files_sha256')
    if (source_package.get('schema_version') != 1
            or source_package.get('status') != 'AWAITING_REVIEW'
            or source_package.get('technical_status') != 'PASS'
            or any(source_package.get(flag) is not False for flag in FLAGS)
            or any(GATE_FIELD.search(key) and key not in PACKAGE_GATE_FIELDS for key in source_package)
            or source_package.get('candidate_sha256') != candidate
            or not isinstance(source_hashes, dict)
            or {'review/' + name: value for name, value in source_hashes.items()}
               != {name: value for name, value in hashes.items() if name != 'review/package.json'}):
        raise ValueError('Private delivery source package is invalid')
    identity = {
        'job_id': provenance['job_id'], 'job_digest': provenance['job_digest'],
        'attempt': provenance['attempt'], 'candidate_sha256': candidate,
        'package_sha256': package_sha, 'archive_sha256': archive_sha,
        'entrypoint': report['entrypoint'], 'entrypoint_sha256': entry_sha,
        'files_sha256': hashes, 'provenance': provenance, **FLAGS,
    }
    identity_sha = hashlib.sha256(canonical(identity).encode()).hexdigest()
    if report.get('delivery_identity_sha256') != identity_sha:
        raise ValueError('Private delivery identity receipt changed')
    if identity_sha != expected_delivery_identity_sha256:
        raise ValueError('Private delivery does not match trusted expected identity')
    return {'schema_version': 1, 'status': 'PASS', **FLAGS,
            'candidate_sha256': candidate, 'package_sha256': package_sha,
            'archive_sha256': archive_sha, 'entrypoint': report['entrypoint'],
            'entrypoint_sha256': entry_sha, 'delivery_identity_sha256': identity_sha,
            'scope': 'Caller-supplied delivery identity matched durable private bytes; playback and creative acceptance remain unverified'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue')
    parser.add_argument('--id', help='Immutable queued video ID')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    export = commands.add_parser('export')
    export.add_argument('--output', required=True, help='New private review package directory')
    verify = commands.add_parser('verify')
    verify.add_argument('--output', required=True, help='Existing private review package directory')
    verify.add_argument('--expected-delivery-identity', required=True,
                        help='Trusted delivery_identity_sha256 received separately from the retained directory')
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            report = verify_exported_cycle(args.output, args.expected_delivery_identity)
        else:
            if not args.queue or not args.id:
                raise ValueError('--queue and --id are required for queue status or export')
            report = status(args.queue, args.id) if args.command == 'status' else export_review(args.queue, args.id, args.output)
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, BadZipFile, RuntimeError) as error:
        print(json.dumps({'status': 'DELIVERY_BLOCKED', 'reason': str(error),
                          'publication_enabled': False, 'paid_generation_enabled': False,
                          'production_ready': False, 'production_approved': False}, indent=2))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if args.command in ('export', 'verify') or report.get('delivery_ready') else 2


if __name__ == '__main__':
    raise SystemExit(main())
