"""Prepare, record, and replay human watch/listen notes for a durable Short."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

from integrations.content_control.cycle_editorial import _text, _timestamp
from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.cycle_queue_short import FLAGS, _source, verify_consumed_short
from integrations.content_control.cycle_review import (
    LISTENER_CHECKS, WATCHER_CHECKS, _coverage_for_duration, _granular_review_checks,
    _load, _regular, _verified_voice,
)
from integrations.content_control.cycle_short import COMPACT_STYLE, SAFE_CAPTION_STYLE
from integrations.content_control.review_package import no_symlinks, require


TARGET_FIELDS = (
    'candidate_sha256', 'caption_sha256', 'queue_short_sha256', 'short_receipt_sha256',
    'preview_caption_mode', 'duration_seconds', 'parent_voice_receipt_sha256',
)
ROLE_CONTRACTS = (
    ('watcher', 'watched_at', 'direct_full_audiovisual_watch_and_listen', WATCHER_CHECKS),
    ('listener', 'listened_at', 'direct_full_mix_listening', LISTENER_CHECKS),
)
SCOPE = ('Supplied observations on the exact Short. This receipt does not independently verify '
         'watching, listening, creative approval, competitor comparison, or phone playback.')
UNVERIFIED = {**FLAGS, 'independent_verification': False,
              'human_av_acceptance_recorded': False, 'phone_playback_verified': False}


def _decode(raw, label):
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError('Invalid UTF-8 JSON: ' + label) from error
    require(isinstance(value, dict), 'JSON object required: ' + label)
    return value


def _read(path, limit):
    with _regular(path, limit).open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'Oversized input: ' + path.name)
    return raw, _decode(raw, path.name)


def _bindings(queue_root, job_id, short_dir):
    short_dir = Path(os.path.abspath(short_dir))
    receipt = verify_consumed_short(queue_root, job_id, short_dir)
    queue_raw, queue_receipt = _read(short_dir / 'queue-short.json', 1024 * 1024)
    short_raw, short_receipt = _read(short_dir / 'short.json', 1024 * 1024)
    short_sha = hashlib.sha256(short_raw).hexdigest()
    require(queue_receipt == receipt and short_sha == receipt['artifacts_sha256']['short.json'],
            'Short receipts changed while reading preview presentation')
    mode = short_receipt.get('preview_caption_mode')
    overlay = short_receipt.get('caption_overlay')
    require((mode == 'sidecar' and 'caption_overlay' not in short_receipt)
            or (mode == 'burned' and isinstance(overlay, dict)
                and overlay.get('style') in (COMPACT_STYLE, SAFE_CAPTION_STYLE)),
            'Short caption presentation mode is invalid')
    parent, source = _source(queue_root, job_id)
    require(source == receipt['source_provenance'], 'Short parent changed while binding voices')
    voice = _verified_voice(parent, _load(parent / 'editorial.json'),
                            _load(parent / 'delivery/render.json'))
    require(voice is not None, 'Authenticated parent voice receipt required for Short listening review')
    # The Short verifier freshly measures the container and its encoded streams.
    require(verify_consumed_short(queue_root, job_id, short_dir) == receipt
            and _read(short_dir / 'queue-short.json', 1024 * 1024)[0] == queue_raw
            and _read(short_dir / 'short.json', 1024 * 1024)[0] == short_raw,
            'Short receipts changed while binding review inputs')
    return {
        **{key: receipt[key] for key in (
            'job_id', 'candidate_sha256', 'caption_sha256', 'parent_candidate_sha256',
            'parent_cycle_sha256', 'selection', 'encoded_streams_sha256',
            'decoded_picture_sha256')},
        'queue_short_sha256': hashlib.sha256(queue_raw).hexdigest(),
        'short_receipt_sha256': short_sha,
        'preview_caption_mode': mode,
        'short_finished_at': _timestamp(receipt.get('finished_at'), 'short_finished_at'),
        'duration_seconds': receipt['media']['duration_seconds'],
        'parent_voice_receipt_sha256': voice['voice_receipt_sha256'],
        'parent_voice_assignments_sha256': voice['voice_assignments_sha256'],
    }


def prepare_submission(queue_root, job_id, short_dir):
    """Return the exact target and blank observation fields for actual review."""
    source = _bindings(queue_root, job_id, short_dir)
    data = {'schema_version': 1, **{key: source[key] for key in TARGET_FIELDS}}
    for role, timestamp_key, basis, checks in ROLE_CONTRACTS:
        data[role + '_review'] = {
            role: '', timestamp_key: '', 'basis': basis, 'coverage': [],
            'checks': {name: {'passed': None, 'evidence': ''} for name in checks},
        }
    return data


def _replay(raw, submitted, source):
    fields = {'schema_version', *TARGET_FIELDS, 'watcher_review', 'listener_review'}
    require(set(submitted) == fields and type(submitted['schema_version']) is int
            and submitted['schema_version'] == 1, 'Exact Short attestation fields required')
    require(type(submitted['duration_seconds']) in (int, float)
            and all(submitted[key] == source[key] for key in TARGET_FIELDS),
            'Short attestation targets different derivative identities, duration or voices')
    recorded, feedback = {}, []
    for role, timestamp_key, basis, check_names in ROLE_CONTRACTS:
        section = submitted[role + '_review']
        require(isinstance(section, dict)
                and set(section) == {role, timestamp_key, 'basis', 'coverage', 'checks'},
                'Exact ' + role + ' observation fields required')
        reviewer = _text(section[role], role, 200)
        when = _timestamp(section[timestamp_key], timestamp_key)
        require(datetime.fromisoformat(when) >= datetime.fromisoformat(source['short_finished_at']),
                role.capitalize() + ' review predates the completed Short')
        require(section['basis'] == basis, 'Direct ' + role + ' observation required')
        coverage = _coverage_for_duration(section, role, source['duration_seconds'])
        checks, repair = _granular_review_checks(section, check_names, role)
        feedback.extend(repair)
        recorded[role + '_review'] = {
            role: reviewer, timestamp_key: when, 'basis': basis, 'coverage': coverage, 'checks': checks,
        }
    return {
        'schema_version': 1,
        'status': 'REVISION_REQUIRED' if feedback else 'WATCH_LISTEN_ATTESTATION_RECORDED',
        **source, **UNVERIFIED, **recorded, 'feedback': feedback,
        'submitted_attestation_sha256': hashlib.sha256(raw).hexdigest(),
        'submitted_attestation_json': raw.decode('utf-8'),
        'scope': SCOPE,
    }


def record_attestation(queue_root, job_id, short_dir, submission, output):
    require(all(os.environ.get(flag, 'false').lower() == 'false'
                for flag in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    queue_root, short_dir, submission, output = map(
        lambda path: Path(os.path.abspath(path)), (queue_root, short_dir, submission, output))
    no_symlinks(output)
    require(not output.exists() and output != submission
            and not output.is_relative_to(short_dir) and not output.is_relative_to(queue_root),
            'Fresh attestation output outside the Short and queue required')
    raw, submitted = _read(submission, 128 * 1024)
    source = _bindings(queue_root, job_id, short_dir)
    result = _replay(raw, submitted, source)
    require(_bindings(queue_root, job_id, short_dir) == source
            and _read(submission, 128 * 1024)[0] == raw,
            'Short or submitted attestation changed while recording')
    no_symlinks(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return result


def verify_recorded_value(queue_root, job_id, short_dir, recorded):
    """Replay a parsed recorded attestation against the durable Short."""
    require(all(recorded.get(key) is False for key in UNVERIFIED),
            'Recorded Short attestation cannot grant verification or approval')
    raw = recorded.get('submitted_attestation_json')
    require(isinstance(raw, str), 'Submitted Short attestation missing')
    raw = raw.encode('utf-8')
    require(len(raw) <= 128 * 1024, 'Oversized embedded Short attestation')
    source = _bindings(queue_root, job_id, short_dir)
    expected = _replay(raw, _decode(raw, 'recorded submission'), source)
    require(json.dumps(recorded, sort_keys=True, allow_nan=False)
            == json.dumps(expected, sort_keys=True, allow_nan=False),
            'Recorded Short attestation no longer matches the derivative or its supplied observations')
    return recorded


def verify_attestation(queue_root, job_id, short_dir, receipt):
    path = Path(os.path.abspath(receipt))
    before, recorded = _read(path, 1024 * 1024)
    source = _bindings(queue_root, job_id, short_dir)
    verify_recorded_value(queue_root, job_id, short_dir, recorded)
    require(_read(path, 1024 * 1024)[0] == before
            and _bindings(queue_root, job_id, short_dir) == source,
            'Short or recorded attestation changed while verifying')
    return recorded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ('prepare', 'record', 'verify'):
        command = commands.add_parser(action)
        command.add_argument('--queue-root', required=True)
        command.add_argument('--job-id', required=True)
        command.add_argument('--short-dir', required=True)
        if action == 'record':
            command.add_argument('--submission', required=True)
            command.add_argument('--output', required=True)
        elif action == 'verify':
            command.add_argument('--receipt', required=True)
    args = parser.parse_args()
    inputs = (args.queue_root, args.job_id, args.short_dir)
    if args.action == 'prepare':
        result = prepare_submission(*inputs)
    elif args.action == 'record':
        result = record_attestation(*inputs, args.submission, args.output)
    else:
        result = verify_attestation(*inputs, args.receipt)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
