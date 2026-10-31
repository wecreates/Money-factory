"""Original, dependency-free file boundaries for review-only media adapters."""
import hashlib
import json
import os
from pathlib import Path
import stat


def require_disabled(value):
    if not isinstance(value, dict) or any(value.get(key) is not False for key in
            ('publication_enabled', 'paid_generation_enabled')):
        raise ValueError('Explicit publication_enabled=false and paid_generation_enabled=false required')


def read_bytes(value, limit):
    if not isinstance(value, (str, Path)) or not str(value):
        raise ValueError('Local file path required')
    # Reject before normalization: collapsing symlink/../ can identify different
    # bytes from the original locator later emitted to a downstream consumer.
    if '..' in Path(value).parts:
        raise ValueError('Parent traversal is not accepted in local file paths')
    path = Path(os.path.abspath(value))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Linked file paths are not accepted')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError('Expected a bounded, nonempty regular file')
        chunks, count = [], 0
        while count <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - count))
            if not chunk:
                break
            chunks.append(chunk)
            count += len(chunk)
        after = os.fstat(fd)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if count > limit or count != before.st_size or identity(before) != identity(after):
            raise ValueError('File changed during validation')
        if identity(before) != identity(os.stat(path, follow_symlinks=False)):
            raise ValueError('File path changed during validation')
        return b''.join(chunks)
    finally:
        os.close(fd)


def read_json(value, limit=2 * 1024 * 1024):
    def reject_constant(_):
        raise ValueError('Non-finite JSON value')
    result = json.loads(read_bytes(value, limit), parse_constant=reject_constant)
    if not isinstance(result, dict):
        raise ValueError('JSON object required')
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_digest(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def result(tool, operation, **fields):
    return {'schema_version': 1, 'status': 'PASS', 'tool': tool, 'operation': operation,
            **fields, 'publication_enabled': False, 'paid_generation_enabled': False,
            'provider_calls': 0, 'production_ready': False, 'quality_gate_required': True,
            'commercial_rights_verified': False}
