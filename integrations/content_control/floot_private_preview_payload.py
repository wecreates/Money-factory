"""Stage one verified private delivery for immutable Floot object upload.

This module performs no provider write.  It copies exactly the five objects
required by the private-preview binding into a fresh local payload, assigns
deterministic add-only storage keys, and replays both source and staged bytes.
Playback, readback, deployment, creative and audiovisual acceptance remain
separate evidence.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from integrations.local_agent_queue import canonical
from integrations.content_control.cycle_checkpoint import _publish_restore
from integrations.content_control.private_preview_binding import (
    FLAGS,
    OBSERVATION_SCOPE,
    ROLE_PATHS,
    SHA256,
    verify_private_preview_binding,
)
from integrations.content_control.review_delivery import (
    digest,
    parse_json,
    regular,
    verify_exported_cycle,
)


MAX_FLOOT_OBJECT = 100 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
STATUS = 'PRIVATE_UPLOAD_PAYLOAD_READY'
SCOPE = (
    'Exact verified delivery bytes staged for private add-only upload; no provider '
    'write, readback, playback, phone, creative or audiovisual acceptance.'
)
OBJECT_FIELDS = frozenset({
    'role', 'logical_key', 'storage_key', 'staged_path', 'size_bytes',
    'sha256', 'visibility', 'add_only', 'overwrite_allowed', 'transfer_method',
})
MANIFEST_FIELDS = frozenset({
    'schema_version', 'status', 'provider', 'delivery_identity_sha256',
    'candidate_sha256', 'package_sha256', 'archive_sha256', 'visibility',
    'collision_policy', 'readback_required', 'provider_write_performed',
    'upload_completed', 'readback_completed',
    'objects', 'payload_identity_sha256', 'scope', *FLAGS,
})
SOURCE_SNAPSHOT_SCOPE = (
    'Externally pinned read-only Floot source snapshot; no object readback, playback, '
    'phone, creative or audiovisual acceptance.'
)
SOURCE_SNAPSHOT_FIELDS = frozenset({
    'schema_version', 'status', 'provider', 'project_id', 'source_version',
    'source_checkpoint', 'source_files_sha256', 'observed_at', 'visibility',
    'published', 'publication_enabled', 'paid_inference_enabled',
    'scope',
})
READBACK_RECEIPT_SCOPE = (
    'Externally pinned provider object-readback inventory for the exact private upload; '
    'full downloaded bytes remain separately replayed and no playback, phone, creative '
    'or audiovisual acceptance is claimed.'
)
READBACK_RECEIPT_FIELDS = frozenset({
    'schema_version', 'status', 'provider', 'project_id', 'source_version',
    'source_checkpoint', 'source_snapshot_sha256', 'upload_manifest_sha256',
    'readback_completed_at', 'visibility', 'published', 'publication_enabled',
    'paid_inference_enabled', 'objects', 'scope',
})
READBACK_OBJECT_FIELDS = frozenset({
    'role', 'logical_key', 'storage_key', 'size_bytes', 'sha256',
    'retrieval_method',
})
READBACK_SCOPE = (
    'Exact five-role readback hashes and externally pinned physical-key receipt retained '
    'with a logical-byte private-preview observation; external bundle and observation '
    'SHA-256 pins plus separate playback evidence remain required.'
)
BUNDLE_STATUS = 'PRIVATE_READBACK_OBSERVATION_READY'
BUNDLE_RECEIPT_FIELDS = frozenset({
    'schema_version', 'status', 'delivery_identity_sha256',
    'payload_identity_sha256', 'upload_manifest_sha256',
    'source_snapshot_sha256', 'readback_receipt_sha256',
    'observation_sha256', 'provider', 'project_id', 'source_version',
    'source_checkpoint', 'external_observation_pin_required',
    'external_bundle_pin_required',
    'provider_write_independently_verified', 'scope', *FLAGS,
})


def _utc_timestamp(value, field):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('Invalid Floot ' + field)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('Invalid Floot ' + field) from error
    if (parsed.tzinfo is None or parsed.utcoffset() != timedelta(0)
            or parsed > datetime.now(timezone.utc) + timedelta(minutes=5)):
        raise ValueError('Invalid Floot ' + field)
    return parsed


def _delivery_completion(delivery_dir, expected_sha256):
    receipt_path = regular(
        Path(delivery_dir) / 'package.json', limit=MAX_MANIFEST)
    raw = receipt_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Durable delivery receipt changed during chronology check')
    try:
        receipt = parse_json(raw.decode('utf-8'))
    except UnicodeDecodeError as error:
        raise ValueError('Invalid durable delivery receipt') from error
    completed_at = receipt.get('provenance', {}).get('completed_at_unix')
    if type(completed_at) not in (int, float) or not 0 < completed_at < float('inf'):
        raise ValueError('Invalid durable delivery completion time')
    try:
        return datetime.fromtimestamp(completed_at, timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError('Invalid durable delivery completion time') from error


def _expected_objects(delivery_dir, delivery):
    root = regular(delivery_dir, directory=True)
    identity = delivery['delivery_identity_sha256']
    result = []
    for role in sorted(ROLE_PATHS):
        logical = ROLE_PATHS[role]
        source = regular(root / logical, limit=MAX_FLOOT_OBJECT)
        result.append({
            'role': role,
            'logical_key': logical,
            'storage_key': f'deliveries/{identity}/{logical}',
            'staged_path': f'objects/{role}',
            'size_bytes': source.stat().st_size,
            'sha256': digest(source),
            'visibility': 'private',
            'add_only': True,
            'overwrite_allowed': False,
            'transfer_method': 'raw_bytes',
        })
    return result


def _manifest(delivery, objects):
    value = {
        'schema_version': 1,
        'status': STATUS,
        'provider': 'floot',
        'delivery_identity_sha256': delivery['delivery_identity_sha256'],
        'candidate_sha256': delivery['candidate_sha256'],
        'package_sha256': delivery['package_sha256'],
        'archive_sha256': delivery['archive_sha256'],
        'visibility': 'private',
        'collision_policy': 'abort_if_any_storage_key_exists',
        'readback_required': True,
        'provider_write_performed': False,
        'upload_completed': False,
        'readback_completed': False,
        'objects': objects,
        **FLAGS,
        'scope': SCOPE,
    }
    value['payload_identity_sha256'] = hashlib.sha256(
        canonical(value).encode()).hexdigest()
    return value


def _copy_exact(source, target, expected):
    observed = hashlib.sha256()
    size = 0
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        os.chmod(target, 0o600)
        while chunk := incoming.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FLOOT_OBJECT:
                raise ValueError('Floot object exceeds the 100 MiB private-object limit')
            observed.update(chunk)
            outgoing.write(chunk)
    if size != expected['size_bytes'] or observed.hexdigest() != expected['sha256']:
        raise ValueError('Delivery object changed while staging: ' + expected['role'])
    if (source.stat().st_size != expected['size_bytes']
            or digest(source) != expected['sha256']):
        raise ValueError('Delivery object changed after staging: ' + expected['role'])


def verify_upload_payload(delivery_dir, expected_delivery_identity_sha256, payload_dir):
    """Replay a prepared payload against the exact durable delivery."""
    delivery = verify_exported_cycle(
        delivery_dir, expected_delivery_identity_sha256)
    payload = regular(payload_dir, directory=True)
    if {path.name for path in payload.iterdir()} != {'floot-upload-manifest.json', 'objects'}:
        raise ValueError('Private upload payload inventory changed')
    objects_dir = regular(payload / 'objects', directory=True)
    if {path.name for path in objects_dir.iterdir()} != set(ROLE_PATHS):
        raise ValueError('Private upload object inventory changed')
    manifest_path = regular(payload / 'floot-upload-manifest.json', limit=MAX_MANIFEST)
    manifest_raw = manifest_path.read_bytes()
    try:
        manifest = parse_json(manifest_raw.decode('utf-8'))
    except UnicodeDecodeError as error:
        raise ValueError('Private upload manifest is invalid') from error
    expected = _expected_objects(delivery_dir, delivery)
    if (not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS
            or manifest.get('schema_version') != 1
            or manifest.get('status') != STATUS
            or manifest.get('provider') != 'floot'
            or manifest.get('visibility') != 'private'
            or manifest.get('collision_policy') != 'abort_if_any_storage_key_exists'
            or manifest.get('readback_required') is not True
            or manifest.get('provider_write_performed') is not False
            or manifest.get('upload_completed') is not False
            or manifest.get('readback_completed') is not False
            or manifest.get('scope') != SCOPE
            or any(manifest.get(field) is not value for field, value in FLAGS.items())
            or manifest.get('delivery_identity_sha256') != delivery['delivery_identity_sha256']
            or manifest.get('candidate_sha256') != delivery['candidate_sha256']
            or manifest.get('package_sha256') != delivery['package_sha256']
            or manifest.get('archive_sha256') != delivery['archive_sha256']
            or manifest.get('objects') != expected):
        raise ValueError('Private upload manifest changed or is unsafe')
    for item in expected:
        if set(item) != OBJECT_FIELDS:
            raise ValueError('Private upload object schema is invalid')
        staged = regular(payload / item['staged_path'], limit=MAX_FLOOT_OBJECT)
        if staged.stat().st_size != item['size_bytes'] or digest(staged) != item['sha256']:
            raise ValueError('Staged object does not match durable delivery: ' + item['role'])
    identity = dict(manifest)
    retained_identity = identity.pop('payload_identity_sha256')
    if hashlib.sha256(canonical(identity).encode()).hexdigest() != retained_identity:
        raise ValueError('Private upload payload identity changed')
    if (manifest_path.read_bytes() != manifest_raw
            or verify_exported_cycle(
                delivery_dir, expected_delivery_identity_sha256) != delivery
            or _expected_objects(delivery_dir, delivery) != expected
            or any(
                regular(payload / item['staged_path'], limit=MAX_FLOOT_OBJECT).stat().st_size
                    != item['size_bytes']
                or digest(payload / item['staged_path']) != item['sha256']
                for item in expected)):
        raise ValueError('Delivery or private upload payload changed during replay')
    return manifest


def prepare_upload_payload(delivery_dir, expected_delivery_identity_sha256, output):
    """Copy the exact five delivery roles into a fresh atomic local payload."""
    if any(os.environ.get(name, 'false').lower() != 'false'
           for name in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED',
                        'PAID_INFERENCE_ENABLED')):
        raise ValueError('Publishing and paid generation/inference must remain disabled')
    delivery_root = regular(delivery_dir, directory=True)
    output = Path(os.path.abspath(output))
    parent = regular(output.parent, directory=True)
    if (output.exists() or output.is_symlink()
            or output.is_relative_to(delivery_root)
            or delivery_root.is_relative_to(output)):
        raise ValueError('Fresh payload output separate from delivery required')
    delivery = verify_exported_cycle(
        delivery_root, expected_delivery_identity_sha256)
    objects = _expected_objects(delivery_root, delivery)
    stage = Path(tempfile.mkdtemp(prefix='.floot-private-payload-', dir=parent))
    stage_identity = None
    try:
        staged_objects = stage / 'objects'
        staged_objects.mkdir(mode=0o700)
        for item in objects:
            _copy_exact(
                regular(delivery_root / item['logical_key'], limit=MAX_FLOOT_OBJECT),
                staged_objects / item['role'], item)
        manifest = _manifest(delivery, objects)
        manifest_path = stage / 'floot-upload-manifest.json'
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + '\n')
        os.chmod(manifest_path, 0o600)
        if (verify_exported_cycle(
                delivery_root, expected_delivery_identity_sha256) != delivery
                or _expected_objects(delivery_root, delivery) != objects
                or verify_upload_payload(
                    delivery_root, expected_delivery_identity_sha256, stage) != manifest):
            raise ValueError('Delivery changed while preparing private upload payload')
        stage_stat = stage.stat(follow_symlinks=False)
        stage_identity = (stage_stat.st_dev, stage_stat.st_ino)
        _publish_restore(stage, output)
        return verify_upload_payload(
            delivery_root, expected_delivery_identity_sha256, output)
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        if stage_identity is not None:
            try:
                current = output.stat(follow_symlinks=False)
            except FileNotFoundError:
                current = None
            if (current is not None and not output.is_symlink()
                    and output.is_dir()
                    and (current.st_dev, current.st_ino) ==
                        stage_identity):
                shutil.rmtree(output)
        raise


def _read_source_snapshot(path, expected_sha256, manifest, manifest_sha256):
    if not isinstance(expected_sha256, str) or not SHA256.fullmatch(expected_sha256):
        raise ValueError('Trusted expected Floot source snapshot identity is required')
    path = regular(path, limit=MAX_MANIFEST)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Floot source snapshot does not match trusted expected identity')
    try:
        value = parse_json(raw.decode('utf-8'))
    except UnicodeDecodeError as error:
        raise ValueError('Floot source snapshot is invalid') from error
    if not isinstance(value, dict):
        raise ValueError('Floot source snapshot must be an object')
    source_files = value.get('source_files_sha256')
    manifest_key = ('cyzor-deliveries/' + manifest['delivery_identity_sha256'] +
                    '/floot-upload-manifest.json')
    if (set(value) != SOURCE_SNAPSHOT_FIELDS
            or value.get('schema_version') != 1
            or value.get('status') != 'PRIVATE_FLOOT_SOURCE_OBSERVED'
            or value.get('provider') != 'floot'
            or value.get('visibility') != 'private'
            or value.get('published') is not False
            or value.get('publication_enabled') is not False
            or value.get('paid_inference_enabled') is not False
            or value.get('scope') != SOURCE_SNAPSHOT_SCOPE
            or not isinstance(source_files, dict)
            or source_files.get(manifest_key) != manifest_sha256):
        raise ValueError('Floot source snapshot schema or payload binding is invalid')
    _utc_timestamp(value['observed_at'], 'source observation timestamp')
    return raw, value


def _read_readback_receipt(path, expected_sha256, manifest, snapshot,
                           source_snapshot_sha256, manifest_sha256):
    if not isinstance(expected_sha256, str) or not SHA256.fullmatch(expected_sha256):
        raise ValueError('Trusted expected Floot readback receipt identity is required')
    path = regular(path, limit=MAX_MANIFEST)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Floot readback receipt does not match trusted expected identity')
    try:
        value = parse_json(raw.decode('utf-8'))
    except UnicodeDecodeError as error:
        raise ValueError('Floot readback receipt is invalid') from error
    if not isinstance(value, dict):
        raise ValueError('Floot readback receipt must be an object')
    expected_objects = [{
        'role': item['role'],
        'logical_key': item['logical_key'],
        'storage_key': item['storage_key'],
        'size_bytes': item['size_bytes'],
        'sha256': item['sha256'],
        'retrieval_method': 'provider_object_readback',
    } for item in manifest['objects']]
    objects = value.get('objects')
    if (set(value) != READBACK_RECEIPT_FIELDS
            or value.get('schema_version') != 1
            or value.get('status') != 'PRIVATE_FLOOT_READBACK_COMPLETE'
            or value.get('provider') != snapshot['provider']
            or value.get('project_id') != snapshot['project_id']
            or value.get('source_version') != snapshot['source_version']
            or value.get('source_checkpoint') != snapshot['source_checkpoint']
            or value.get('source_snapshot_sha256') != source_snapshot_sha256
            or value.get('upload_manifest_sha256') != manifest_sha256
            or value.get('visibility') != 'private'
            or value.get('published') is not False
            or value.get('publication_enabled') is not False
            or value.get('paid_inference_enabled') is not False
            or value.get('scope') != READBACK_RECEIPT_SCOPE
            or objects != expected_objects
            or any(not isinstance(item, dict)
                   or set(item) != READBACK_OBJECT_FIELDS for item in objects)):
        raise ValueError('Floot readback receipt schema or physical-key binding is invalid')
    if (_utc_timestamp(value['readback_completed_at'], 'readback completion timestamp')
            < _utc_timestamp(snapshot['observed_at'], 'source observation timestamp')):
        raise ValueError('Floot readback completed before the bound source observation')
    return raw, value


def _readback_objects(readback_dir, manifest, payload_dir=None, delivery_dir=None):
    root = regular(readback_dir, directory=True)
    if {path.name for path in root.iterdir()} != set(ROLE_PATHS):
        raise ValueError('Complete exact five-role provider readback required')
    objects = []
    retained = {}
    for item in manifest['objects']:
        role = item['role']
        path = regular(root / role, limit=MAX_FLOOT_OBJECT)
        nofollow = getattr(os, 'O_NOFOLLOW', 0)
        cloexec = getattr(os, 'O_CLOEXEC', 0)
        source_fds = []
        try:
            if payload_dir is not None and delivery_dir is not None:
                for source in (
                        regular(Path(payload_dir) / item['staged_path'],
                                limit=MAX_FLOOT_OBJECT),
                        regular(Path(delivery_dir) / item['logical_key'],
                                limit=MAX_FLOOT_OBJECT)):
                    source_fds.append(os.open(
                        source, os.O_RDONLY | nofollow | cloexec))
            readback_fd = os.open(path, os.O_RDONLY | nofollow | cloexec)
            try:
                before = os.fstat(readback_fd)
                source_before = [os.fstat(fd) for fd in source_fds]
                if (not stat.S_ISREG(before.st_mode)
                        or before.st_size > MAX_FLOOT_OBJECT
                        or any(not stat.S_ISREG(value.st_mode)
                               or value.st_size > MAX_FLOOT_OBJECT
                               for value in source_before)):
                    raise ValueError('Provider readback file is invalid: ' + role)
                observed_hash = hashlib.sha256()
                observed_size = 0
                while chunk := os.read(readback_fd, 1024 * 1024):
                    observed_size += len(chunk)
                    if observed_size > MAX_FLOOT_OBJECT:
                        raise ValueError('Provider readback file is too large: ' + role)
                    observed_hash.update(chunk)
                after = os.fstat(readback_fd)
                source_after = [os.fstat(fd) for fd in source_fds]
            finally:
                os.close(readback_fd)
            if (before.st_dev, before.st_ino, before.st_size) != (
                    after.st_dev, after.st_ino, after.st_size):
                raise ValueError('Provider readback changed while hashing: ' + role)
            observed = (observed_size, observed_hash.hexdigest())
            if observed != (item['size_bytes'], item['sha256']):
                raise ValueError('Provider readback does not match staged object: ' + role)
            source_identities = []
            for source_stat, current in zip(source_before, source_after):
                if (source_stat.st_dev, source_stat.st_ino, source_stat.st_size) != (
                        current.st_dev, current.st_ino, current.st_size):
                    raise ValueError('Payload or delivery changed while hashing: ' + role)
                if (after.st_dev, after.st_ino) == (
                        source_stat.st_dev, source_stat.st_ino):
                    raise ValueError(
                        'Provider readback must not hardlink staged or delivery bytes')
                source_identities.extend((source_stat.st_dev, source_stat.st_ino))
            retained[role] = (
                after.st_dev, after.st_ino, observed[0], observed[1],
                *source_identities)
        finally:
            for fd in source_fds:
                os.close(fd)
        objects.append({
            'role': role,
            'key': item['logical_key'],
            'size_bytes': observed[0],
            'sha256': observed[1],
        })
    return root, objects, retained


def _bundle_receipt(manifest, manifest_sha, snapshot, source_snapshot_sha,
                    readback_receipt_sha, observation_sha):
    return {
        'schema_version': 1,
        'status': BUNDLE_STATUS,
        'delivery_identity_sha256': manifest['delivery_identity_sha256'],
        'payload_identity_sha256': manifest['payload_identity_sha256'],
        'upload_manifest_sha256': manifest_sha,
        'source_snapshot_sha256': source_snapshot_sha,
        'readback_receipt_sha256': readback_receipt_sha,
        'observation_sha256': observation_sha,
        'provider': snapshot['provider'],
        'project_id': snapshot['project_id'],
        'source_version': snapshot['source_version'],
        'source_checkpoint': snapshot['source_checkpoint'],
        'external_observation_pin_required': True,
        'external_bundle_pin_required': True,
        'provider_write_independently_verified': False,
        **FLAGS,
        'scope': READBACK_SCOPE,
    }


def verify_readback_observation_bundle(
        delivery_dir, expected_delivery_identity_sha256, payload_dir,
        readback_dir, bundle_dir, expected_source_snapshot_sha256,
        expected_readback_receipt_sha256, expected_observation_sha256,
        expected_bundle_receipt_sha256):
    """Replay the exact logical and physical-key provenance in a retained bundle."""
    for identity, label in (
            (expected_source_snapshot_sha256, 'source snapshot'),
            (expected_readback_receipt_sha256, 'readback receipt'),
            (expected_observation_sha256, 'observation'),
            (expected_bundle_receipt_sha256, 'bundle receipt')):
        if not isinstance(identity, str) or not SHA256.fullmatch(identity):
            raise ValueError('Trusted expected ' + label + ' identity is required')
    delivery_root = regular(delivery_dir, directory=True)
    payload_root = regular(payload_dir, directory=True)
    readback_root = regular(readback_dir, directory=True)
    bundle_root = regular(bundle_dir, directory=True)
    if (readback_root.is_relative_to(payload_root)
            or payload_root.is_relative_to(readback_root)
            or readback_root.is_relative_to(delivery_root)
            or delivery_root.is_relative_to(readback_root)):
        raise ValueError('Provider readback must be separate from payload and delivery')
    names = {
        'private-preview-observation.json', 'floot-readback-receipt.json',
        'floot-source-snapshot.json', 'readback-observation-bundle.json',
    }
    if {path.name for path in bundle_root.iterdir()} != names:
        raise ValueError('Private readback observation bundle inventory changed')
    manifest = verify_upload_payload(
        delivery_root, expected_delivery_identity_sha256, payload_root)
    manifest_path = regular(
        payload_root / 'floot-upload-manifest.json', limit=MAX_MANIFEST)
    manifest_raw = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    snapshot_path = bundle_root / 'floot-source-snapshot.json'
    snapshot_raw, snapshot = _read_source_snapshot(
        snapshot_path, expected_source_snapshot_sha256, manifest, manifest_sha)
    if (_utc_timestamp(snapshot['observed_at'], 'source observation timestamp')
            < _delivery_completion(
                delivery_root, next(item['sha256'] for item in manifest['objects']
                                    if item['role'] == 'delivery_receipt'))):
        raise ValueError('Floot source observation predates durable delivery completion')
    receipt_path = bundle_root / 'floot-readback-receipt.json'
    receipt_raw, receipt = _read_readback_receipt(
        receipt_path, expected_readback_receipt_sha256, manifest, snapshot,
        expected_source_snapshot_sha256, manifest_sha)
    _, logical_objects, retained = _readback_objects(
        readback_root, manifest, payload_root, delivery_root)
    observation_path = regular(
        bundle_root / 'private-preview-observation.json', limit=MAX_MANIFEST)
    binding = verify_private_preview_binding(
        delivery_root, expected_delivery_identity_sha256,
        observation_path, expected_observation_sha256)
    if (binding.get('status') != 'PASS'
            or binding.get('provider') != snapshot['provider']
            or binding.get('project_id') != snapshot['project_id']
            or binding.get('source_version') != snapshot['source_version']
            or binding.get('source_checkpoint') != snapshot['source_checkpoint']
            or binding.get('source_files_sha256') != snapshot['source_files_sha256']
            or binding.get('observed_at') != receipt['readback_completed_at']
            or binding.get('objects') != sorted(
                logical_objects, key=lambda item: item['role'])):
        raise ValueError('Logical observation is not bound to physical readback evidence')
    expected = _bundle_receipt(
        manifest, manifest_sha, snapshot, expected_source_snapshot_sha256,
        expected_readback_receipt_sha256, expected_observation_sha256)
    bundle_receipt_path = regular(
        bundle_root / 'readback-observation-bundle.json', limit=MAX_MANIFEST)
    bundle_raw = bundle_receipt_path.read_bytes()
    if hashlib.sha256(bundle_raw).hexdigest() != expected_bundle_receipt_sha256:
        raise ValueError('Readback bundle receipt does not match trusted expected identity')
    try:
        bundle_receipt = parse_json(bundle_raw.decode('utf-8'))
    except UnicodeDecodeError as error:
        raise ValueError('Readback bundle receipt is invalid') from error
    if (not isinstance(bundle_receipt, dict)
            or set(bundle_receipt) != BUNDLE_RECEIPT_FIELDS
            or bundle_receipt != expected):
        raise ValueError('Readback bundle receipt schema or identity binding is invalid')
    if (verify_upload_payload(
            delivery_root, expected_delivery_identity_sha256, payload_root) != manifest
            or manifest_path.read_bytes() != manifest_raw
            or snapshot_path.read_bytes() != snapshot_raw
            or receipt_path.read_bytes() != receipt_raw
            or bundle_receipt_path.read_bytes() != bundle_raw
            or digest(observation_path) != expected_observation_sha256
            or _readback_objects(
                readback_root, manifest, payload_root, delivery_root)[2] != retained):
        raise ValueError('Readback bundle inputs changed during replay')
    replay = {key: value for key, value in expected.items()
              if key not in {'schema_version', 'status'}}
    return {'schema_version': 1, 'status': 'PASS',
            'bundle_status': expected['status'],
            'bundle_receipt_sha256': expected_bundle_receipt_sha256, **replay}


def build_readback_observation(delivery_dir, expected_delivery_identity_sha256,
                               payload_dir, readback_dir, source_snapshot_path,
                               expected_source_snapshot_sha256,
                               readback_receipt_path,
                               expected_readback_receipt_sha256, output):
    """Build, but do not externally trust, a strict five-role observation."""
    if any(os.environ.get(name, 'false').lower() != 'false'
           for name in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED',
                        'PAID_INFERENCE_ENABLED')):
        raise ValueError('Publishing and paid generation/inference must remain disabled')
    delivery_root = regular(delivery_dir, directory=True)
    payload_root = regular(payload_dir, directory=True)
    readback_root = regular(readback_dir, directory=True)
    snapshot_path = regular(source_snapshot_path, limit=MAX_MANIFEST)
    receipt_path = regular(readback_receipt_path, limit=MAX_MANIFEST)
    output = Path(os.path.abspath(output))
    parent = regular(output.parent, directory=True)
    if (output.exists() or output.is_symlink()
            or any(output.is_relative_to(root) or root.is_relative_to(output)
                   for root in (delivery_root, payload_root, readback_root))):
        raise ValueError('Fresh observation bundle separate from all inputs required')
    if (readback_root.is_relative_to(payload_root)
            or payload_root.is_relative_to(readback_root)
            or readback_root.is_relative_to(delivery_root)
            or delivery_root.is_relative_to(readback_root)):
        raise ValueError('Provider readback must be separate from payload and delivery')
    manifest = verify_upload_payload(
        delivery_root, expected_delivery_identity_sha256, payload_root)
    manifest_path = regular(
        payload_root / 'floot-upload-manifest.json', limit=MAX_MANIFEST)
    manifest_raw = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    if (verify_upload_payload(
            delivery_root, expected_delivery_identity_sha256, payload_root) != manifest
            or manifest_path.read_bytes() != manifest_raw):
        raise ValueError('Private upload manifest changed before readback binding')
    snapshot_raw, snapshot = _read_source_snapshot(
        snapshot_path, expected_source_snapshot_sha256, manifest, manifest_sha)
    if (_utc_timestamp(snapshot['observed_at'], 'source observation timestamp')
            < _delivery_completion(
                delivery_root, next(item['sha256'] for item in manifest['objects']
                                    if item['role'] == 'delivery_receipt'))):
        raise ValueError('Floot source observation predates durable delivery completion')
    receipt_raw, receipt = _read_readback_receipt(
        receipt_path, expected_readback_receipt_sha256, manifest, snapshot,
        expected_source_snapshot_sha256, manifest_sha)
    _, objects, retained = _readback_objects(
        readback_root, manifest, payload_root, delivery_root)
    observation = {
        'schema_version': 1,
        'status': 'UNPUBLISHED_PRIVATE_PREVIEW_OBSERVED',
        'provider': snapshot['provider'],
        'project_id': snapshot['project_id'],
        'source_version': snapshot['source_version'],
        'source_checkpoint': snapshot['source_checkpoint'],
        'source_files_sha256': snapshot['source_files_sha256'],
        'source_manifest_sha256': hashlib.sha256(
            canonical(snapshot['source_files_sha256']).encode()).hexdigest(),
        'observed_at': receipt['readback_completed_at'],
        'visibility': 'private',
        'objects': objects,
        'scope': OBSERVATION_SCOPE,
        **FLAGS,
    }
    stage = Path(tempfile.mkdtemp(
        prefix='.floot-readback-observation-', dir=parent))
    output_identity = None
    try:
        observation_path = stage / 'private-preview-observation.json'
        observation_path.write_text(
            json.dumps(observation, indent=2, sort_keys=True, allow_nan=False) + '\n')
        os.chmod(observation_path, 0o600)
        retained_receipt_path = stage / 'floot-readback-receipt.json'
        with retained_receipt_path.open('xb') as retained_receipt:
            retained_receipt.write(receipt_raw)
        os.chmod(retained_receipt_path, 0o600)
        retained_snapshot_path = stage / 'floot-source-snapshot.json'
        with retained_snapshot_path.open('xb') as retained_snapshot:
            retained_snapshot.write(snapshot_raw)
        os.chmod(retained_snapshot_path, 0o600)
        observation_sha = digest(observation_path)
        bundle_receipt = _bundle_receipt(
            manifest, manifest_sha, snapshot, expected_source_snapshot_sha256,
            expected_readback_receipt_sha256, observation_sha)
        bundle_receipt_path = stage / 'readback-observation-bundle.json'
        bundle_receipt_path.write_text(json.dumps(
            bundle_receipt, indent=2, sort_keys=True, allow_nan=False) + '\n')
        os.chmod(bundle_receipt_path, 0o600)
        bundle_receipt_sha = digest(bundle_receipt_path)
        binding = verify_private_preview_binding(
            delivery_root, expected_delivery_identity_sha256,
            observation_path, observation_sha)
        if binding.get('status') != 'PASS':
            raise ValueError('Complete provider readback did not produce a strict binding')
        if (verify_upload_payload(
                delivery_root, expected_delivery_identity_sha256, payload_root) != manifest
                or manifest_path.read_bytes() != manifest_raw
                or snapshot_path.read_bytes() != snapshot_raw
                or receipt_path.read_bytes() != receipt_raw
                or _readback_objects(
                    readback_root, manifest, payload_root, delivery_root)[2] != retained):
            raise ValueError(
                'Payload, source snapshot, receipt, or readback changed during observation')
        stage_stat = stage.stat(follow_symlinks=False)
        output_identity = (stage_stat.st_dev, stage_stat.st_ino)
        _publish_restore(stage, output)
        published_observation = regular(
            output / 'private-preview-observation.json', limit=MAX_MANIFEST)
        published_receipt = regular(
            output / 'floot-readback-receipt.json', limit=MAX_MANIFEST)
        published_snapshot = regular(
            output / 'floot-source-snapshot.json', limit=MAX_MANIFEST)
        published_bundle_receipt = regular(
            output / 'readback-observation-bundle.json', limit=MAX_MANIFEST)
        if ({path.name for path in output.iterdir()} != {
                'private-preview-observation.json', 'floot-readback-receipt.json',
                'floot-source-snapshot.json', 'readback-observation-bundle.json'}
                or digest(published_observation) != observation_sha
                or digest(published_receipt) != expected_readback_receipt_sha256
                or digest(published_snapshot) != expected_source_snapshot_sha256
                or digest(published_bundle_receipt) != bundle_receipt_sha
                or verify_readback_observation_bundle(
                    delivery_root, expected_delivery_identity_sha256,
                    payload_root, readback_root, output,
                    expected_source_snapshot_sha256,
                    expected_readback_receipt_sha256, observation_sha,
                    bundle_receipt_sha).get('status') != 'PASS'):
            raise ValueError('Published readback observation bundle changed')
        return {'bundle_receipt_sha256': bundle_receipt_sha, **bundle_receipt}
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        if output_identity is not None:
            try:
                current = output.stat(follow_symlinks=False)
            except FileNotFoundError:
                current = None
            if (current is not None and not output.is_symlink()
                    and output.is_dir()
                    and (current.st_dev, current.st_ino) == output_identity):
                shutil.rmtree(output)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'verify'):
        command = commands.add_parser(name)
        command.add_argument('--delivery', required=True)
        command.add_argument('--expected-delivery-identity', required=True)
        command.add_argument('--payload', required=True)
    readback = commands.add_parser('build-observation')
    readback.add_argument('--delivery', required=True)
    readback.add_argument('--expected-delivery-identity', required=True)
    readback.add_argument('--payload', required=True)
    readback.add_argument('--readback', required=True)
    readback.add_argument('--source-snapshot', required=True)
    readback.add_argument('--expected-source-snapshot-identity', required=True)
    readback.add_argument('--readback-receipt', required=True)
    readback.add_argument('--expected-readback-receipt-identity', required=True)
    readback.add_argument('--output', required=True)
    replay = commands.add_parser('verify-observation')
    replay.add_argument('--delivery', required=True)
    replay.add_argument('--expected-delivery-identity', required=True)
    replay.add_argument('--payload', required=True)
    replay.add_argument('--readback', required=True)
    replay.add_argument('--bundle', required=True)
    replay.add_argument('--expected-source-snapshot-identity', required=True)
    replay.add_argument('--expected-readback-receipt-identity', required=True)
    replay.add_argument('--expected-observation-identity', required=True)
    replay.add_argument('--expected-bundle-receipt-identity', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare_upload_payload(
                args.delivery, args.expected_delivery_identity, args.payload)
        elif args.command == 'verify':
            result = verify_upload_payload(
                args.delivery, args.expected_delivery_identity, args.payload)
        elif args.command == 'build-observation':
            result = build_readback_observation(
                args.delivery, args.expected_delivery_identity, args.payload,
                args.readback, args.source_snapshot,
                args.expected_source_snapshot_identity, args.readback_receipt,
                args.expected_readback_receipt_identity, args.output)
        else:
            result = verify_readback_observation_bundle(
                args.delivery, args.expected_delivery_identity, args.payload,
                args.readback, args.bundle,
                args.expected_source_snapshot_identity,
                args.expected_readback_receipt_identity,
                args.expected_observation_identity,
                args.expected_bundle_receipt_identity)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'schema_version': 1, 'status': 'BLOCKED',
                          **FLAGS, 'reason': str(error), 'scope': SCOPE}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
