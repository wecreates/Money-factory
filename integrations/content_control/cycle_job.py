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
    optional = {'intake_input', 'revision_input', 'minimum_duration_seconds'}
    if not isinstance(request, dict) or not fields <= request.keys() <= (fields | optional):
        raise ValueError('Require the exact documented content-cycle request')
    if request['operation'] != 'produce-content-cycle':
        raise ValueError('Only produce-content-cycle is supported')
    if request['publication_enabled'] is not False or request['paid_generation_enabled'] is not False:
        raise ValueError('Publication and paid generation must remain false')
    if type(request['timeout_seconds']) is not int or not 30 <= request['timeout_seconds'] <= 1800:
        raise ValueError('Require a 30..1800 second cycle deadline')
    if 'minimum_duration_seconds' in request:
        minimum = request['minimum_duration_seconds']
        if type(minimum) is not int or not 1 <= minimum <= 600:
            raise ValueError('Minimum duration must be an integer from 1 to 600 seconds')
    if not isinstance(request['brief'], dict) or len(canonical(request['brief']).encode()) > 120000:
        raise ValueError('A bounded inline editorial brief is required')
    if (not isinstance(request['brief_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', request['brief_sha256'])
            or request['brief_sha256'] != brief_digest(request['brief'])):
        raise ValueError('Editorial brief identity mismatch')
    from integrations.content_control.cycle_editorial import compile_editorial, portrait_duration_limit
    editorial = compile_editorial(request['brief'])
    maximum = portrait_duration_limit(request['brief'], editorial)
    if maximum is not None and request.get('minimum_duration_seconds', 0) > maximum:
        raise ValueError('Requested minimum exceeds the portrait handoff maximum')
    production_input(request)
    return request


def production_input(request):
    """Return exact production bytes and optional lineage; paths remain host-owned."""
    encoded, lineage, _, _ = production_handoff(request)
    return encoded, lineage


def production_handoff(request):
    """Resolve input bytes, revision lineage, retained intake files and verified proof."""
    claimed_discovery = isinstance(request.get('brief'), dict) and 'topic_discovery' in request['brief']
    if 'intake_input' in request:
        from integrations.content_control.cycle_intake import MAX_INPUT, verify_inline_intake
        from integrations.content_control.cycle_discovery import MAX_POOL, MAX_RECEIPT
        if 'revision_input' in request:
            raise ValueError('Choose either the fresh intake or the revision handoff')
        supplied = request['intake_input']
        names = {'research_json': ('research.json', MAX_INPUT),
                 'draft_json': ('draft.json', MAX_INPUT), 'receipt_json': ('intake.json', MAX_INPUT)}
        discovery = {'discovery_pool_json': ('discovery-pool.json', MAX_POOL),
                     'discovery_receipt_json': ('discovery.json', MAX_RECEIPT)}
        if (not isinstance(supplied, dict)
                or set(supplied) not in (set(names), set(names) | set(discovery))):
            raise ValueError('Require exact inline intake_input fields')
        files = {}
        for field, (name, limit) in ({**names, **discovery} if set(discovery) <= set(supplied) else names).items():
            try:
                raw = supplied[field].encode('utf-8') if isinstance(supplied[field], str) else b''
            except UnicodeError as error:
                raise ValueError('Intake inputs must be bounded UTF-8 text') from error
            if not 0 < len(raw) <= limit:
                raise ValueError('Intake inputs must be bounded UTF-8 text')
            files[name] = raw
        encoded, proof = verify_inline_intake(request['brief'], files['research.json'],
                                              files['draft.json'], files['intake.json'],
                                              discovery_pool_raw=files.get('discovery-pool.json'),
                                              discovery_receipt_raw=files.get('discovery.json'))
        if claimed_discovery != ('topic_discovery' in proof):
            raise ValueError('Topic discovery requires replayable verified discovery intake')
        return encoded, None, files, proof
    if claimed_discovery:
        raise ValueError('Topic discovery requires replayable verified discovery intake')
    if 'revision_input' not in request:
        return canonical(request['brief']).encode('utf-8'), None, {}, None
    revision = request['revision_input']
    if not isinstance(revision, dict) or set(revision) != {'brief_json', 'revision_lineage'}:
        raise ValueError('Require exact inline revision_input fields')
    raw = revision['brief_json']
    if not isinstance(raw, str):
        raise ValueError('Revision brief_json must be UTF-8 text')
    try:
        encoded = raw.encode('utf-8')
    except UnicodeError as error:
        raise ValueError('Revision brief_json must be UTF-8 text') from error
    if len(encoded) > 256 * 1024:
        raise ValueError('Revision brief_json exceeds 256 KiB')
    from integrations.content_control.cycle_lineage import validate_lineage, _pairs, _constant
    parsed = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    if canonical(parsed) != canonical(request['brief']):
        raise ValueError('Revision brief differs from queued brief')
    validate_lineage(revision['revision_lineage'], hashlib.sha256(encoded).hexdigest())
    return encoded, revision['revision_lineage'], {}, None


def verify_attempt_intake(attempt, intake, cycle_receipt):
    """Recheck the owned attempt against the immutable request and cycle receipt."""
    if cycle_receipt.get('verified_intake') != intake:
        raise ValueError('Completed verified intake differs from queued handoff')
    if intake is not None:
        from integrations.content_control.cycle_intake import verify_intake
        discovered = 'topic_discovery' in intake
        if verify_intake(attempt/'research.json', attempt/'draft.json', attempt,
                         discovery_pool=attempt/'discovery-pool.json' if discovered else None,
                         discovery_receipt=attempt/'discovery.json' if discovered else None) != intake:
            raise ValueError('Retained intake differs from queued handoff')


def _json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4*1024*1024:
        raise ValueError('Missing or unsafe cycle receipt')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('Cycle receipt must be an object')
    return value


def check_completed(directory, expected_brief_sha256, *, minimum_duration=None, require_portrait_duration=False,
                    deadline=None):
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
    from integrations.content_control.cycle_editorial import compile_editorial, portrait_duration_limit
    source_brief = _json(directory/'brief.json')
    if editorial != compile_editorial(source_brief):
        raise ValueError('Editorial does not derive from the queued brief')
    from integrations.content_control.cycle_package import declared_speaker_label, editorial_digest, inspect_media
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
    declared_speaker_label(editorial, rendered)
    declared_speaker_label(editorial, package)
    if (rendered.get('candidate_sha256') != receipt['candidate_sha256']
            or rendered.get('editorial_sha256') != canonical_editorial_sha
            or rendered.get('caption_sha256') != package['caption_sha256']
            or rendered.get('status') != 'AWAITING_REVIEW'
            or rendered.get('technical_status') != 'PASS'
            or any(rendered.get(key) is not False for key in
                   ('publication_enabled', 'paid_generation_enabled', 'production_approved', 'full_av_review'))):
        raise ValueError('Renderer receipt identity or approval mismatch')
    for stage_receipt in (receipt, rendered):
        observed = stage_receipt.get('minimum_duration_seconds')
        if observed != minimum_duration or type(observed) is not type(minimum_duration):
            raise ValueError('Completed minimum duration differs from queued request')
    picture = rendered.get('encoded_picture_duration_seconds')
    if minimum_duration is not None:
        frame_budget = rendered.get('measured_narration_frame_budget')
        if (type(frame_budget) is not int or not minimum_duration * 24 <= frame_budget <= 600 * 24
                or type(picture) not in (int, float) or not minimum_duration <= picture <= 600.25):
            raise ValueError('Completed render does not verify the queued minimum picture duration')
    field = 'maximum_duration_seconds'
    maximum = None
    if field in receipt or field in rendered or require_portrait_duration and 'portrait_handoff' in source_brief:
        maximum = portrait_duration_limit(source_brief, editorial)
        if maximum is None or any(type(obj.get(field)) is not int or obj[field] != maximum
                                  for obj in (receipt, rendered)):
            raise ValueError('Completed maximum duration differs from the portrait handoff')
        frame_budget = rendered.get('measured_narration_frame_budget')
        container = rendered.get('encoded_container_duration_seconds')
        media = package.get('media')
        if (type(frame_budget) is not int or not 0 < frame_budget <= maximum * 24
                or any(type(value) not in (int, float) or not 0 < value <= maximum for value in (picture, container))
                or not isinstance(media, dict) or container != media.get('duration_seconds')):
            raise ValueError('Completed render does not verify the portrait maximum duration')
    if minimum_duration is not None or maximum is not None:
        try:
            observed_media = inspect_media(directory/'delivery/video.mp4', deadline=deadline,
                                           decode=False, include_picture_duration=True)
            observed_picture = observed_media['picture_duration_seconds']
            if maximum is not None:
                observed_container = observed_media['duration_seconds']
        except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
            limit = 'queued minimum picture duration' if minimum_duration is not None else 'portrait maximum duration'
            raise ValueError(f'Cannot verify {limit} from delivered media') from error
        if minimum_duration is not None and (not minimum_duration <= observed_picture <= 600.25
                                             or float(observed_picture) != picture):
            raise ValueError('Delivered video does not match the queued minimum picture duration evidence')
        if maximum is not None and (not 0 < observed_picture <= maximum or not 0 < observed_container <= maximum
                                    or float(observed_picture) != picture or observed_container != container):
            raise ValueError('Delivered video does not match the portrait maximum duration evidence')
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
    brief_bytes, lineage, intake_files, intake = production_handoff(request)
    minimum = request.get('minimum_duration_seconds')
    production_hash = hashlib.sha256(brief_bytes).hexdigest()
    attempt_dir = Path(attempt_dir).absolute()
    if not attempt_dir.is_dir() or attempt_dir.is_symlink():
        raise ValueError('A queue-owned attempt directory is required')
    result = {'schema_version': 1, 'status': 'BLOCKED', 'operation': request['operation'],
              'brief_sha256': request['brief_sha256'], 'production_brief_sha256': production_hash,
              'publication_enabled': False,
              'paid_generation_enabled': False, 'production_ready': False,
              'production_approved': False, 'full_av_review': False,
              'scope': 'One admitted unpublished cycle; no unattended service or creative approval'}
    if minimum is not None:
        result['minimum_duration_seconds'] = minimum
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
        input_files = {'brief.json': brief_bytes, **intake_files}
        revision_path = None
        if lineage is not None:
            revision_path = attempt_dir/'revision.json'
            input_files[revision_path.name] = lineage['revision_json'].encode('utf-8')
        for name, raw in input_files.items():
            with (attempt_dir/name).open('xb') as stream:
                stream.write(raw)
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
            discovered = 'discovery-pool.json' in intake_files
            intake_expression = 'intake_inputs=dict(research_path=sys.argv[9],draft_path=sys.argv[10])'
            intake_paths = ([str(attempt_dir/name) for name in ('research.json', 'draft.json')]
                            if intake_files else [])
            if discovered:
                intake_expression = ('intake_inputs=dict(research_path=sys.argv[9],draft_path=sys.argv[10],'
                                     'discovery_pool=sys.argv[11],discovery_receipt=sys.argv[12])')
                intake_paths += [str(attempt_dir/'discovery-pool.json'), str(attempt_dir/'discovery.json')]
            bootstrap = ('import sys;from integrations.content_control.complete_cycle import run_cycle;'
                         'r=run_cycle(sys.argv[1],sys.argv[2],voice_python=sys.argv[3],'
                         'voice_root=sys.argv[4],timeout=int(sys.argv[5]),transcription_python=sys.argv[6] or None,'
                         'revision_path=sys.argv[7] or None,minimum_duration=int(sys.argv[8]) if sys.argv[8] else None,'
                         + (intake_expression if intake_files else 'intake_inputs=None') + ');'
                         'sys.exit(0 if r.get("status")=="AWAITING_REVIEW" else 2)')
            guarded_runner(lease, cpus)(
                [sys.executable, '-c', bootstrap, str(attempt_dir/'brief.json'),
                 str(attempt_dir/'cycle'), str(runtime), str(root), str(request['timeout_seconds']),
                 str(transcription_python) if transcription_python else '',
                 str(revision_path) if revision_path else '', str(minimum) if minimum is not None else '',
                 *intake_paths],
                cwd=ROOT, log=attempt_dir/'cycle.log', deadline=deadline, env=os.environ)
            receipt = check_completed(attempt_dir/'cycle', production_hash, minimum_duration=minimum,
                                      require_portrait_duration=True, deadline=deadline)
            if receipt.get('revision_lineage') != lineage:
                raise ValueError('Completed revision lineage differs from queued handoff')
            verify_attempt_intake(attempt_dir, intake, receipt)
            for directory in sorted((p for p in (attempt_dir/'cycle').rglob('*') if p.is_dir()), reverse=True):
                sync_packet(directory)
            sync_packet(attempt_dir/'cycle')
            result.update(status='PASS', review_status='AWAITING_REVIEW',
                          candidate_sha256=receipt['candidate_sha256'], artifact_directory='cycle',
                          pipeline_receipt_sha256=digest(attempt_dir/'cycle/cycle.json'))
            if intake is not None:
                result['verified_intake'] = intake
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, AdmissionBusy) as error:
        result['blocker'] = str(error) if isinstance(error, ValueError) else type(error).__name__
    with (attempt_dir/'cycle-adapter-receipt.json').open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    sync_packet(attempt_dir)
    return result
