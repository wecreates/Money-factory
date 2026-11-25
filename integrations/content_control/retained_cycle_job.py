"""Restore an exact unpublished cycle into a durable local queue attempt."""
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import BadZipFile, ZipFile

from integrations.content_control.cycle_checkpoint import (
    FILES, FLAGS, MANIFEST_LIMIT, OPTIONAL_FILES, TOTAL_LIMIT, _identities, restore_checkpoint,
)
from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control.review_package import SHA, digest, no_symlinks
from integrations.owned_process import owned_process


ADAPTER = 'content-control-retained-cycle'
OPERATION = 'restore-unpublished-cycle'
RECEIPT = 'retained-cycle-adapter-receipt.json'
CHECKPOINT_LIMIT = TOTAL_LIMIT + MANIFEST_LIMIT
IDENTITY_FIELDS = {
    'candidate_sha256': 'delivery/video.mp4',
    'caption_sha256': 'delivery/captions.vtt',
    'brief_sha256': 'brief.json',
    'pipeline_receipt_sha256': 'cycle.json',
    'package_sha256': 'delivery/package.json',
    'archive_sha256': 'delivery/review-package.zip',
}


def validate(request):
    required = {'operation', 'checkpoint_sha256', 'timeout_seconds', *IDENTITY_FIELDS,
                'publication_enabled', 'paid_generation_enabled'}
    if not isinstance(request, dict) or set(request) != required or request['operation'] != OPERATION:
        raise ValueError('Invalid retained cycle request fields or operation')
    if any(request[flag] is not False for flag in ('publication_enabled', 'paid_generation_enabled')):
        raise ValueError('Publishing and paid generation must remain false')
    if any(not isinstance(request[key], str) or not SHA.fullmatch(request[key])
           for key in ('checkpoint_sha256', *IDENTITY_FIELDS)):
        raise ValueError('Exact retained checkpoint and cycle identities required')
    if type(request['timeout_seconds']) is not int or not 5 <= request['timeout_seconds'] <= 300:
        raise ValueError('Retained cycle restore requires a 5..300 second deadline')
    return request


def check_completed(attempt, request):
    """Reopen the queue-owned bytes against the immutable checkpoint and media pins."""
    validate(request)
    attempt = Path(attempt).absolute()
    checkpoint = attempt / 'checkpoint.zip'
    cycle = attempt / 'cycle'
    no_symlinks(checkpoint)
    if (not checkpoint.is_file() or checkpoint.stat().st_size > CHECKPOINT_LIMIT
            or digest(checkpoint) != request['checkpoint_sha256']):
        raise ValueError('Retained checkpoint identity mismatch')
    with ZipFile(checkpoint) as bundle:
        info = bundle.getinfo('checkpoint.json')
        if info.file_size > MANIFEST_LIMIT:
            raise ValueError('Retained checkpoint manifest is oversized')
        manifest = json.loads(bundle.read(info))
    files = manifest.get('files') if isinstance(manifest, dict) else None
    if (not isinstance(files, dict) or not FILES <= set(files) <= FILES | OPTIONAL_FILES
            or any(manifest.get(flag) is not False for flag in FLAGS)
            or any(not isinstance(files[path], dict) or files[path].get('sha256') != request[key]
                   for key, path in IDENTITY_FIELDS.items())
            or _identities(cycle, files) != files):
        raise ValueError('Restored members differ from immutable checkpoint or cycle identities')
    # The checkpoint has only two fixed subdirectories. Never walk unexpected subtrees.
    for relative in ('', 'delivery', 'render'):
        directory = cycle / relative
        expected = {Path(path).name for path in files if str(Path(path).parent) == (relative or '.')}
        if not relative:
            expected.update(('delivery', 'render'))
        for child in directory.iterdir():
            if child.name not in expected or child.is_symlink():
                raise ValueError('Retained cycle inventory changed')
    snapshot = inspect_cycle(cycle)
    package_path = cycle / 'delivery/package.json'
    package = json.loads(package_path.read_text())
    if (any(snapshot['files_sha256'][path] != request[key] for key, path in IDENTITY_FIELDS.items())
            or snapshot['cycle'].get('archive_sha256') != request['archive_sha256']
            or snapshot['cycle'].get('production_ready') is not False
            or any(package.get(flag) is not False for flag in FLAGS)
            or digest(package_path) != request['package_sha256']
            or digest(checkpoint) != request['checkpoint_sha256']):
        raise ValueError('Retained cycle or checkpoint changed during verification')
    return {
        'status': 'PASS', 'review_status': 'AWAITING_REVIEW', 'operation': OPERATION,
        'artifact_directory': 'cycle', 'checkpoint_sha256': request['checkpoint_sha256'],
        'timeout_seconds': request['timeout_seconds'],
        **{key: request[key] for key in IDENTITY_FIELDS}, 'provider_calls': 0, **FLAGS,
    }


def _blocked(reason):
    return {'status': 'BLOCKED', 'operation': OPERATION, 'reason': reason,
            'provider_calls': 0, **FLAGS}


def _restore_job(request, attempt, source):
    """Run inside the guardian, including receipt and artifact fsync calls."""
    receipt_path = attempt / RECEIPT
    no_symlinks(attempt)
    if not attempt.is_dir() or any(attempt.iterdir()):
        raise ValueError('Fresh queue-owned attempt directory required')
    try:
        no_symlinks(source)
        if not source.is_file() or source.stat().st_size > CHECKPOINT_LIMIT:
            raise ValueError('Trusted checkpoint is missing or oversized')
        checkpoint = attempt / 'checkpoint.zip'
        remaining = CHECKPOINT_LIMIT
        with source.open('rb') as incoming, checkpoint.open('xb') as outgoing:
            while chunk := incoming.read(1024 * 1024):
                remaining -= len(chunk)
                if remaining < 0:
                    raise ValueError('Checkpoint grew past the allowed byte limit')
                outgoing.write(chunk)
        restore_checkpoint(checkpoint, attempt / 'cycle', expected_sha256=request['checkpoint_sha256'])
        receipt = check_completed(attempt, request)
        # Flush the restored files and then their directory entries before SQLite completion.
        for directory, _, names in os.walk(attempt, topdown=False):
            for name in names:
                with (Path(directory) / name).open('rb') as stream:
                    os.fsync(stream.fileno())
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        if digest(source) != request['checkpoint_sha256']:
            raise ValueError('Trusted checkpoint changed during the attempt')
    except (ValueError, OSError, KeyError, TypeError, BadZipFile) as error:
        receipt = _blocked(str(error) if isinstance(error, ValueError) else type(error).__name__)
    with receipt_path.open('x') as stream:
        json.dump(receipt, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    for directory in (attempt, attempt.parent, attempt.parent.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return receipt


def _worker_command(request, attempt, source):
    return [sys.executable, '-m', 'integrations.content_control.retained_cycle_job',
            json.dumps(request, sort_keys=True, allow_nan=False), str(attempt), str(source)]


def run_job(request, attempt_dir, *, cycle_checkpoint_path=None):
    validate(request)
    if any(os.environ.get(flag, 'false').lower() != 'false'
           for flag in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')):
        return _blocked('Publishing and paid generation must remain false')
    if cycle_checkpoint_path is None:
        return _blocked('Explicit trusted checkpoint archive path required')
    if not sys.platform.startswith('linux'):
        return _blocked('Retained cycle restoration requires Linux or WSL2 process ownership')
    attempt = Path(attempt_dir).absolute()
    source = Path(cycle_checkpoint_path).absolute()
    argv = _worker_command(request, attempt, source)
    env = {'PUBLICATION_ENABLED': 'false', 'PAID_GENERATION_ENABLED': 'false',
           'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    with owned_process(argv, timeout=request['timeout_seconds'],
                       cwd=Path(__file__).resolve().parents[2], env=env,
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL) as process:
        output, _ = process.communicate()
    if process.returncode == 125:
        return _blocked('Retained cycle restore deadline exhausted or interrupted')
    if process.returncode != 0:
        return _blocked('Owned retained cycle worker failed before completion')
    return json.loads(output)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Internal retained cycle invocation is invalid')
    request = validate(json.loads(sys.argv[1]))
    print(json.dumps(_restore_job(request, Path(sys.argv[2]), Path(sys.argv[3])), allow_nan=False))
