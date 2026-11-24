"""Queue adapter for the existing, source-pinned unpublished picture producer."""
from contextlib import contextmanager
import hashlib
import importlib.util
import importlib.machinery
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import types

from integrations.agent_capacity import shared_admission_lock, collect_snapshot, recommend_capacity, AdmissionBusy
from integrations.owned_process import owned_process, interruptible_processes


def validate(request):
    fields = {'operation', 'source_commit', 'source_manifest_sha256', 'timeout_seconds',
              'publication_enabled', 'paid_generation_enabled'}
    if not isinstance(request, dict) or set(request) != fields:
        raise ValueError('Require the exact documented video job request')
    if request['operation'] != 'produce-episode1-review':
        raise ValueError('Only the existing Episode1 review producer is allowed')
    if request['publication_enabled'] is not False or request['paid_generation_enabled'] is not False:
        raise ValueError('Publication and paid generation must remain false')
    for name, length in (('source_commit', 40), ('source_manifest_sha256', 64)):
        if not isinstance(request[name], str) or not re.fullmatch('[0-9a-f]{' + str(length) + '}', request[name]):
            raise ValueError('Invalid pinned ' + name)
    if type(request['timeout_seconds']) is not int or not 30 <= request['timeout_seconds'] <= 1800:
        raise ValueError('Require a 30..1800 second production deadline')
    return request


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@contextmanager
def producer_module(root):
    """Load already-validated source without reusing another checkout's helpers.

    The queue is a foreground single consumer and holds shared admission while
    this namespace is installed. This is not a sandbox for untrusted code.
    """
    old_path = list(sys.path)
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    saved = {key: value for key, value in sys.modules.items() if key == 'scripts' or key.startswith('scripts.')}
    for key in saved:
        del sys.modules[key]
    sys.path.insert(0, str(root))
    # A later installed regular package named "scripts" otherwise overrides a
    # namespace directory, even when the verified checkout is first on sys.path.
    package = types.ModuleType('scripts')
    package.__package__ = 'scripts'
    package.__path__ = [str(root / 'scripts')]
    package.__spec__ = importlib.machinery.ModuleSpec('scripts', loader=None, is_package=True)
    package.__spec__.submodule_search_locations = package.__path__
    sys.modules['scripts'] = package
    try:
        spec = importlib.util.spec_from_file_location('_cyzor_pinned_picture_producer', root / 'scripts/produce_episode1_review.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if 'command_runner' not in inspect.signature(module.produce).parameters:
            raise ValueError('Pinned producer lacks owned-stage runner support')
        yield module
    finally:
        for key in list(sys.modules):
            if key == 'scripts' or key.startswith('scripts.'):
                del sys.modules[key]
        sys.modules.update(saved)
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_bytecode


def guarded_runner(lease_fd, cpus):
    """Each external stage owns a guardian and duplicates the admission lease."""
    def run(command, *, cwd, log, deadline, env):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Video job deadline exhausted')
        # Kernel affinity also bounds renderer grandchildren and ASR native threads.
        # This trusted wrapper is fixed adapter code, never job-supplied code.
        wrapper = 'import os,sys;os.sched_setaffinity(0,set(map(int,sys.argv[1].split(","))));os.execvpe(sys.argv[2],sys.argv[2:],os.environ)'
        argv = [sys.executable, '-c', wrapper, ','.join(map(str, cpus)), *command]
        safe_env = {key: value for key, value in env.items() if key in {
            'PATH', 'HOME', 'SYSTEMROOT', 'WINDIR', 'TMP', 'TEMP', 'TMPDIR',
            'HF_HOME', 'HF_HUB_CACHE', 'PICTURE_PYTHON', 'PICTURE_TEMP_DIR', 'CYZOR_REVIEW_BENCHMARKS'}}
        safe_env.update(PUBLICATION_ENABLED='false', PAID_GENERATION_ENABLED='false',
                        PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                        OPENBLAS_NUM_THREADS='2', OMP_NUM_THREADS='2', LANG='C.UTF-8', LC_ALL='C.UTF-8')
        with Path(log).open('xb') as output:
            with owned_process(argv, timeout=remaining, lease_fd=lease_fd, cwd=cwd,
                               env=safe_env, stdout=output, stderr=subprocess.STDOUT) as process:
                result = process.wait()
        if result:
            raise RuntimeError('Owned video stage failed; inspect the attempt log')
    return run


def check_completed(directory, expected_source):
    """Do not turn pipeline completion into creative or publishing approval."""
    path = directory / 'run.json'
    receipt = json.loads(path.read_text())
    if (receipt.get('status') != 'AWAITING_REVIEW' or receipt.get('technical_status') != 'PASS'
            or receipt.get('publication_enabled') is not False or receipt.get('production_approved') is not False
            or receipt.get('full_av_review') is not False or receipt.get('source_inputs_unchanged') is not True
            or receipt.get('renderer_scratch_cleaned') is not True
            or receipt.get('source_sha256') != expected_source['source_files']):
        raise ValueError('Pipeline did not complete a source-bound unpublished review packet')
    artifacts = receipt.get('artifacts_sha256')
    if not isinstance(artifacts, dict) or not {'video.mp4', 'captions.vtt', 'encoded-verification.json', 'audio-verification.json'} <= artifacts.keys():
        raise ValueError('Required review artifacts missing')
    for name, expected in artifacts.items():
        file = directory / name
        if Path(name).name != name or file.is_symlink() or not file.is_file() or digest(file) != expected:
            raise ValueError('Review artifact identity changed')
    if receipt.get('candidate_sha256') != digest(directory / 'video.mp4'):
        raise ValueError('Candidate identity changed')
    return receipt


def sync_packet(directory):
    """Flush generated bytes and directory entries before SQLite can accept PASS."""
    for path in directory.iterdir():
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def run_job(request, attempt_dir, *, content_control_root=None, video_python=None, picture_python=None):
    validate(request)
    attempt_dir = Path(attempt_dir)
    if not attempt_dir.is_dir() or attempt_dir.is_symlink():
        raise ValueError('Queue-owned attempt directory required')
    result = {'schema_version': 1, 'status': 'BLOCKED', 'operation': request['operation'],
              'publication_enabled': False, 'paid_generation_enabled': False,
              'production_ready': False, 'production_approved': False, 'full_av_review': False,
              'scope': 'Local queue execution and technical review packet only; no audiovisual or publishing approval',
              'source_commit': request['source_commit'], 'source_manifest_sha256': request['source_manifest_sha256']}
    try:
        if sys.version_info < (3, 11):
            raise ValueError('Queue video adapter requires Python 3.11 or newer')
        if not content_control_root or not video_python or not picture_python:
            raise ValueError('Operator must provide the Content Control checkout and Python runtimes')
        if not sys.platform.startswith('linux') or not hasattr(os, 'sched_getaffinity'):
            raise ValueError('Video queue requires Linux or WSL2 process and CPU ownership')
        root = Path(content_control_root).resolve(strict=True)
        # Preserve the venv entry path: resolving its interpreter symlink would
        # silently select the base Python and lose the installed environment.
        runtimes = [Path(value).absolute() for value in (video_python, picture_python)]
        if any(not value.is_file() or not os.access(value, os.X_OK) for value in runtimes):
            raise ValueError('Operator runtime must be an executable local file')
        from integrations.content_control.runtime_doctor import describe_source, inspect_runtime
        from integrations.content_control.cycle_av_review import automated_review_command, read_automated_review
        with interruptible_processes(), shared_admission_lock() as lease:
            source = describe_source(root, expected_commit=request['source_commit'], lease_fd=lease)
            if source['source_manifest_sha256'] != request['source_manifest_sha256']:
                raise ValueError('Approved source manifest does not match checkout')
            runtime = inspect_runtime(root, str(runtimes[0]), str(runtimes[1]), lease_fd=lease)
            result['runtime_prerequisites'] = runtime
            if runtime.get('status') != 'PASS':
                raise ValueError('Video runtime prerequisites are blocked')
            budget = recommend_capacity(collect_snapshot(), requested_workers=1,
                                        worker_memory_mb=1536, cpu_per_worker=2, max_workers=1)
            result['capacity'] = budget
            if budget['admitted_workers'] != 1:
                raise ValueError('Fresh host capacity does not admit video production')
            cpus = sorted(os.sched_getaffinity(0))[:2]
            if len(cpus) < 2:
                raise ValueError('Two CPU affinity slots required')
            result['cpu_affinity'] = cpus
            runner = guarded_runner(lease, cpus)
            deadline = time.monotonic() + request['timeout_seconds']
            with producer_module(root) as producer:
                produced = producer.produce(attempt_dir / 'review', python=str(runtimes[0]),
                    picture_python=str(runtimes[1]), timeout=request['timeout_seconds'], root=root,
                    command_runner=runner)
            if produced.get('status') != 'AWAITING_REVIEW':
                result['pipeline_failed_step'] = produced.get('failed_step')
                raise ValueError('Existing producer left a blocked review packet')
            after = describe_source(root, expected_commit=request['source_commit'], lease_fd=lease)
            if after['source_manifest_sha256'] != source['source_manifest_sha256']:
                raise ValueError('Source checkout changed during production')
            receipt = check_completed(attempt_dir / 'review', source)
            report = attempt_dir / 'automated-review.json'
            result['pipeline_failed_step'] = 'automated-review'
            runner(automated_review_command(attempt_dir / 'review', report, receipt, deadline),
                   cwd=Path(__file__).resolve().parents[2], log=attempt_dir / 'automated-review.log',
                   deadline=deadline, env=os.environ)
            report_bytes = read_automated_review(report, receipt['candidate_sha256'],
                                                 receipt['artifacts_sha256']['captions.vtt'], sync=True)
            report_sha = hashlib.sha256(report_bytes).hexdigest()
            result.pop('pipeline_failed_step')
            sync_packet(attempt_dir / 'review')
            result.update(status='PASS', review_status='AWAITING_REVIEW',
                          candidate_sha256=receipt['candidate_sha256'],
                          automated_review_sha256=report_sha,
                          pipeline_receipt_sha256=digest(attempt_dir / 'review/run.json'),
                          artifact_directory='review', source_inputs_unchanged=True)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError, AdmissionBusy) as error:
        result['blocker'] = str(error) if isinstance(error, ValueError) else type(error).__name__
        # Shared-admission contention happens before this adapter can launch a
        # production stage, so replay is safe and may succeed once the other
        # bounded batch releases the host.  All other blockers stay opt-in
        # non-retryable: their external outcome or operator fix may be unknown.
        if isinstance(error, AdmissionBusy):
            result['retryable'] = True
    # A killed consumer never reaches this write or queue.finish; recovery leaves
    # INTERRUPTED and preserves partial files without replaying the job.
    with (attempt_dir / 'video-adapter-receipt.json').open('x') as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    descriptor = os.open(attempt_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return result
