"""Bind a durable private cycle export to a read-only deployment observation.

This verifier does not contact or mutate the provider.  The caller supplies the
SHA-256 of the exact observation through a separate trusted channel.  Missing
deployment objects remain BLOCKED; conflicting object identities fail closed.
Playback, phone, creative and audiovisual acceptance remain separate evidence.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re

from integrations.local_agent_queue import canonical
from integrations.content_control.review_delivery import (
    digest,
    parse_json,
    regular,
    verify_exported_preview,
)


MAX_OBSERVATION = 1024 * 1024
SHA256 = re.compile(r'[0-9a-f]{64}')
TEXT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,199}')
FLAGS = {
    'published': False,
    'publication_enabled': False,
    'paid_inference_enabled': False,
    'production_approved': False,
    'creative_review_verified': False,
    'listening_verified': False,
    'playback_verified': False,
    'physical_phone_verified': False,
    'full_av_review': False,
}
ROLE_PATHS = {
    'candidate_video': 'review/video.mp4',
    'captions': 'review/captions.vtt',
    'source_package': 'review/package.json',
    'review_archive': 'review-package.zip',
    'delivery_receipt': 'package.json',
}
OBSERVATION_FIELDS = frozenset({
    'schema_version', 'status', 'provider', 'project_id', 'source_version',
    'source_checkpoint', 'source_files_sha256', 'source_manifest_sha256',
    'observed_at', 'visibility', 'objects', 'scope', *FLAGS,
})
OBJECT_FIELDS = frozenset({'role', 'key', 'size_bytes', 'sha256'})
OBSERVATION_SCOPE = (
    'Read-only unpublished deployment observation; no playback, phone, creative or '
    'audiovisual acceptance.'
)
SCOPE = (
    'Exact durable private delivery bound to an externally pinned read-only deployment '
    'observation; playback, phone, creative and audiovisual acceptance remain unverified.'
)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate deployment observation key')
        result[key] = value
    return result


def _constant(_):
    raise ValueError('Nonfinite deployment observation value')


def _read_observation(path):
    path = regular(path, limit=MAX_OBSERVATION)
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8')
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('Deployment observation JSON is invalid') from error
    if not isinstance(value, dict):
        raise ValueError('Deployment observation must be an object')
    return raw, value


def _text(value, field):
    if (not isinstance(value, str) or not TEXT.fullmatch(value)
            or '://' in value):
        raise ValueError('Invalid deployment observation ' + field)
    return value


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('Invalid deployment observation timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('Invalid deployment observation timestamp') from error
    if (parsed.tzinfo is None or parsed.utcoffset() != timedelta(0)
            or not math.isfinite(parsed.timestamp())
            or parsed > datetime.now(timezone.utc) + timedelta(minutes=5)):
        raise ValueError('Invalid deployment observation timestamp')
    return value, parsed


def _delivery_completion(delivery_dir, expected_objects):
    """Read the exact hash-bound root receipt and normalize its completion time."""
    receipt_path = regular(Path(delivery_dir) / 'package.json')
    receipt_raw = receipt_path.read_bytes()
    if hashlib.sha256(receipt_raw).hexdigest() != expected_objects[
            'delivery_receipt']['sha256']:
        raise ValueError('Durable delivery receipt changed during chronology check')
    try:
        receipt = parse_json(receipt_raw.decode('utf-8'))
    except UnicodeDecodeError as error:
        raise ValueError('Durable delivery receipt is invalid') from error
    completed_at = receipt.get('provenance', {}).get('completed_at_unix')
    if type(completed_at) not in (int, float) or not math.isfinite(completed_at):
        raise ValueError('Durable delivery completion time is invalid')
    try:
        return datetime.fromtimestamp(completed_at, timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError('Durable delivery completion time is invalid') from error


def short_completion(delivery_dir, delivery):
    """Use the verified derivative completion as a lower bound, never its parent."""
    path = regular(Path(delivery_dir) / 'review/queue-short.json', limit=MAX_OBSERVATION)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != delivery['short_queue_receipt_sha256']:
        raise ValueError('Short queue receipt changed during chronology check')
    receipt = parse_json(raw.decode('utf-8'))
    if (receipt.get('status') != 'AWAITING_REVIEW'
            or receipt.get('technical_status') != 'PASS'
            or receipt.get('candidate_sha256') != delivery['candidate_sha256']
            or receipt.get('caption_sha256') != delivery['caption_sha256']):
        raise ValueError('Short queue receipt does not identify the delivered derivative')
    return _timestamp(receipt.get('finished_at'))[1]


def _expected_objects(delivery_dir, delivery=None):
    root = regular(delivery_dir, directory=True)
    paths = dict(ROLE_PATHS)
    if delivery and 'source_package_path' in delivery:
        paths['source_package'] = delivery['source_package_path']
    return {
        role: {
            'role': role,
            'key': key,
            'size_bytes': regular(root / key, limit=1024 * 1024 * 1024).stat().st_size,
            'sha256': digest(root / key),
        }
        for role, key in paths.items()
    }


def verify_private_preview_binding(delivery_dir, expected_delivery_identity_sha256,
                                   observation_path, expected_observation_sha256):
    """Replay durable bytes and bind them to an externally pinned observation."""
    if (not isinstance(expected_observation_sha256, str)
            or not SHA256.fullmatch(expected_observation_sha256)):
        raise ValueError('Trusted expected deployment observation identity is required')
    delivery = verify_exported_preview(delivery_dir, expected_delivery_identity_sha256)
    raw, observation = _read_observation(observation_path)
    observation_sha = hashlib.sha256(raw).hexdigest()
    if observation_sha != expected_observation_sha256:
        raise ValueError('Deployment observation does not match trusted expected identity')
    if (set(observation) != OBSERVATION_FIELDS
            or observation.get('schema_version') != 1
            or observation.get('status') != 'UNPUBLISHED_PRIVATE_PREVIEW_OBSERVED'
            or observation.get('visibility') != 'private'
            or observation.get('scope') != OBSERVATION_SCOPE
            or any(observation.get(field) is not expected for field, expected in FLAGS.items())):
        raise ValueError('Deployment observation schema or safety flags are invalid')

    provider = _text(observation.get('provider'), 'provider')
    project_id = _text(observation.get('project_id'), 'project_id')
    source_version = _text(observation.get('source_version'), 'source_version')
    source_checkpoint = _text(observation.get('source_checkpoint'), 'source_checkpoint')
    source_files = observation.get('source_files_sha256')
    if (not isinstance(source_files, dict) or not 1 <= len(source_files) <= 500
            or any(not isinstance(name, str)
                   or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@+/-]{0,255}', name)
                   or name.startswith('/') or Path(name).as_posix() != name
                   or '..' in Path(name).parts
                   or not isinstance(value, str) or not SHA256.fullmatch(value)
                   for name, value in source_files.items())):
        raise ValueError('Invalid deployment source file identities')
    source_manifest = observation.get('source_manifest_sha256')
    if (not isinstance(source_manifest, str) or not SHA256.fullmatch(source_manifest)
            or hashlib.sha256(canonical(source_files).encode()).hexdigest() != source_manifest):
        raise ValueError('Invalid deployment source manifest identity')
    short = 'short_queue_receipt_sha256' in delivery
    expected_objects = (_expected_objects(delivery_dir, delivery) if short
                        else _expected_objects(delivery_dir))
    completed_time = (short_completion(delivery_dir, delivery) if short
                      else _delivery_completion(delivery_dir, expected_objects))
    observed_at, observed_time = _timestamp(observation.get('observed_at'))
    if observed_time < completed_time:
        raise ValueError('Deployment observation predates durable delivery completion')
    objects = observation.get('objects')
    if not isinstance(objects, list) or len(objects) > len(ROLE_PATHS):
        raise ValueError('Invalid deployment object inventory')

    observed = {}
    for item in objects:
        if not isinstance(item, dict) or set(item) != OBJECT_FIELDS:
            raise ValueError('Invalid deployment object schema')
        role = item.get('role')
        if role not in ROLE_PATHS or role in observed:
            raise ValueError('Invalid or duplicate deployment object role')
        if (item.get('key') != expected_objects[role]['key']
                or type(item.get('size_bytes')) is not int
                or item['size_bytes'] < 0
                or not isinstance(item.get('sha256'), str)
                or not SHA256.fullmatch(item['sha256'])):
            raise ValueError('Invalid deployment object identity: ' + role)
        if item != expected_objects[role]:
            raise ValueError('Deployment object does not match durable delivery: ' + role)
        observed[role] = item

    missing = sorted(set(ROLE_PATHS) - set(observed))
    delivery_receipt_sha = expected_objects['delivery_receipt']['sha256']
    caption_sha = expected_objects['captions']['sha256']
    identity = {
        'delivery_identity_sha256': delivery['delivery_identity_sha256'],
        'delivery_receipt_sha256': delivery_receipt_sha,
        'candidate_sha256': delivery['candidate_sha256'],
        'caption_sha256': caption_sha,
        'package_sha256': delivery['package_sha256'],
        'archive_sha256': delivery['archive_sha256'],
        'deployment_observation_sha256': observation_sha,
        'provider': provider,
        'project_id': project_id,
        'source_version': source_version,
        'source_checkpoint': source_checkpoint,
        'source_files_sha256': source_files,
        'source_manifest_sha256': source_manifest,
        'observed_at': observed_at,
        'visibility': 'private',
        'objects': [observed[role] for role in sorted(observed)],
        **FLAGS,
    }
    if (regular(observation_path, limit=MAX_OBSERVATION).read_bytes() != raw
            or verify_exported_preview(delivery_dir, expected_delivery_identity_sha256) != delivery
            or (_expected_objects(delivery_dir, delivery) if short
                else _expected_objects(delivery_dir)) != expected_objects):
        raise ValueError('Delivery or deployment observation changed during binding')
    binding_sha = hashlib.sha256(canonical(identity).encode()).hexdigest()
    return {
        'schema_version': 1,
        'status': 'BLOCKED' if missing else 'PASS',
        **identity,
        'missing_roles': missing,
        'preview_binding_identity_sha256': binding_sha,
        'scope': SCOPE,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery', required=True)
    parser.add_argument('--expected-delivery-identity', required=True)
    parser.add_argument('--observation', required=True)
    parser.add_argument('--expected-observation-identity', required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_private_preview_binding(
            Path(os.path.abspath(args.delivery)), args.expected_delivery_identity,
            Path(os.path.abspath(args.observation)), args.expected_observation_identity)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'schema_version': 1, 'status': 'BLOCKED', **FLAGS,
                          'reason': str(error), 'scope': SCOPE}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
