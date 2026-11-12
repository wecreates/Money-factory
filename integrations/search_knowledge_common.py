"""Bounded, data-only import helpers. No network, credentials, or upstream execution."""
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit


def guard(job):
    if job.get('publication_enabled') is not False or job.get('paid_generation_enabled') is not False:
        raise ValueError('Explicit publication_enabled=false and paid_generation_enabled=false required')
    if job.get('network_enabled', False) is not False or job.get('paid_services_enabled', False) is not False:
        raise ValueError('Network and paid services are not supported by this offline bridge')


def load(job):
    path = Path(job['input'])
    if '..' in path.parts:
        raise ValueError('Parent traversal is not accepted')
    path = path.absolute()
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent_fd = os.open('/', directory_flags)
    try:
        for component in path.parent.parts[1:]:
            child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = child_fd
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    except OSError as error:
        raise ValueError('Input must be an ordinary file without linked path components') from error
    finally:
        os.close(parent_fd)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024 * 1024:
            raise ValueError('Input must be a regular JSON file no larger than 2 MiB')
        raw = handle.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Input exceeds 2 MiB')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON keys are not accepted')
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if not isinstance(value, dict):
        raise ValueError('Input must be a JSON object')
    return value, hashlib.sha256(raw).hexdigest()


def text(value, name, maximum=2000, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > maximum or '\0' in value:
        raise ValueError(f'{name} must be bounded text')
    return value


def number(value, name, minimum=0, maximum=1e9, integer=False):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum or (integer and int(value) != value):
        raise ValueError(f'Invalid {name}')
    return value


def safe_url(value):
    value = text(value, 'URL', 4096)
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Only credential-free HTTP(S) source URLs are accepted')
    return value


def result(tool, operation, revision, **fields):
    return {'schema_version': 1, 'tool': tool, 'operation': operation, 'status': 'PASS',
            'upstream_revision': revision, 'network_executed': False, 'paid_services_enabled': False,
            'paid_generation_enabled': False, 'publication_enabled': False, 'production_ready': False,
            'upstream_runtime_verified': False, **fields}
