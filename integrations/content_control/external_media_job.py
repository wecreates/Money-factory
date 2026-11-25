"""Durably admit an already-produced free/offline media derivative for review.

This adapter never executes the external tool, a provider, ffmpeg, or network
code.  An operator supplies a trusted artifact root.  The immutable queue job
pins every lineage boundary, and this module only verifies, copies and packages
those bytes through the existing unpublished review packager.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import time
from zipfile import BadZipFile, ZipFile

from integrations.content_control.review_package import (
    LIMIT, check_deadline, copy_chunks, digest, inspect_packet, no_symlinks, package_review,
)


SHA256 = re.compile(r'^[0-9a-f]{64}$')
GIT_SHA = re.compile(r'^[0-9a-f]{40}$')
MAX_JSON = 4 * 1024 * 1024
MAX_MEDIA = 256 * 1024 * 1024
LEGACY_OPERATION = 'package-openmontage-safe-reframe'
SOURCE_BYTES_OPERATION = 'package-openmontage-safe-reframe-with-source-bytes'
MODEL_EDIT_OPERATION = 'package-free-local-model-edit-with-source-bytes'
LEGACY_SOURCE_EVIDENCE = 'receipt_attested_only'
REHASHED_SOURCE_EVIDENCE = 'queue_owned_source_bytes_rehashed'
SOURCE_MEDIA = {
    'source-evidence/original.mp4': 'source_candidate_sha256',
    'source-evidence/trimmed.mp4': 'transformed_source_sha256',
}
SOURCE_RECEIPTS = {
    'safe-reframe-receipt.json': 'external_receipt_sha256',
    'diagnostics/prior-openmontage-receipt.json': 'prior_tool_receipt_sha256',
}
MODEL_SOURCE_RECEIPTS = {
    'model-consumer-receipt.json': 'external_receipt_sha256',
    'diagnostics/model-edit-receipt.json': 'prior_tool_receipt_sha256',
}
FIELDS = {
    'operation', 'source_candidate_sha256', 'transformed_source_sha256',
    'candidate_sha256', 'external_receipt_sha256', 'prior_tool_receipt_sha256',
    'review_run_sha256', 'tool_commit', 'timeout_seconds',
    'publication_enabled', 'paid_generation_enabled', 'production_approved',
    'production_ready', 'full_av_review',
}
FALSE_GATES = {
    'publish', 'publishing', 'publication', 'paid', 'approved', 'approval',
    'production_approved',
    'production_ready', 'full_av_review', 'full_audiovisual_review',
    'creative_final_acceptance', 'creative_acceptance',
}
SAFE_RECEIPT_FIELDS = {
    'schema_version', 'observed_at_utc', 'workstream', 'issue_evidence', 'source',
    'input', 'consumer', 'safety', 'tests', 'visual_review', 'revision_package',
    'verdict',
}
SAFE_SOURCE_FIELDS = {
    'repository', 'base_commit', 'adapter_commit', 'checkout_clean',
    'prior_receipt_sha256',
}
SAFE_INPUT_FIELDS = {
    'current_candidate_sha256', 'trimmed_source_sha256', 'trim_seconds',
    'source_resolution',
}
SAFE_CONSUMER_FIELDS = {
    'tool', 'tool_version', 'provider', 'runtime', 'operation',
    'output_resolution', 'scaled_picture_resolution', 'sample_aspect_ratio',
    'display_aspect_ratio', 'letterbox_y_offset', 'output_duration_seconds',
    'output_sha256',
}
SAFETY_FIELDS = {
    'publication_enabled', 'paid_generation_enabled', 'production_approved',
    'provider_calls', 'sandbox_weakened', 'external_write',
}
PRIOR_RECEIPT_FIELDS = {
    'schema_version', 'observed_at_utc', 'workstream', 'source', 'safety',
    'input', 'ordinary_browser_probe', 'remotion_attempt',
    'actual_tool_consumers', 'visual_review', 'verdict',
}
PRIOR_SOURCE_FIELDS = {'repository', 'commit', 'checkout_clean'}
PRIOR_INPUT_FIELDS = {
    'path', 'sha256', 'duration_seconds', 'resolution', 'video_codec', 'audio_codec',
}
RUN_FIELDS = {
    'schema_version', 'status', 'technical_status', 'observed_at_utc', 'consumer',
    'operation', 'candidate_sha256', 'caption_sha256', 'source_candidate_sha256',
    'prior_openmontage_receipt_sha256', 'openmontage_adapter_commit',
    'artifacts_sha256', 'publication_enabled', 'paid_generation_enabled',
    'production_approved', 'full_av_review', 'production_ready',
    'sandbox_weakened', 'provider_calls', 'scope',
}
METADATA_FIELDS = {
    'schema_version', 'status', 'tool', 'tool_version', 'provider', 'runtime',
    'operation', 'observed_at_utc', 'source_candidate_sha256',
    'trimmed_source_sha256', 'candidate_sha256',
    'prior_openmontage_receipt_sha256', 'openmontage_repository',
    'openmontage_base_commit', 'openmontage_adapter_commit', 'source_resolution',
    'output_resolution', 'sample_aspect_ratio', 'display_aspect_ratio',
    'letterbox_y_offset', 'duration_seconds', 'video_codec', 'audio_codec',
    'publication_enabled', 'paid_generation_enabled', 'production_approved',
    'full_av_review', 'production_ready', 'provider_calls', 'sandbox_weakened',
    'scope',
}
MODEL_WRAPPER_FIELDS = {
    'schema_version', 'observed_at_utc', 'workstream', 'operation',
    'source_candidate_sha256', 'candidate_sha256', 'model_receipt_sha256',
    'tool_commit', 'consumer', 'safety', 'scope',
}
MODEL_RUN_FIELDS = {
    'schema_version', 'status', 'technical_status', 'observed_at_utc', 'consumer',
    'operation', 'candidate_sha256', 'caption_sha256', 'source_candidate_sha256',
    'prior_tool_receipt_sha256', 'tool_commit', 'artifacts_sha256',
    'publication_enabled', 'paid_generation_enabled', 'production_approved',
    'full_av_review', 'production_ready', 'sandbox_weakened', 'provider_calls', 'scope',
}
MODEL_METADATA_FIELDS = {
    'schema_version', 'status', 'tool', 'runtime', 'operation', 'observed_at_utc',
    'source_candidate_sha256', 'candidate_sha256', 'model_sha256',
    'model_receipt_sha256', 'tool_commit', 'source_resolution', 'output_resolution',
    'duration_seconds', 'video_codec', 'audio_codec', 'full_decode',
    'audio_packet_stream_preserved', 'publication_enabled',
    'paid_generation_enabled', 'production_approved', 'full_av_review',
    'production_ready', 'provider_calls', 'sandbox_weakened', 'scope',
}


def validate(request):
    if not isinstance(request, dict) or set(request) != FIELDS:
        raise ValueError('Require the exact documented external-media request')
    if request['operation'] not in (LEGACY_OPERATION, SOURCE_BYTES_OPERATION, MODEL_EDIT_OPERATION):
        raise ValueError('Only a reviewed OpenMontage or free-local model edit admission is allowed')
    for name in ('publication_enabled', 'paid_generation_enabled', 'production_approved',
                 'production_ready', 'full_av_review'):
        if request[name] is not False:
            raise ValueError('Publishing, payment and approval gates must remain false')
    for name in ('source_candidate_sha256', 'transformed_source_sha256',
                 'candidate_sha256', 'external_receipt_sha256',
                 'prior_tool_receipt_sha256', 'review_run_sha256'):
        if not isinstance(request[name], str) or not SHA256.fullmatch(request[name]):
            raise ValueError('Invalid pinned ' + name)
    if not isinstance(request['tool_commit'], str) or not GIT_SHA.fullmatch(request['tool_commit']):
        raise ValueError('Invalid pinned tool_commit')
    if type(request['timeout_seconds']) is not int or not 5 <= request['timeout_seconds'] <= 300:
        raise ValueError('Require a 5..300 second local packaging deadline')
    return request


def _unique_json(path, limit=MAX_JSON):
    path = Path(path).absolute()
    no_symlinks(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
        raise ValueError('Required external artifact is missing or oversized')
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError('Required external artifact is oversized')

    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('Duplicate external receipt key')
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda item: (_ for _ in ()).throw(
                               ValueError('Nonfinite external receipt value')))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid external receipt JSON') from error
    if not isinstance(value, dict):
        raise ValueError('External receipt must be an object')
    return raw, value


def _false_gate_scan(value):
    """Reject approval/payment/publication claims wherever a receipt nests them."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower()
            if any(token in normalized for token in FALSE_GATES) and item is not False:
                raise ValueError('External receipt contains a non-false approval or publishing gate')
            if normalized == 'provider_calls' and item != 0:
                raise ValueError('External receipt records provider calls')
            if normalized in ('external_write', 'sandbox_weakened') and item is not False:
                raise ValueError('External receipt records an unsafe execution boundary')
            if normalized == 'cost_usd' and item != 0 and item != 0.0:
                raise ValueError('External receipt records a paid operation')
            if (normalized.endswith('status') and isinstance(item, str)
                    and any(gate in item.upper() for gate in ('APPROVED', 'PUBLISHED', 'PRODUCTION_READY'))):
                raise ValueError('External receipt contains an approval-bearing status')
            _false_gate_scan(item)
    elif isinstance(value, list):
        for item in value:
            _false_gate_scan(item)


def _regular_root(root):
    root = Path(root).absolute()
    no_symlinks(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('Operator-supplied external-media root must be a regular directory')
    return root


def _transfer_pinned_input(path, expected, limit, deadline, target=None):
    """Hash one bounded regular input, optionally copying those exact bytes."""
    no_symlinks(path)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as incoming:
        before = os.fstat(incoming.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError('Required source evidence is not a bounded regular file: ' + path.name)
        observed = hashlib.sha256()
        size = 0
        outgoing = None
        try:
            if target is not None:
                outgoing = os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb')
            while True:
                check_deadline(deadline)
                chunk = incoming.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise ValueError('Source evidence exceeds byte limit: ' + path.name)
                observed.update(chunk)
                if outgoing is not None:
                    outgoing.write(chunk)
        finally:
            if outgoing is not None:
                outgoing.close()
        after = os.fstat(incoming.fileno())
    if (size != before.st_size
            or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or observed.hexdigest() != expected):
        raise ValueError('Source evidence hash mismatch: ' + path.name)
    return size


def _source_bytes(root, request, deadline, target=None):
    media_root = root / 'source-evidence'
    no_symlinks(media_root)
    if not media_root.is_dir() or {path.name for path in media_root.iterdir()} != {'original.mp4', 'trimmed.mp4'}:
        raise ValueError('Require exactly original.mp4 and trimmed.mp4 as source evidence')
    if target is not None:
        (target / 'source-evidence').mkdir(mode=0o700)
        (target / 'diagnostics').mkdir(mode=0o700)
        receipts = MODEL_SOURCE_RECEIPTS if request['operation'] == MODEL_EDIT_OPERATION else SOURCE_RECEIPTS
        for name, key in receipts.items():
            (target / name).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _transfer_pinned_input(root / name, request[key], MAX_JSON, deadline, target / name)
    remaining = MAX_MEDIA
    for name, key in SOURCE_MEDIA.items():
        remaining -= _transfer_pinned_input(root / name, request[key], remaining, deadline,
                                            target / name if target is not None else None)


def _inspect_model_source(root, request, review, deadline):
    """Validate one exact YuNet-driven edit and its normal review packet."""
    wrapper_path = root / 'model-consumer-receipt.json'
    model_path = root / 'diagnostics' / 'model-edit-receipt.json'
    wrapper_raw, wrapper = _unique_json(wrapper_path)
    model_raw, model = _unique_json(model_path)
    _false_gate_scan(wrapper)
    _false_gate_scan(model)
    if hashlib.sha256(wrapper_raw).hexdigest() != request['external_receipt_sha256']:
        raise ValueError('Model consumer receipt hash mismatch')
    if hashlib.sha256(model_raw).hexdigest() != request['prior_tool_receipt_sha256']:
        raise ValueError('Model edit receipt hash mismatch')
    safety = wrapper.get('safety')
    prior_safety = model.get('safety')
    prior_input = model.get('input')
    prior_output = model.get('output')
    local_model = model.get('local_model')
    if (set(wrapper) != MODEL_WRAPPER_FIELDS
            or wrapper.get('schema_version') != 1 or wrapper.get('workstream') != 'C09'
            or wrapper.get('operation') != MODEL_EDIT_OPERATION
            or wrapper.get('source_candidate_sha256') != request['source_candidate_sha256']
            or wrapper.get('candidate_sha256') != request['candidate_sha256']
            or wrapper.get('model_receipt_sha256') != request['prior_tool_receipt_sha256']
            or wrapper.get('tool_commit') != request['tool_commit']
            or wrapper.get('consumer') != 'content-control-external-media'
            or not isinstance(safety, dict)
            or safety != {'publication_enabled': False, 'paid_generation_enabled': False,
                           'production_approved': False, 'production_ready': False,
                           'full_av_review': False, 'provider_calls': 0}
            or model.get('schema_version') != 1
            or not isinstance(prior_input, dict)
            or prior_input.get('sha256') != request['source_candidate_sha256']
            or not isinstance(prior_output, dict)
            or prior_output.get('sha256') != request['candidate_sha256']
            or prior_output.get('full_decode') != 'PASS'
            or prior_output.get('audio_packet_stream_preserved') is not True
            or not isinstance(local_model, dict)
            or local_model.get('provider_calls') != 0
            or local_model.get('cost_usd') not in (0, 0.0)
            or not isinstance(local_model.get('sha256'), str)
            or not SHA256.fullmatch(local_model['sha256'])
            or not isinstance(prior_safety, dict)
            or prior_safety.get('publication_enabled') is not False
            or prior_safety.get('paid_inference_enabled') is not False
            or prior_safety.get('provider_calls') != 0
            or prior_safety.get('external_write') is not False
            or prior_safety.get('sandbox_weakened') is not False):
        raise ValueError('Model edit receipts do not bind the exact free-local source and output')

    run_raw, run = _unique_json(review / 'run.json')
    metadata_raw, metadata = _unique_json(review / 'video.mp4.json')
    _false_gate_scan(run)
    _false_gate_scan(metadata)
    if (set(run) != MODEL_RUN_FIELDS or set(metadata) != MODEL_METADATA_FIELDS
            or hashlib.sha256(run_raw).hexdigest() != request['review_run_sha256']
            or run.get('status') != 'AWAITING_REVIEW'
            or run.get('technical_status') != 'PASS'
            or run.get('consumer') != 'content-control-external-media'
            or run.get('operation') != MODEL_EDIT_OPERATION
            or run.get('source_candidate_sha256') != request['source_candidate_sha256']
            or run.get('candidate_sha256') != request['candidate_sha256']
            or run.get('prior_tool_receipt_sha256') != request['prior_tool_receipt_sha256']
            or run.get('tool_commit') != request['tool_commit']
            or metadata.get('status') != 'AWAITING_REVIEW'
            or metadata.get('tool') != 'OpenCV YuNet face detector 2023mar'
            or metadata.get('runtime') != 'local'
            or metadata.get('operation') != MODEL_EDIT_OPERATION
            or metadata.get('source_candidate_sha256') != request['source_candidate_sha256']
            or metadata.get('candidate_sha256') != request['candidate_sha256']
            or metadata.get('model_sha256') != local_model['sha256']
            or metadata.get('model_receipt_sha256') != request['prior_tool_receipt_sha256']
            or metadata.get('tool_commit') != request['tool_commit']
            or metadata.get('full_decode') != 'PASS'
            or metadata.get('audio_packet_stream_preserved') is not True
            or any(item.get(name) is not False for item in (run, metadata)
                   for name in ('publication_enabled', 'paid_generation_enabled',
                                'production_approved', 'full_av_review', 'production_ready'))
            or run.get('provider_calls') != 0 or metadata.get('provider_calls') != 0):
        raise ValueError('Model review packet lineage does not match immutable queue pins')
    packet = inspect_packet(review, request['review_run_sha256'], request['candidate_sha256'], deadline)
    if (review / 'video.mp4').stat().st_size > MAX_MEDIA:
        raise ValueError('External media exceeds the queue admission limit')
    _source_bytes(root, request, deadline)
    return {'root': root, 'review': review, 'receipt': wrapper,
            'receipt_sha256': request['external_receipt_sha256'],
            'prior_sha256': request['prior_tool_receipt_sha256'], 'run': packet[0]}


def inspect_source(root, request, *, deadline=None):
    """Verify the exact pre-existing packet without interpreting it as approval."""
    validate(request)
    root = _regular_root(root)
    if request['operation'] == MODEL_EDIT_OPERATION:
        review = root / 'review'
        for path in (root / 'model-consumer-receipt.json',
                     root / 'diagnostics' / 'model-edit-receipt.json', review):
            no_symlinks(path)
        return _inspect_model_source(root, request, review, deadline)
    receipt_path = root / 'safe-reframe-receipt.json'
    prior_path = root / 'diagnostics' / 'prior-openmontage-receipt.json'
    review = root / 'review'
    for path in (receipt_path, prior_path, review):
        no_symlinks(path)

    receipt_raw, receipt = _unique_json(receipt_path)
    prior_raw, prior = _unique_json(prior_path)
    _false_gate_scan(receipt)
    _false_gate_scan(prior)
    if hashlib.sha256(receipt_raw).hexdigest() != request['external_receipt_sha256']:
        raise ValueError('External receipt hash mismatch')
    if hashlib.sha256(prior_raw).hexdigest() != request['prior_tool_receipt_sha256']:
        raise ValueError('Prior tool receipt hash mismatch')

    source = receipt.get('source')
    original = receipt.get('input')
    consumer = receipt.get('consumer')
    if (set(receipt) != SAFE_RECEIPT_FIELDS
            or set(source or {}) != SAFE_SOURCE_FIELDS
            or set(original or {}) != SAFE_INPUT_FIELDS
            or set(consumer or {}) != SAFE_CONSUMER_FIELDS
            or set(receipt.get('safety') or {}) != SAFETY_FIELDS
            or receipt.get('schema_version') != 1 or receipt.get('workstream') != 'C09'
            or not isinstance(source, dict) or not isinstance(original, dict)
            or not isinstance(consumer, dict)
            or source.get('repository') != 'https://github.com/OpenMontageInc/OpenMontage.git'
            or source.get('checkout_clean') is not True
            or source.get('adapter_commit') != request['tool_commit']
            or original.get('current_candidate_sha256') != request['source_candidate_sha256']
            or original.get('trimmed_source_sha256') != request['transformed_source_sha256']
            or consumer.get('tool') != 'showcase_card'
            or consumer.get('tool_version') != '0.1.0'
            or consumer.get('provider') != 'ffmpeg' or consumer.get('runtime') != 'local'
            or consumer.get('operation') != 'contain_and_pad_portrait_preview'
            or consumer.get('output_sha256') != request['candidate_sha256']
            or source.get('prior_receipt_sha256') != request['prior_tool_receipt_sha256']):
        raise ValueError('External receipt does not match immutable source/tool/output pins')

    prior_input = prior.get('input')
    prior_safety = prior.get('safety')
    prior_source = prior.get('source')
    if (set(prior) != PRIOR_RECEIPT_FIELDS
            or set(prior_source or {}) != PRIOR_SOURCE_FIELDS
            or set(prior_input or {}) != PRIOR_INPUT_FIELDS
            or set(prior_safety or {}) != SAFETY_FIELDS - {'production_approved'}
            or prior.get('schema_version') != 1 or prior.get('workstream') != 'C09'
            or not isinstance(prior_input, dict) or not isinstance(prior_safety, dict)
            or prior_input.get('sha256') != request['source_candidate_sha256']
            or prior_source.get('repository') != source['repository']
            or prior_source.get('checkout_clean') is not True
            or prior_safety.get('publication_enabled') is not False
            or prior_safety.get('paid_generation_enabled') is not False
            or prior_safety.get('provider_calls') != 0):
        raise ValueError('Prior tool receipt does not bind the queued source')

    run_path = review / 'run.json'
    run_raw, run = _unique_json(run_path)
    metadata_raw, metadata = _unique_json(review / 'video.mp4.json')
    _false_gate_scan(run)
    _false_gate_scan(metadata)
    if set(run) != RUN_FIELDS or set(metadata) != METADATA_FIELDS:
        raise ValueError('Review packet receipt schema is invalid')
    if hashlib.sha256(run_raw).hexdigest() != request['review_run_sha256']:
        raise ValueError('Review run receipt hash mismatch')
    if (run.get('status') != 'AWAITING_REVIEW' or run.get('technical_status') != 'PASS'
            or metadata.get('status') != 'AWAITING_REVIEW'
            or run.get('consumer') != 'openmontage'
            or run.get('source_candidate_sha256') != request['source_candidate_sha256']
            or run.get('candidate_sha256') != request['candidate_sha256']
            or run.get('prior_openmontage_receipt_sha256') != request['prior_tool_receipt_sha256']
            or run.get('openmontage_adapter_commit') != request['tool_commit']
            or metadata.get('source_candidate_sha256') != request['source_candidate_sha256']
            or metadata.get('trimmed_source_sha256') != request['transformed_source_sha256']
            or metadata.get('candidate_sha256') != request['candidate_sha256']
            or metadata.get('prior_openmontage_receipt_sha256') != request['prior_tool_receipt_sha256']
            or metadata.get('openmontage_adapter_commit') != request['tool_commit']
            or metadata.get('tool') != consumer['tool']
            or metadata.get('tool_version') != consumer['tool_version']
            or metadata.get('provider') != 'ffmpeg' or metadata.get('runtime') != 'local'):
        raise ValueError('Review packet lineage does not match immutable queue pins')
    if len(metadata_raw) > MAX_JSON:
        raise ValueError('Oversized media metadata')
    packet = inspect_packet(review, request['review_run_sha256'], request['candidate_sha256'], deadline)
    video = review / 'video.mp4'
    if video.stat().st_size > MAX_MEDIA:
        raise ValueError('External media exceeds the queue admission limit')
    if request['operation'] == SOURCE_BYTES_OPERATION:
        consumers = prior['actual_tool_consumers']
        trimmers = [entry for entry in consumers if isinstance(entry, dict)
                    and entry.get('tool') == 'video_trimmer'] if isinstance(consumers, list) else []
        if (len(trimmers) != 1 or trimmers[0].get('success') is not True
                or type(trimmers[0].get('cost_usd')) not in (int, float)
                or trimmers[0]['cost_usd'] != 0
                or trimmers[0].get('output_sha256') != request['transformed_source_sha256']):
            raise ValueError('Prior receipt does not bind a successful free trim to the pinned bytes')
        _source_bytes(root, request, deadline)
    return {'root': root, 'review': review, 'receipt': receipt,
            'receipt_sha256': request['external_receipt_sha256'],
            'prior_sha256': request['prior_tool_receipt_sha256'], 'run': packet[0]}


def _copy_packet(source, target, deadline):
    if target.exists() or target.is_symlink():
        raise ValueError('Queue-owned review staging directory already exists')
    no_symlinks(target)
    target.mkdir(mode=0o700)
    try:
        for path in sorted(source.iterdir()):
            if time.monotonic() >= deadline:
                raise TimeoutError('External-media packaging deadline exhausted')
            if not path.is_file() or path.is_symlink():
                raise ValueError('Only regular review packet files may be staged')
            with path.open('rb') as incoming, (target / path.name).open('xb') as outgoing:
                copy_chunks(incoming, outgoing, deadline)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise


def _verify_package(delivery, request, provenance, deadline=None):
    delivery = Path(delivery)
    no_symlinks(delivery)
    if (not delivery.is_dir() or delivery.is_symlink()
            or {path.name for path in delivery.iterdir()} != {'review', 'review-package.zip', 'package.json'}):
        raise ValueError('External-media delivery inventory changed')
    package_raw, package = _unique_json(delivery / 'package.json')
    manifest_raw, manifest = _unique_json(delivery / 'review' / 'delivery-manifest.json')
    if (package.get('schema_version') != 1 or package.get('status') != 'AWAITING_REVIEW'
            or package.get('candidate_sha256') != request['candidate_sha256']
            or package.get('run_sha256') != request['review_run_sha256']
            or package.get('provenance') != provenance
            or package.get('archive') != 'review-package.zip'
            or package.get('entrypoint') != 'review/index.html'
            or any(package.get(name) is not False for name in (
                'publication_enabled', 'paid_generation_enabled', 'production_approved',
                'full_av_review', 'production_ready'))):
        raise ValueError('Packaged external-media receipt is invalid')
    base = {key: value for key, value in package.items()
            if key not in ('archive', 'archive_sha256', 'entrypoint')}
    if manifest != base:
        raise ValueError('Packaged delivery manifest changed')
    hashes = package.get('files_sha256')
    review = delivery / 'review'
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('Packaged review inventory is invalid')
    expected_files = set(hashes) | {'delivery-manifest.json'}
    if {path.name for path in review.iterdir()} != expected_files:
        raise ValueError('Packaged review inventory changed')
    sizes = {'delivery-manifest.json': len(manifest_raw)}
    for name, expected in hashes.items():
        path = review / name
        if (Path(name).name != name or not SHA256.fullmatch(expected or '')
                or path.is_symlink() or not path.is_file() or digest(path, deadline) != expected):
            raise ValueError('Packaged review artifact changed: ' + str(name))
        sizes[name] = path.stat().st_size
    archive = delivery / 'review-package.zip'
    if (archive.is_symlink() or not archive.is_file() or archive.stat().st_size > LIMIT
            or digest(archive, deadline) != package.get('archive_sha256')):
        raise ValueError('Packaged review archive changed')
    archive_hashes = dict(hashes)
    archive_hashes['delivery-manifest.json'] = hashlib.sha256(manifest_raw).hexdigest()
    try:
        with ZipFile(archive) as bundle:
            members = bundle.infolist()
            expected_members = {'review/' + name for name in archive_hashes}
            if (len({item.filename for item in members}) != len(members)
                    or {item.filename for item in members} != expected_members):
                raise ValueError('Packaged archive inventory changed')
            for item in members:
                name = item.filename.removeprefix('review/')
                if (item.is_dir() or ((item.external_attr >> 16) & 0o170000) == 0o120000
                        or item.file_size != sizes[name]):
                    raise ValueError('Packaged archive contains an invalid member')
                observed = hashlib.sha256()
                with bundle.open(item) as stream:
                    while True:
                        check_deadline(deadline)
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        observed.update(chunk)
                if observed.hexdigest() != archive_hashes[name]:
                    raise ValueError('Packaged archive member changed')
    except BadZipFile as error:
        raise ValueError('Packaged review archive is invalid') from error
    return {'package_sha256': hashlib.sha256(package_raw).hexdigest(),
            'archive_sha256': package['archive_sha256']}


def _provenance(request):
    provenance = {
        'adapter': 'content-control-external-media',
        'operation': request['operation'],
        'source_candidate_sha256': request['source_candidate_sha256'],
        'transformed_source_sha256': request['transformed_source_sha256'],
        'candidate_sha256': request['candidate_sha256'],
        'external_receipt_sha256': request['external_receipt_sha256'],
        'prior_tool_receipt_sha256': request['prior_tool_receipt_sha256'],
        'review_run_sha256': request['review_run_sha256'],
        'tool_commit': request['tool_commit'],
        'provider_calls': 0,
        'publication_enabled': False,
        'paid_generation_enabled': False,
        'production_approved': False,
        'production_ready': False,
        'full_av_review': False,
        'scope': 'Verified pre-existing free/offline derivative lineage; no provider execution, playback, creative or publishing approval.',
    }
    if request['operation'] in (SOURCE_BYTES_OPERATION, MODEL_EDIT_OPERATION):
        provenance['source_evidence'] = REHASHED_SOURCE_EVIDENCE
    return provenance


def check_completed(attempt_dir, request, *, deadline=None):
    """Rehash queue-owned staged and packaged bytes for delivery readers."""
    attempt = Path(attempt_dir).absolute()
    no_symlinks(attempt)
    if not attempt.is_dir() or attempt.is_symlink():
        raise ValueError('Queue-owned external-media attempt is missing')
    validate(request)
    if request['operation'] in (SOURCE_BYTES_OPERATION, MODEL_EDIT_OPERATION):
        inspect_source(attempt, request, deadline=deadline)
        source_evidence = REHASHED_SOURCE_EVIDENCE
    else:
        inspect_packet(attempt / 'review', request['review_run_sha256'],
                       request['candidate_sha256'], deadline)
        source_evidence = LEGACY_SOURCE_EVIDENCE
    packaged = _verify_package(attempt / 'delivery', request, _provenance(request), deadline)
    return {'review': attempt / 'review', 'source_evidence': source_evidence, **packaged}


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
        check_deadline(deadline)
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    check_deadline(deadline)


def run_job(request, attempt_dir, *, external_media_root=None):
    validate(request)
    attempt = Path(attempt_dir).absolute()
    if not attempt.is_dir() or attempt.is_symlink():
        raise ValueError('Queue-owned attempt directory required')
    result = {
        'schema_version': 1, 'status': 'BLOCKED', 'operation': request['operation'],
        'review_status': 'AWAITING_REVIEW', 'publication_enabled': False,
        'paid_generation_enabled': False, 'production_approved': False,
        'production_ready': False, 'full_av_review': False, 'provider_calls': 0,
        'scope': 'Local byte admission and private review packaging only; no provider, playback, creative or publishing approval.',
    }
    try:
        if external_media_root is None:
            raise ValueError('Explicit operator-supplied external-media root required')
        deadline = time.monotonic() + request['timeout_seconds']
        source = inspect_source(external_media_root, request, deadline=deadline)
        _copy_packet(source['review'], attempt / 'review', deadline)
        if request['operation'] in (SOURCE_BYTES_OPERATION, MODEL_EDIT_OPERATION):
            _source_bytes(source['root'], request, deadline, target=attempt)
        inspect_packet(attempt / 'review', request['review_run_sha256'],
                       request['candidate_sha256'], deadline)
        package_review(attempt / 'review', attempt / 'delivery',
                       expected_run_sha256=request['review_run_sha256'],
                       expected_candidate_sha256=request['candidate_sha256'],
                       provenance=_provenance(request), deadline=deadline)
        completed = check_completed(attempt, request, deadline=deadline)
        # A concurrent mutation of the operator-owned source cannot be hidden by
        # a valid queue copy; require the complete lineage to still match.
        inspect_source(external_media_root, request, deadline=deadline)
        _sync_tree(attempt, deadline)
        result.update(
            status='PASS', artifact_directory='review', package_directory='delivery',
            candidate_sha256=request['candidate_sha256'],
            source_candidate_sha256=request['source_candidate_sha256'],
            transformed_source_sha256=request['transformed_source_sha256'],
            external_receipt_sha256=request['external_receipt_sha256'],
            prior_tool_receipt_sha256=request['prior_tool_receipt_sha256'],
            review_run_sha256=request['review_run_sha256'],
            pipeline_receipt_sha256=request['review_run_sha256'],
            tool_commit=request['tool_commit'], package_sha256=completed['package_sha256'],
            archive_sha256=completed['archive_sha256'], source_inputs_unchanged=True,
        )
        if request['operation'] in (SOURCE_BYTES_OPERATION, MODEL_EDIT_OPERATION):
            result['source_evidence'] = completed['source_evidence']
    except (ValueError, OSError, KeyError, TypeError, TimeoutError, BadZipFile) as error:
        result['blocker'] = str(error) if isinstance(error, ValueError) else type(error).__name__
    receipt = attempt / 'external-media-adapter-receipt.json'
    with receipt.open('x') as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    descriptor = os.open(attempt, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return result
