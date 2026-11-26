"""Stage one verified private delivery for immutable Floot object upload.

This module performs no provider write.  It copies exactly the five objects
required by the private-preview binding into a fresh local payload, assigns
deterministic add-only storage keys, and replays both source and staged bytes.
Playback, readback, deployment, creative and audiovisual acceptance remain
separate evidence.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from integrations.local_agent_queue import canonical
from integrations.content_control.cycle_checkpoint import _publish_restore
from integrations.content_control.private_preview_binding import FLAGS, ROLE_PATHS
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'verify'):
        command = commands.add_parser(name)
        command.add_argument('--delivery', required=True)
        command.add_argument('--expected-delivery-identity', required=True)
        command.add_argument('--payload', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare_upload_payload(
                args.delivery, args.expected_delivery_identity, args.payload)
        else:
            result = verify_upload_payload(
                args.delivery, args.expected_delivery_identity, args.payload)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'schema_version': 1, 'status': 'BLOCKED',
                          **FLAGS, 'reason': str(error), 'scope': SCOPE}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
