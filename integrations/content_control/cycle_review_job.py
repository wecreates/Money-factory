"""Durably consume retained REA evidence through the cycle review recorder.

The queue owns a byte-for-byte copy of the completed cycle, REA analysis, and
submitted review before recording a result.  This adapter is deliberately
offline: it never invokes a provider, publishes, or promotes a review to
production approval.
"""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import time
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from integrations.content_control.review_package import check_deadline, no_symlinks


SHA256 = re.compile(r'^[0-9a-f]{64}$')
OPERATION = 'record-retained-rea-review'
MAX_JSON = 4 * 1024 * 1024
MAX_FILES = 2048
MAX_TREE_BYTES = 512 * 1024 * 1024
FIELDS = {
    'operation', 'candidate_sha256', 'caption_sha256', 'package_sha256',
    'review_archive_sha256', 'rea_receipt_sha256',
    'submitted_review_sha256', 'timeout_seconds', 'publication_enabled',
    'paid_generation_enabled', 'production_approved', 'production_ready',
    'full_av_review',
}
FALSE_FLAGS = ('publication_enabled', 'paid_generation_enabled',
               'production_approved', 'production_ready', 'full_av_review')
SCOPE = ('Durable local review consumption only; diagnostics and supplied '
         'attestations do not establish audiovisual or creative acceptance.')
SUCCESS_RECEIPT_FIELDS = {
    'schema_version', 'status', 'operation', 'candidate_sha256', 'provider_calls',
    'retryable', 'publication_enabled', 'paid_generation_enabled',
    'production_approved', 'production_ready', 'full_av_review', 'scope',
    'review_status', 'rea_receipt_sha256', 'submitted_review_sha256',
    'input_manifest_sha256', 'recorded_review_sha256',
    'review_manifest_sha256', 'review_export_sha256',
    'source_inputs_unchanged',
}
RECORDED_REVIEW_FIELDS = {
    'schema_version', 'status', 'candidate_sha256', 'reviewer', 'reviewed_at',
    'recorded_at', 'checks', 'feedback', 'source_files_sha256',
    'submitted_review_sha256', 'independent_verification', 'scope',
    'publication_enabled', 'paid_generation_enabled', 'production_approved',
    'full_av_review', 'production_ready', 'rea_diagnostics',
}


def _child_call(connection, function, args, kwargs):
    """Run one review primitive in a killable process group."""
    try:
        os.setsid()
        connection.send(('ready',))
        connection.send(('ok', function(*args, **kwargs)))
    except BaseException as error:
        connection.send(('error', type(error).__name__, str(error)))
    finally:
        connection.close()


def _stop_process(process, *, group_ready):
    """Bounded process-group stop with direct-process fallback."""
    if group_ready:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.is_alive():
        try:
            process.kill()
        except (AttributeError, ProcessLookupError):
            process.terminate()
    process.join(.5)
    if process.is_alive():
        process.terminate()
        process.join(.5)
    if process.is_alive():
        try:
            process.kill()
        except (AttributeError, ProcessLookupError):
            pass
        process.join(.5)
    if process.is_alive():
        raise RuntimeError('Isolated review process could not be stopped')


def _bounded_call(deadline, label, function, *args, **kwargs):
    """Hard-bound a potentially blocking local review primitive."""
    check_deadline(deadline)
    remaining = deadline - time.monotonic()
    try:
        context = multiprocessing.get_context('fork')
    except ValueError as error:
        raise RuntimeError('Retained review execution requires POSIX fork isolation') from error
    incoming, outgoing = context.Pipe(duplex=False)
    process = context.Process(target=_child_call,
                              args=(outgoing, function, args, kwargs), daemon=False)
    process.start()
    outgoing.close()
    if not incoming.poll(remaining):
        _stop_process(process, group_ready=False)
        incoming.close()
        raise TimeoutError('Review deadline exhausted during ' + label)
    first = incoming.recv()
    if first[0] != 'ready':
        _stop_process(process, group_ready=False)
        incoming.close()
        name, message = first[1], first[2]
        errors = {'OSError': OSError, 'RuntimeError': RuntimeError}
        raise errors.get(name, RuntimeError)(message)
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not incoming.poll(remaining):
        _stop_process(process, group_ready=True)
        incoming.close()
        raise TimeoutError('Review deadline exhausted during ' + label)
    result = incoming.recv()
    incoming.close()
    process.join(.5)
    if process.is_alive():
        _stop_process(process, group_ready=True)
    if result[0] == 'ok':
        return result[1]
    name, message = result[1], result[2]
    errors = {
        'ValueError': ValueError,
        'OSError': OSError,
        'KeyError': KeyError,
        'TypeError': TypeError,
        'TimeoutError': TimeoutError,
    }
    raise errors.get(name, RuntimeError)(message)


def _review_evidence(path, cycle, snapshot, reviewed_at):
    from integrations.rea_video.analyze_cycle import review_evidence

    evidence, recheck = review_evidence(path, cycle, snapshot, reviewed_at)
    recheck()
    return evidence


def validate(request):
    if not isinstance(request, dict) or set(request) != FIELDS:
        raise ValueError('Require the exact documented retained-REA review request')
    if request['operation'] != OPERATION:
        raise ValueError('Only retained REA review recording is supported')
    if any(request[name] is not False for name in FALSE_FLAGS):
        raise ValueError('Publishing, payment and approval gates must remain false')
    for name in ('candidate_sha256', 'caption_sha256', 'package_sha256',
                 'review_archive_sha256', 'rea_receipt_sha256',
                 'submitted_review_sha256'):
        if not isinstance(request[name], str) or not SHA256.fullmatch(request[name]):
            raise ValueError('Invalid pinned ' + name)
    if type(request['timeout_seconds']) is not int or not 5 <= request['timeout_seconds'] <= 300:
        raise ValueError('Require a 5..300 second local review deadline')
    return request


def _file_digest(path, deadline):
    observed = hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            check_deadline(deadline)
            chunk = stream.read(1024 * 1024)
            if not chunk:
                return observed.hexdigest()
            observed.update(chunk)


def _tree_manifest(root, deadline):
    root = Path(root).absolute()
    no_symlinks(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('Retained input root must be a regular directory')
    manifest = {}
    total = 0
    for path in sorted(root.rglob('*')):
        check_deadline(deadline)
        no_symlinks(path)
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError('Retained input trees may contain only regular files')
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total += size
        if len(manifest) >= MAX_FILES or total > MAX_TREE_BYTES:
            raise ValueError('Retained input tree exceeds queue limits')
        manifest[relative] = _file_digest(path, deadline)
    if not manifest:
        raise ValueError('Retained input tree is empty')
    return manifest


def _copy_tree(source, target, manifest, deadline):
    if target.exists() or target.is_symlink():
        raise ValueError('Queue-owned input staging directory already exists')
    target.mkdir(parents=True, mode=0o700)
    try:
        for relative, expected in manifest.items():
            check_deadline(deadline)
            origin = source / relative
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            with os.fdopen(os.open(origin, flags), 'rb') as incoming:
                before = os.fstat(incoming.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError('Retained input changed to a non-regular file')
                observed = hashlib.sha256()
                with destination.open('xb') as outgoing:
                    while True:
                        check_deadline(deadline)
                        chunk = incoming.read(1024 * 1024)
                        if not chunk:
                            break
                        observed.update(chunk)
                        outgoing.write(chunk)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                after = os.fstat(incoming.fileno())
            if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or observed.hexdigest() != expected):
                raise ValueError('Retained input changed during queue admission: ' + relative)
        if _tree_manifest(target, deadline) != manifest:
            raise ValueError('Queue-owned input copy identity mismatch')
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise


def _load_json(path):
    no_symlinks(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_JSON:
        raise ValueError('Required JSON input is missing or oversized')
    value = json.loads(path.read_bytes(), parse_constant=lambda value: (_ for _ in ()).throw(
        ValueError('Nonfinite JSON value: ' + value)))
    if not isinstance(value, dict):
        raise ValueError('Required JSON input must be an object')
    return value


def _bind_cycle(snapshot, request):
    files = snapshot['files_sha256']
    if (snapshot['candidate_sha256'] != request['candidate_sha256']
            or files.get('delivery/captions.vtt') != request['caption_sha256']
            or files.get('delivery/package.json') != request['package_sha256']
            or files.get('delivery/review-package.zip') != request['review_archive_sha256']):
        raise ValueError('Completed cycle does not match immutable queue pins')


def _write_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def _sync_tree(root, deadline):
    directories = [Path(root)]
    for path in sorted(Path(root).rglob('*')):
        check_deadline(deadline)
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
        elif path.is_dir() and not path.is_symlink():
            directories.append(path)
    for path in reversed(directories):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _export_review(delivery, analysis, submitted, recorded, request, deadline):
    delivery.mkdir(mode=0o700)
    files = {
        'analysis.json': analysis,
        'submitted-review.json': submitted,
        'recorded-review.json': recorded,
    }
    for name, source in files.items():
        check_deadline(deadline)
        shutil.copyfile(source, delivery / name)
    manifest = {
        'schema_version': 1,
        'status': 'REVIEW_EXPORTED',
        'candidate_sha256': request['candidate_sha256'],
        'files_sha256': {name: _file_digest(delivery / name, deadline) for name in files},
        'publication_enabled': False,
        'paid_generation_enabled': False,
        'production_approved': False,
        'production_ready': False,
        'full_av_review': False,
        'scope': ('Exact retained REA receipt, submitted attestation, and recorded review; '
                  'no audiovisual, creative, production, or publishing approval.'),
    }
    _write_json(delivery / 'manifest.json', manifest)
    manifest_sha = _file_digest(delivery / 'manifest.json', deadline)
    with ZipFile(delivery / 'review-export.zip', 'x', compression=ZIP_DEFLATED) as archive:
        for name in sorted(set(files) | {'manifest.json'}):
            check_deadline(deadline)
            archive.write(delivery / name, name)
    return manifest_sha, _file_digest(delivery / 'review-export.zip', deadline)


def _validate_recorded_review(review, submitted, snapshot, request, evidence):
    from integrations.content_control.cycle_editorial import _text, _timestamp
    from integrations.content_control.cycle_review import CHECKS, _rea_diagnostic_findings

    checks = submitted.get('checks')
    if not isinstance(checks, dict) or not set(checks) <= set(CHECKS):
        raise ValueError('Submitted review checks are invalid')
    expected_fields = set(RECORDED_REVIEW_FIELDS)
    if 'voice_naturalness' in checks:
        expected_fields.add('listener_review')
    if 'full_audiovisual' in checks:
        expected_fields.add('watcher_review')
    findings = _rea_diagnostic_findings(evidence)
    if findings:
        expected_fields.add('diagnostic_findings')
    if set(review) != expected_fields:
        raise ValueError('Recorded review schema is invalid')
    feedback = review.get('feedback')
    normalized = review.get('checks')
    expected_status = 'REVISION_REQUIRED' if feedback else 'EDITORIAL_REVIEW_RECORDED'
    if (review.get('schema_version') != 1
            or review.get('status') != expected_status
            or review.get('candidate_sha256') != request['candidate_sha256']
            or review.get('reviewer') != _text(submitted.get('reviewer'), 'reviewer', 200)
            or review.get('reviewed_at') != _timestamp(submitted.get('reviewed_at'), 'reviewed_at')
            or not isinstance(_timestamp(review.get('recorded_at'), 'recorded_at'), str)
            or not isinstance(normalized, dict) or set(normalized) != set(checks)
            or not isinstance(feedback, list)
            or review.get('source_files_sha256') != snapshot['files_sha256']
            or review.get('submitted_review_sha256') != request['submitted_review_sha256']
            or review.get('independent_verification') is not False
            or review.get('scope') != ('Candidate-bound reviewer attestation only; supplied '
                                       'judgments are not independently verified.')
            or review.get('rea_diagnostics') != evidence
            or any(review.get(name) is not False for name in FALSE_FLAGS)):
        raise ValueError('Recorded review identity, status, or scope is invalid')
    for name, submitted_check in checks.items():
        recorded_check = normalized.get(name)
        expected_keys = {'passed', 'evidence'} | (
            {'feedback'} if submitted_check.get('passed') is False else set())
        if (not isinstance(submitted_check, dict)
                or type(submitted_check.get('passed')) is not bool
                or not isinstance(recorded_check, dict)
                or set(recorded_check) != expected_keys
                or recorded_check.get('passed') is not submitted_check['passed']):
            raise ValueError('Recorded review checks do not match the submission')
    if findings:
        if review.get('diagnostic_findings') != findings or not all(
                item in feedback for item in findings):
            raise ValueError('Recorded REA findings are missing or changed')
    elif 'diagnostic_findings' in review:
        raise ValueError('Unexpected recorded REA findings')


def _validate_success_receipt(receipt, request, completed):
    if (not isinstance(receipt, dict) or set(receipt) != SUCCESS_RECEIPT_FIELDS
            or receipt.get('schema_version') != 1 or receipt.get('status') != 'PASS'
            or receipt.get('operation') != OPERATION
            or receipt.get('candidate_sha256') != request['candidate_sha256']
            or receipt.get('provider_calls') != 0 or receipt.get('retryable') is not False
            or receipt.get('scope') != SCOPE
            or receipt.get('review_status') not in (
                'REVISION_REQUIRED', 'EDITORIAL_REVIEW_RECORDED')
            or receipt.get('rea_receipt_sha256') != request['rea_receipt_sha256']
            or receipt.get('submitted_review_sha256') != request['submitted_review_sha256']
            or receipt.get('source_inputs_unchanged') is not True
            or any(receipt.get(name) is not False for name in FALSE_FLAGS)):
        raise ValueError('Durable retained-review receipt schema or scope is invalid')
    for name in ('input_manifest_sha256', 'recorded_review_sha256',
                 'review_manifest_sha256', 'review_export_sha256'):
        if (not isinstance(receipt.get(name), str) or not SHA256.fullmatch(receipt[name])
                or receipt[name] != completed[name]):
            raise ValueError('Durable receipt does not bind completed output: ' + name)
    if receipt['review_status'] != completed['review_status']:
        raise ValueError('Durable receipt does not bind recorded review status')


def _verify_completed(attempt, request, deadline):
    validate(request)
    attempt = Path(attempt).absolute()
    cycle = attempt / 'inputs/cycle'
    analysis_root = attempt / 'inputs/rea-analysis'
    submitted = attempt / 'inputs/submitted-review.json'
    recorded = attempt / 'delivery/recorded-review.json'
    from integrations.content_control.cycle_review import inspect_cycle
    snapshot = _bounded_call(deadline, 'completed cycle inspection', inspect_cycle, cycle)
    _bind_cycle(snapshot, request)
    retained = _load_json(attempt / 'inputs/input-manifest.json')
    if (retained.get('schema_version') != 1
            or retained.get('candidate_sha256') != request['candidate_sha256']
            or retained.get('rea_receipt_sha256') != request['rea_receipt_sha256']
            or retained.get('submitted_review_sha256') != request['submitted_review_sha256']
            or retained.get('cycle_files_sha256') != _tree_manifest(cycle, deadline)
            or retained.get('rea_analysis_files_sha256') != _tree_manifest(analysis_root, deadline)):
        raise ValueError('Queue-owned retained input manifest changed')
    if (_file_digest(analysis_root / 'analysis.json', deadline) != request['rea_receipt_sha256']
            or _file_digest(submitted, deadline) != request['submitted_review_sha256']):
        raise ValueError('Queue-owned review input identity mismatch')
    submitted_value = _load_json(submitted)
    review = _load_json(recorded)
    evidence = _bounded_call(
        deadline, 'retained REA evidence verification', _review_evidence,
        analysis_root / 'analysis.json', cycle, snapshot, review.get('reviewed_at'))
    if evidence.get('receipt_sha256') != request['rea_receipt_sha256']:
        raise ValueError('Recorded review does not match the pinned REA receipt')
    _validate_recorded_review(review, submitted_value, snapshot, request, evidence)
    root_recorded = attempt / 'recorded-review.json'
    if (_file_digest(root_recorded, deadline) != _file_digest(recorded, deadline)
            or root_recorded.read_bytes() != recorded.read_bytes()):
        raise ValueError('Recorded review root and delivery copies differ')
    delivery = attempt / 'delivery'
    manifest = _load_json(delivery / 'manifest.json')
    expected = {'analysis.json': request['rea_receipt_sha256'],
                'submitted-review.json': request['submitted_review_sha256'],
                'recorded-review.json': _file_digest(recorded, deadline)}
    if (manifest.get('candidate_sha256') != request['candidate_sha256']
            or manifest.get('files_sha256') != expected
            or any(manifest.get(name) is not False for name in FALSE_FLAGS)):
        raise ValueError('Review export manifest changed')
    archive = delivery / 'review-export.zip'
    try:
        with ZipFile(archive) as bundle:
            members = bundle.infolist()
            if (len(members) != 4
                    or {item.filename for item in members} != set(expected) | {'manifest.json'}):
                raise ValueError('Review export archive inventory changed')
            for item in members:
                with bundle.open(item) as stream:
                    observed = hashlib.file_digest(stream, 'sha256').hexdigest()
                target = (_file_digest(delivery / 'manifest.json', deadline)
                          if item.filename == 'manifest.json' else expected[item.filename])
                if observed != target:
                    raise ValueError('Review export archive member changed: ' + item.filename)
    except BadZipFile as error:
        raise ValueError('Review export archive is invalid') from error
    return {
        'review_status': review['status'],
        'input_manifest_sha256': _file_digest(attempt / 'inputs/input-manifest.json', deadline),
        'recorded_review_sha256': expected['recorded-review.json'],
        'review_manifest_sha256': _file_digest(delivery / 'manifest.json', deadline),
        'review_export_sha256': _file_digest(archive, deadline),
    }


def check_completed(attempt_dir, request, durable_receipt, *, deadline=None):
    """Recheck retained bytes against the authoritative SQLite attempt receipt."""
    validate(request)
    deadline = deadline or time.monotonic() + request['timeout_seconds']
    attempt = Path(attempt_dir).absolute()
    completed = _verify_completed(attempt, request, deadline)
    on_disk_receipt = _load_json(attempt / 'cycle-review-adapter-receipt.json')
    if on_disk_receipt != durable_receipt:
        raise ValueError('Attempt receipt differs from the authoritative durable receipt')
    _validate_success_receipt(durable_receipt, request, completed)
    return completed


def run_job(request, attempt_dir, *, cycle_review_root=None,
            rea_analysis_root=None, submitted_review_path=None):
    validate(request)
    attempt = Path(attempt_dir).absolute()
    if not attempt.is_dir() or attempt.is_symlink():
        raise ValueError('Queue-owned attempt directory required')
    result = {
        'schema_version': 1, 'status': 'BLOCKED', 'operation': OPERATION,
        'candidate_sha256': request['candidate_sha256'], 'provider_calls': 0,
        'retryable': False, 'publication_enabled': False,
        'paid_generation_enabled': False, 'production_approved': False,
        'production_ready': False, 'full_av_review': False,
        'scope': SCOPE,
    }
    try:
        if cycle_review_root is None or rea_analysis_root is None or submitted_review_path is None:
            raise ValueError('Explicit trusted cycle, REA analysis, and submitted review paths required')
        deadline = time.monotonic() + request['timeout_seconds']
        cycle_source = Path(cycle_review_root).absolute()
        analysis_source = Path(rea_analysis_root).absolute()
        submitted_source = Path(submitted_review_path).absolute()
        from integrations.content_control.cycle_review import inspect_cycle, record_review
        snapshot = _bounded_call(
            deadline, 'source cycle inspection', inspect_cycle, cycle_source)
        _bind_cycle(snapshot, request)
        if (_file_digest(analysis_source / 'analysis.json', deadline) != request['rea_receipt_sha256']
                or _file_digest(submitted_source, deadline) != request['submitted_review_sha256']):
            raise ValueError('Retained review input hash mismatch')
        submitted_value = _load_json(submitted_source)
        _bounded_call(
            deadline, 'source REA evidence verification', _review_evidence,
            analysis_source / 'analysis.json', cycle_source, snapshot,
            submitted_value.get('reviewed_at'))
        cycle_manifest = _tree_manifest(cycle_source, deadline)
        analysis_manifest = _tree_manifest(analysis_source, deadline)
        inputs = attempt / 'inputs'
        inputs.mkdir(mode=0o700)
        _copy_tree(cycle_source, inputs / 'cycle', cycle_manifest, deadline)
        _copy_tree(analysis_source, inputs / 'rea-analysis', analysis_manifest, deadline)
        shutil.copyfile(submitted_source, inputs / 'submitted-review.json')
        if _file_digest(inputs / 'submitted-review.json', deadline) != request['submitted_review_sha256']:
            raise ValueError('Queue-owned submitted review identity mismatch')
        _write_json(inputs / 'input-manifest.json', {
            'schema_version': 1,
            'candidate_sha256': request['candidate_sha256'],
            'rea_receipt_sha256': request['rea_receipt_sha256'],
            'submitted_review_sha256': request['submitted_review_sha256'],
            'cycle_files_sha256': cycle_manifest,
            'rea_analysis_files_sha256': analysis_manifest,
        })
        recorded_path = attempt / 'recorded-review.json'
        recorded = _bounded_call(
            deadline, 'review recording', record_review,
            inputs / 'cycle', inputs / 'submitted-review.json', recorded_path,
            rea_analysis=inputs / 'rea-analysis/analysis.json')
        delivery = attempt / 'delivery'
        manifest_sha, archive_sha = _export_review(
            delivery, inputs / 'rea-analysis/analysis.json',
            inputs / 'submitted-review.json', recorded_path, request, deadline)
        completed = _verify_completed(attempt, request, deadline)
        if (_tree_manifest(cycle_source, deadline) != cycle_manifest
                or _tree_manifest(analysis_source, deadline) != analysis_manifest
                or _file_digest(submitted_source, deadline) != request['submitted_review_sha256']):
            raise ValueError('Operator-owned review inputs changed during consumption')
        _sync_tree(attempt, deadline)
        result.update(status='PASS', review_status=recorded['status'],
                      rea_receipt_sha256=request['rea_receipt_sha256'],
                      submitted_review_sha256=request['submitted_review_sha256'],
                      input_manifest_sha256=completed['input_manifest_sha256'],
                      recorded_review_sha256=completed['recorded_review_sha256'],
                      review_manifest_sha256=manifest_sha,
                      review_export_sha256=archive_sha,
                      source_inputs_unchanged=True)
    except (ValueError, OSError, KeyError, TypeError, TimeoutError, BadZipFile) as error:
        result['blocker'] = str(error) if isinstance(error, ValueError) else type(error).__name__
        result['retryable'] = isinstance(error, (OSError, TimeoutError))
    receipt = attempt / 'cycle-review-adapter-receipt.json'
    _write_json(receipt, result)
    return result
