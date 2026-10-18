"""Run a reviewed repository job through Content Control's local Node/Python lane."""
import argparse
import hashlib
import json
import os
import re
import signal
import stat
import tempfile
import threading
import time
import uuid
from pathlib import Path
import subprocess


MAX_JOB_BYTES = 4 * 1024 * 1024  # Matches Content Control's local JSON ceiling.
MAX_OUTPUT_JSON_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
PLATFORMS = {'kdp', 'redbubble', 'teepublic', 'zazzle', 'spreadshirt'}
REVIEW_FLAGS = ('publication_enabled', 'production_ready', 'paid_generation_enabled', 'marketplace_ready')
REVIEW_CHECKS = {'official_template', 'rights', 'editorial', 'independent_visual_review',
                 'marketplace_account', 'platform_preview', 'release_approval'}
COMMON_ARTIFACTS = {'print.png', 'art-mask.png', 'text-mask.png', 'metadata.json',
                    'research.json', 'provenance.json'}
KDP_ARTIFACTS = {'cover.pdf', 'interior.pdf', 'interior.receipt.json'}
REVIEW_TIMEOUT_SECONDS = 260
REVIEW_STOP_SECONDS = 12  # Allow the pinned Node supervisor's five-second group cleanup.


def run_review_child(argv, *, check=True, timeout=REVIEW_TIMEOUT_SECONDS, checkpoint=lambda: None):
    # Python signal handlers belong to the main thread. Reject unsupported callers
    # before spawning rather than silently omitting cancellation forwarding.
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('REVIEW_MAIN_THREAD_REQUIRED')
    cancelled = False
    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True
    previous = {}
    child = None
    deadline = time.monotonic() + timeout
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, cancel)
        checkpoint()
        if cancelled:
            raise InterruptedError('REVIEW_CANCELLED')
        child = subprocess.Popen(argv)
        while True:
            checkpoint()
            if cancelled:
                raise InterruptedError('REVIEW_CANCELLED')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                code = child.wait(timeout=min(.1, remaining))
            except subprocess.TimeoutExpired:
                continue
            # Cancellation is sticky, including when a terminating child exits zero.
            if cancelled:
                raise InterruptedError('REVIEW_CANCELLED')
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(argv, timeout)
            if check and code:
                raise subprocess.CalledProcessError(code, argv)
            result = subprocess.CompletedProcess(argv, code)
            break
    finally:
        try:
            if child is not None and child.poll() is None:
                # Do not kill Node immediately: it owns a separate Python process
                # group and must finish its TERM/KILL escalation before exiting.
                child.terminate()
                try:
                    child.wait(timeout=REVIEW_STOP_SECONDS)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    # Signals received after wait succeeded but during handler restoration must
    # not be lost to a return value already computed inside the try block.
    if cancelled:
        raise InterruptedError('REVIEW_CANCELLED')
    checkpoint()
    return result


def validate_inventory(files, platform):
    if not isinstance(files, dict) or not 1 <= len(files) <= 32:
        raise ValueError('ARTIFACT_BATCH_INVALID')
    if any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', name)
           for name in files):
        raise ValueError('ARTIFACT_NAME_INVALID')
    required = COMMON_ARTIFACTS | (KDP_ARTIFACTS if platform == 'kdp' else set())
    if not required.issubset(files):
        raise ValueError('ARTIFACT_SET_INCOMPLETE')


def validate_result(result, platform):
    if (not isinstance(result, dict) or type(result.get('schema_version')) is not int
            or result['schema_version'] != 1 or result.get('platform') != platform
            or result.get('status') != 'REVIEW_REQUIRED'
            or any(result.get(flag) is not False for flag in REVIEW_FLAGS)):
        raise ValueError('RESULT_SCOPE_INVALID')
    checks = result.get('remaining_checks')
    if (not isinstance(checks, list) or any(not isinstance(c, str) or not c for c in checks)
            or len(set(checks)) != len(checks) or not REVIEW_CHECKS.issubset(checks)):
        raise ValueError('RESULT_SCOPE_INVALID')


def validate_manifest(manifest, platform):
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 1 or manifest.get('platform') != platform
            or manifest.get('publication_enabled') is not False):
        raise ValueError('MANIFEST_SCOPE_INVALID')


def output_chunks(path, limit):
    # Descriptor checks also cover replacement between path validation and open.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('OUTPUT_FILE_INVALID')
        if info.st_size > limit:
            raise ValueError('OUTPUT_TOO_LARGE')
        source = os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise
    with source:
        total = 0
        while True:
            chunk = source.read(min(1024 * 1024, limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError('OUTPUT_TOO_LARGE')
            yield chunk


def output_json(path):
    body = b''.join(output_chunks(path, MAX_OUTPUT_JSON_BYTES))
    return json.loads(body.decode('utf-8', errors='strict'))

def capture_job(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('JOB_FILE_INVALID')
        source = os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise
    with source:
        body = source.read(MAX_JOB_BYTES + 1)
    if len(body) > MAX_JOB_BYTES:
        raise ValueError('JOB_TOO_LARGE')
    return body


def write_receipt(output, result, *, checkpoint=lambda: None):
    # The final path becomes visible only after complete bytes have been synced.
    # A hard link commits without overwriting a concurrent/existing destination.
    checkpoint()
    body = (json.dumps(result, indent=2, allow_nan=False)+'\n').encode('utf-8')
    directory = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    name = '.mf-receipt-'+uuid.uuid4().hex+'.tmp'
    staged = False
    committed = False
    identity = None
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        staged = True
        try:
            info = os.fstat(fd)
            identity = (info.st_dev, info.st_ino)
            remaining = memoryview(body)
            while remaining:
                checkpoint()
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError('RECEIPT_WRITE_INCOMPLETE')
                remaining = remaining[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        checkpoint()
        os.link(name, 'money-factory-receipt.json', src_dir_fd=directory,
                dst_dir_fd=directory, follow_symlinks=False)
        committed = True
        os.unlink(name, dir_fd=directory)
        staged = False
        os.fsync(directory)
        # Cancellation after the exclusive link cannot undo that commit. The
        # existing recovery path retains the complete receipt and rejects success.
        checkpoint()
    except BaseException as error:
        # A signal/error can arrive after link succeeds but before its return is
        # recorded. Identify our inode instead of incorrectly claiming rollback.
        if not committed and identity is not None:
            try:
                final = os.stat('money-factory-receipt.json', dir_fd=directory, follow_symlinks=False)
                committed = (final.st_dev, final.st_ino) == identity
            except OSError:
                pass
        if staged:
            try:
                os.unlink(name, dir_fd=directory)
            except OSError:
                error.add_note('RECEIPT_STAGING_CLEANUP_REQUIRED')
        if committed:
            # Never remove or rewrite a committed receipt to pretend rollback.
            raise RuntimeError('RECEIPT_COMMITTED_RECOVERY_REQUIRED') from error
        raise
    finally:
        os.close(directory)


def run(job, content_control, font, output):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('REVIEW_MAIN_THREAD_REQUIRED')
    cancelled = False
    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True
    def checkpoint():
        if cancelled:
            raise InterruptedError('REVIEW_CANCELLED')
    previous = {}
    result = None
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, cancel)
        result = _run_review(job, content_control, font, output, checkpoint)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    # A late signal during restoration is still cancellation. The completed
    # receipt must be reconciled, not deleted or reported as a rolled-back run.
    try:
        checkpoint()
    except InterruptedError as error:
        raise RuntimeError('RECEIPT_COMMITTED_RECOVERY_REQUIRED') from error
    return result


def _run_review(job, content_control, font, output, checkpoint):
    checkpoint()
    job=Path(job).resolve(strict=True)
    root=Path(content_control).resolve(strict=True)
    body=capture_job(job)
    checkpoint()
    spec=json.loads(body.decode('utf-8', errors='strict'))
    if not isinstance(spec, dict):
        raise ValueError('JOB_INVALID')
    if spec.get('publication_enabled') is not False or spec.get('paid_generation_enabled') is not False:
        raise ValueError('REVIEW_ONLY_REQUIRED')
    platform = spec.get('platform')
    if not isinstance(platform, str) or platform not in PLATFORMS:
        raise ValueError('PLATFORM_BLOCKED')
    output=Path(output).resolve()
    if output.exists():
        raise ValueError('OUTPUT_EXISTS')
    # Validate, execute and receipt one byte version. The caller's path may be
    # replaced or removed while the child runs; never reopen it for provenance.
    with tempfile.TemporaryDirectory(prefix='pod-mf-job-') as tmp:
        snapshot=Path(tmp)/'job.json'
        with snapshot.open('xb') as target:
            target.write(body)
        snapshot.chmod(0o400)
        checkpoint()
        run_review_child(['node',str(root/'scripts/pod_review_cli.mjs'),str(snapshot),
                         str(Path(font).resolve(strict=True)),str(output)],
                         check=True,timeout=REVIEW_TIMEOUT_SECONDS,checkpoint=checkpoint)
    checkpoint()
    result=validate_review_output(output, platform, checkpoint=checkpoint)
    result['input_sha256']=hashlib.sha256(body).hexdigest()
    write_receipt(output, result, checkpoint=checkpoint)
    return result


def validate_review_output(output, platform, *, checkpoint=lambda: None):
    """Read/hash one existing review package without generating or writing files."""
    output = Path(output)
    checkpoint()
    result=output_json(output/'result.json')
    checkpoint()
    validate_result(result, platform)
    manifest=output_json(output/'package/manifest.json')
    checkpoint()
    validate_manifest(manifest, platform)
    expected=manifest.pop('package_sha256')
    encoded=json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    if hashlib.sha256(encoded).hexdigest()!=expected or result['package_sha256']!=expected:
        raise ValueError('MANIFEST_HASH_MISMATCH')
    files=manifest['files']
    validate_inventory(files, platform)
    total=0
    for name,sha in files.items():
        checkpoint()
        base=(output/'package').resolve()
        # Inventory names are flat. Keep the final component unresolved so
        # output_chunks' O_NOFOLLOW cannot be bypassed by a preexisting symlink.
        path=base/name
        digest=hashlib.sha256()
        for chunk in output_chunks(path, MAX_ARTIFACT_BYTES):
            checkpoint()
            total+=len(chunk)
            if total>MAX_PACKAGE_BYTES:
                raise ValueError('PACKAGE_TOO_LARGE')
            digest.update(chunk)
        if digest.hexdigest()!=sha:
            raise ValueError('ARTIFACT_HASH_MISMATCH')
    checkpoint()
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('job','content-control','font','output'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.job,args.content_control,args.font,args.output)))
