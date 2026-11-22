"""Explicit fresh-content jobs on the existing durable local agent queue.

Jobs contain an editorial brief, never executable commands or runtime paths.
The trusted host owns runtime selection and a guardian owns the entire cycle.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from integrations.agent_capacity import shared_admission_lock, collect_snapshot, recommend_capacity, AdmissionBusy
from integrations.owned_process import interruptible_processes
from integrations.content_control.video_job import guarded_runner, digest, sync_packet

ROOT = Path(__file__).resolve().parents[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def brief_digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def validate(request):
    fields = {'operation', 'brief', 'brief_sha256', 'timeout_seconds',
              'publication_enabled', 'paid_generation_enabled'}
    if not isinstance(request, dict) or set(request) != fields:
        raise ValueError('Require the exact documented content-cycle request')
    if request['operation'] != 'produce-content-cycle':
        raise ValueError('Only produce-content-cycle is supported')
    if request['publication_enabled'] is not False or request['paid_generation_enabled'] is not False:
        raise ValueError('Publication and paid generation must remain false')
    if type(request['timeout_seconds']) is not int or not 30 <= request['timeout_seconds'] <= 1800:
        raise ValueError('Require a 30..1800 second cycle deadline')
    if not isinstance(request['brief'], dict) or len(canonical(request['brief']).encode()) > 120000:
        raise ValueError('A bounded inline editorial brief is required')
    if (not isinstance(request['brief_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', request['brief_sha256'])
            or request['brief_sha256'] != brief_digest(request['brief'])):
        raise ValueError('Editorial brief identity mismatch')
    from integrations.content_control.cycle_editorial import compile_editorial
    compile_editorial(request['brief'])
    return request


def _json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4*1024*1024:
        raise ValueError('Missing or unsafe cycle receipt')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('Cycle receipt must be an object')
    return value


def check_completed(directory, expected_brief_sha256):
    """Independently bind queue success to delivered bytes; never approve them."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Missing cycle output directory')
    if any(path.is_symlink() for path in directory.rglob('*')):
        raise ValueError('Symlink cycle artifacts are forbidden')
    receipt = _json(directory/'cycle.json')
    if (receipt.get('status') != 'AWAITING_REVIEW' or receipt.get('technical_status') != 'PASS'
            or any(receipt.get(key) is not False for key in
                   ('publication_enabled', 'paid_generation_enabled', 'production_approved', 'full_av_review',
                    'production_ready', 'factual_review', 'competitor_comparison'))
            or receipt.get('brief_sha256') != expected_brief_sha256):
        raise ValueError('Cycle did not complete a bound unpublished review')
    if 'revision_lineage' in receipt:
        from integrations.content_control.cycle_lineage import validate_lineage
        validate_lineage(receipt['revision_lineage'], expected_brief_sha256)
    candidate = directory/'render/video.mp4'
    if not candidate.is_file() or digest(candidate) != receipt.get('candidate_sha256'):
        raise ValueError('Cycle candidate identity mismatch')
    if digest(directory/'editorial.json') != receipt.get('editorial_sha256'):
        raise ValueError('Cycle editorial identity mismatch')
    editorial = _json(directory/'editorial.json')
    if digest(directory/'brief.json') != expected_brief_sha256:
        raise ValueError('Cycle input brief identity mismatch')
    from integrations.content_control.cycle_editorial import compile_editorial
    if editorial != compile_editorial(_json(directory/'brief.json')):
        raise ValueError('Editorial does not derive from the queued brief')
    from integrations.content_control.cycle_package import editorial_digest
    canonical_editorial_sha = editorial_digest(editorial)
    if digest(directory/'delivery/package.json') != receipt.get('package_sha256'):
        raise ValueError('Cycle package identity mismatch')
    package = _json(directory/'delivery/package.json')
    if (package.get('candidate_sha256') != receipt['candidate_sha256']
            or package.get('status') != 'AWAITING_REVIEW'
            or package.get('technical_status') != 'PASS'
            or any(package.get(key) is not False for key in
                   ('publication_enabled', 'paid_generation_enabled', 'production_approved',
                    'full_av_review', 'production_ready'))):
        raise ValueError('Package belongs to a different candidate or review scope')
    if (digest(directory/'delivery/video.mp4') != receipt['candidate_sha256']
            or digest(directory/'delivery/editorial.json') != receipt['editorial_sha256']
            or package.get('editorial_sha256') != canonical_editorial_sha
            or digest(directory/'delivery/render.json') != digest(directory/'render/render.json')
            or package.get('render_receipt_sha256') != digest(directory/'render/render.json')
            or digest(directory/'delivery/captions.vtt') != digest(directory/'render/captions.vtt')
            or package.get('caption_sha256') != digest(directory/'render/captions.vtt')):
        raise ValueError('Delivered artifacts do not bind the same editorial and candidate')
    rendered = _json(directory/'render/render.json')
    if (rendered.get('candidate_sha256') != receipt['candidate_sha256']
            or rendered.get('editorial_sha256') != canonical_editorial_sha
            or rendered.get('caption_sha256') != package['caption_sha256']
            or rendered.get('status') != 'AWAITING_REVIEW'
            or rendered.get('technical_status') != 'PASS'
            or any(rendered.get(key) is not False for key in
                   ('publication_enabled', 'paid_generation_enabled', 'production_approved', 'full_av_review'))):
        raise ValueError('Renderer receipt identity or approval mismatch')
    archive = directory/'delivery/review-package.zip'
    if not archive.is_file() or digest(archive) != receipt.get('archive_sha256'):
        raise ValueError('Package archive identity mismatch')
    files = package.get('files_sha256')
    if not isinstance(files, dict) or not {'video.mp4', 'index.html', 'captions.vtt', 'render.json', 'editorial.json'} <= files.keys():
        raise ValueError('Package artifact map is missing')
    for name, expected in files.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name:
            raise ValueError('Unsafe package artifact path')
        artifact = directory/'delivery'/relative
        if not artifact.is_file() or digest(artifact) != expected:
            raise ValueError('Delivered package artifact identity mismatch')
    return receipt


def run_job(request, attempt_dir, *, voice_python=None, voice_root=None, transcription_python=None):
    validate(request)
    attempt_dir = Path(attempt_dir).absolute()
    if not attempt_dir.is_dir() or attempt_dir.is_symlink():
        raise ValueError('A queue-owned attempt directory is required')
    result = {'schema_version': 1, 'status': 'BLOCKED', 'operation': request['operation'],
              'brief_sha256': request['brief_sha256'], 'publication_enabled': False,
              'paid_generation_enabled': False, 'production_ready': False,
              'production_approved': False, 'full_av_review': False,
              'scope': 'One admitted unpublished cycle; no unattended service or creative approval'}
    try:
        if not sys.platform.startswith('linux') or not hasattr(os, 'sched_getaffinity'):
            raise ValueError('Cycle queue requires Linux/WSL2 process ownership')
        if not voice_python or not voice_root:
            raise ValueError('Host must provide explicit voice runtime and source checkout')
        runtime, root = Path(voice_python).absolute(), Path(voice_root).resolve(strict=True)
        if not runtime.is_file() or not os.access(runtime, os.X_OK) or not (root/'scripts/v2_free_voice.py').is_file():
            raise ValueError('Voice runtime or trusted source checkout is unavailable')
        if transcription_python is not None:
            transcription_python = Path(transcription_python).absolute()
            if not transcription_python.is_file() or not os.access(transcription_python, os.X_OK):
                raise ValueError('Host transcription runtime must be an executable file')
        with (attempt_dir/'brief.json').open('x') as stream:
            stream.write(canonical(request['brief']))
            stream.flush(); os.fsync(stream.fileno())
        deadline = time.monotonic() + request['timeout_seconds']
        with interruptible_processes(), shared_admission_lock() as lease:
            budget = recommend_capacity(collect_snapshot(), requested_workers=1,
                                        worker_memory_mb=2048, cpu_per_worker=2, max_workers=1)
            result['capacity'] = budget
            if budget['admitted_workers'] != 1:
                raise ValueError('Fresh host capacity does not admit a content cycle')
            cpus = sorted(os.sched_getaffinity(0))[:2]
            if len(cpus) < 2:
                raise ValueError('Two CPU affinity slots are required')
            result['cpu_affinity'] = cpus
            # Fixed trusted bootstrap; user input is only JSON data and arguments.
            bootstrap = ('import sys;from integrations.content_control.complete_cycle import run_cycle;'
                         'r=run_cycle(sys.argv[1],sys.argv[2],voice_python=sys.argv[3],'
                         'voice_root=sys.argv[4],timeout=int(sys.argv[5]),transcription_python=sys.argv[6] or None);'
                         'sys.exit(0 if r.get("status")=="AWAITING_REVIEW" else 2)')
            guarded_runner(lease, cpus)(
                [sys.executable, '-c', bootstrap, str(attempt_dir/'brief.json'),
                 str(attempt_dir/'cycle'), str(runtime), str(root), str(request['timeout_seconds']),
                 str(transcription_python) if transcription_python else ''],
                cwd=ROOT, log=attempt_dir/'cycle.log', deadline=deadline, env=os.environ)
            receipt = check_completed(attempt_dir/'cycle', request['brief_sha256'])
            for directory in sorted((p for p in (attempt_dir/'cycle').rglob('*') if p.is_dir()), reverse=True):
                sync_packet(directory)
            sync_packet(attempt_dir/'cycle')
            result.update(status='PASS', review_status='AWAITING_REVIEW',
                          candidate_sha256=receipt['candidate_sha256'], artifact_directory='cycle',
                          pipeline_receipt_sha256=digest(attempt_dir/'cycle/cycle.json'))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, AdmissionBusy) as error:
        result['blocker'] = str(error) if isinstance(error, ValueError) else type(error).__name__
    with (attempt_dir/'cycle-adapter-receipt.json').open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    sync_packet(attempt_dir)
    return result
