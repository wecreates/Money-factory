"""Portable review checkpoints; integrity is not audiovisual approval.

Only the files needed to inspect/review/revise a completed cycle are retained.
Voice models, raw stems, motion frames, credentials and unrelated files are not.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import zipfile

from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control.review_package import digest, no_symlinks, require, SHA

FILES = frozenset(['cycle.json', 'brief.json', 'editorial.json'] +
                  ['render/' + n for n in ('video.mp4', 'captions.vtt', 'render.json')] +
                  ['delivery/' + n for n in ('video.mp4', 'captions.vtt', 'render.json',
                   'editorial.json', 'index.html', 'thumbnail-1.png', 'thumbnail-2.png',
                   'thumbnail-3.png', 'package.json', 'review-package.zip')])
OPTIONAL_FILES = frozenset({'delivery/automated-review.json'})
FILE_LIMIT = 256 * 1024 * 1024
TOTAL_LIMIT = 1024 * 1024 * 1024
MANIFEST_LIMIT = 64 * 1024
FLAGS = {k: False for k in ('publication_enabled', 'paid_generation_enabled',
                           'production_approved', 'full_av_review', 'production_ready')}


def _path(path):
    path = Path(os.path.abspath(path)); no_symlinks(path)
    return path


def _identities(root, files):
    result = {}; total = 0
    for name in sorted(files):
        path = root / name; no_symlinks(path)
        require(path.is_file(), 'Missing checkpoint input: ' + name)
        size = path.stat().st_size; total += size
        require(size <= FILE_LIMIT and total <= TOTAL_LIMIT, 'Checkpoint size limit exceeded')
        result[name] = {'sha256': digest(path), 'size': size}
    return result


def create_checkpoint(cycle_dir, output):
    root, output = _path(cycle_dir), _path(output)
    require(not output.exists() and not output.is_relative_to(root), 'Fresh checkpoint outside cycle required')
    snapshot = inspect_cycle(root)
    snapshot_names = set(snapshot['files_sha256'])
    require(snapshot_names <= FILES | OPTIONAL_FILES, 'Unsupported additional package files')
    files = FILES | (snapshot_names & OPTIONAL_FILES)
    identities = _identities(root, files)
    manifest = {'schema_version': 1, 'candidate_sha256': snapshot['candidate_sha256'],
                'files': identities, 'created_at': datetime.now(timezone.utc).isoformat(), **FLAGS,
                'scope': 'Review/revision checkpoint only; raw synthesis and animation diagnostics excluded.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.cycle-checkpoint-', suffix='.zip', dir=output.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr('checkpoint.json', json.dumps(manifest, sort_keys=True, allow_nan=False))
            for name in sorted(files):
                bundle.write(root / name, name)
        require(inspect_cycle(root) == snapshot and _identities(root, files) == identities, 'Cycle changed during checkpoint')
        # Check the bytes actually archived, not just the original files.
        with zipfile.ZipFile(temporary) as bundle:
            for name, identity in identities.items():
                with bundle.open(name) as stream:
                    require(hashlib.file_digest(stream, 'sha256').hexdigest() == identity['sha256'], 'Archived input changed')
        require(temporary.stat().st_size <= TOTAL_LIMIT + MANIFEST_LIMIT, 'Checkpoint archive too large')
        archive_hash = digest(temporary)
        os.link(temporary, output)  # Exclusive publication, never overwrite an existing checkpoint.
        return {'status': 'CHECKPOINT_CREATED', 'checkpoint_sha256': archive_hash,
                'candidate_sha256': snapshot['candidate_sha256'], **FLAGS}
    finally:
        temporary.unlink(missing_ok=True)


def _publish_restore(source, output):
    """Atomically publish without replacing a concurrent destination."""
    if os.name == 'nt':
        os.rename(source, output)  # Windows rename fails if destination exists.
    elif sys.platform.startswith('linux'):
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, 'renameat2', None)
        require(rename is not None, 'Atomic no-replace restore unavailable on this platform')
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(output), 1) != 0:
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number), str(output))
    else:
        raise ValueError('Atomic no-replace restore requires Linux or Windows')


def restore_checkpoint(archive, output, *, expected_sha256):
    archive, output = _path(archive), _path(output)
    require(isinstance(expected_sha256, str) and SHA.fullmatch(expected_sha256), 'External expected checkpoint SHA-256 required')
    require(archive.is_file() and archive.stat().st_size <= TOTAL_LIMIT + MANIFEST_LIMIT, 'Missing or oversized checkpoint')
    require(not output.exists() and not archive.is_relative_to(output), 'Fresh separate restore directory required')
    require(digest(archive) == expected_sha256, 'Checkpoint identity mismatch')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.cycle-restore-', dir=output.parent))
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            names = {member.filename for member in members}
            artifacts = names - {'checkpoint.json'}
            require(len(members) == len(names) and 'checkpoint.json' in names
                    and FILES <= artifacts <= (FILES | OPTIONAL_FILES),
                    'Unexpected, duplicate or missing checkpoint members')
            total = 0
            for member in members:
                mode = member.external_attr >> 16
                require(stat.S_IFMT(mode) in (0, stat.S_IFREG) and not member.is_dir() and not member.flag_bits & 1,
                        'Nonregular or encrypted checkpoint member')
                limit = MANIFEST_LIMIT if member.filename == 'checkpoint.json' else FILE_LIMIT
                total += member.file_size
                require(0 <= member.file_size <= limit and total <= TOTAL_LIMIT + MANIFEST_LIMIT, 'Checkpoint member size limit exceeded')
            manifest = json.loads(bundle.read('checkpoint.json'))
            require(isinstance(manifest, dict) and type(manifest.get('schema_version')) is int and manifest['schema_version'] == 1,
                    'Checkpoint schema mismatch')
            require(all(manifest.get(k) is False for k in FLAGS), 'Checkpoint approval flags must remain false')
            files = manifest.get('files')
            require(isinstance(files, dict) and set(files) == artifacts, 'Checkpoint manifest files mismatch')
            for name in sorted(artifacts):
                expected = files[name]
                require(isinstance(expected, dict) and isinstance(expected.get('sha256'), str) and
                        SHA.fullmatch(expected['sha256']) and type(expected.get('size')) is int and
                        expected['size'] == bundle.getinfo(name).file_size, 'Invalid checkpoint member identity')
                path = temporary / name; path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(name) as source, path.open('xb') as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                require(digest(path) == expected['sha256'], 'Restored member identity mismatch: ' + name)
        snapshot = inspect_cycle(temporary)
        require(snapshot['candidate_sha256'] == manifest.get('candidate_sha256')
                and (artifacts & OPTIONAL_FILES) == (set(snapshot['files_sha256']) & OPTIONAL_FILES)
                and _identities(temporary, artifacts) == files,
                'Restored checkpoint differs from manifest')
        require(digest(archive) == expected_sha256, 'Checkpoint changed during restore')
        no_symlinks(output); require(not output.exists(), 'Restore output appeared during validation')
        _publish_restore(temporary, output)
        return {'status': 'RESTORED_AWAITING_REVIEW', 'candidate_sha256': snapshot['candidate_sha256'],
                'checkpoint_sha256': expected_sha256, **FLAGS}
    finally:
        if temporary.exists(): shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create'); create.add_argument('--cycle-dir', required=True); create.add_argument('--output', required=True)
    restore = commands.add_parser('restore'); restore.add_argument('--archive', required=True); restore.add_argument('--output', required=True)
    restore.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    result = (create_checkpoint(args.cycle_dir, args.output) if args.command == 'create' else
              restore_checkpoint(args.archive, args.output, expected_sha256=args.expected_sha256))
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
