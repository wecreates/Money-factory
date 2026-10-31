"""Explicit, offline-only dispatch for the 2026-10-23 source integrations.

These operations execute project-owned adapters, never downloaded upstream code.
The legacy VoiceStudio synthesis runtime and its original source pin are separate.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

BRIDGES = {
    'hypit': ('hypit.adapter', 'e26d9142fd8a6f78bf4f3cdb800d6205f4ecca16',
              ('status', 'prepare-project', 'validate-export')),
    'open-seo': ('open_seo.adapter', '2d8236a4fd5d799bf5c089187d0131f4dac4f38c',
                 ('readiness', 'prepare-research', 'import-serp')),
    'weknora': ('weknora.adapter', '30658b7d43bf6415537435c42a5c4e95f2766b8d',
                ('readiness', 'prepare-search', 'import-search')),
    'openwhispr': ('openwhispr.adapter', '7a6ae826de9ec1caf65f3a6e769475dab2ae829f',
                   ('readiness', 'import-transcript')),
    'openproject': ('openproject.adapter', 'b2f981098776c3c1522833273bc77158d71d5ccb',
                    ('readiness', 'export-work-packages', 'import-work-packages')),
    'open-higgsfield': ('open_higgsfield.adapter', 'b16a0efe4d7e2707b56f8ccb02387fd2a9d2eddf',
                       ('status', 'prepare-generation', 'validate-export')),
    'voicestudio': ('voicestudio.reel_adapter', '311effa5f7b9ca8f2559de7f91fccf35d686e981',
                    ('status', 'prepare-narration', 'validate-export')),
}


def _owned_adapter(module_name):
    # Namespace-package resolution can prefer an unrelated installed package.
    # Load the exact repository-owned file with a private module name instead.
    path = Path(__file__).absolute().parent.joinpath(*module_name.split('.')).with_suffix('.py')
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
        raise ValueError('Repository-owned adapter file is missing or linked')
    spec = importlib.util.spec_from_file_location('_cyzor_offline_' + module_name.replace('.', '_'), path)
    if spec is None or spec.loader is None or spec.origin != str(path):
        raise ValueError('Invalid repository-owned adapter origin')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def handles(job):
    config = BRIDGES.get(job.get('tool'))
    return config is not None and job.get('operation') in config[2]


def _output_parent(value):
    if not isinstance(value, (str, Path)) or not str(value) or '..' in Path(value).parts:
        raise ValueError('Output requires an ordinary local path without parent traversal')
    path = Path(value).absolute()
    # Hold a descriptor for each traversed directory. O_NOFOLLOW on every step
    # rejects linked parents, including links swapped during a path-based check.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', flags)
    try:
        for component in path.parent.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd, path.name
    except BaseException:
        os.close(fd)
        raise


def _new_json(parent_fd, name, value):
    # O_EXCL rejects both extant files and dangling symlinks. Never overwrite evidence.
    raw = (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(raw)
    return raw


def run_bridge(job, registry):
    if not handles(job):
        raise ValueError('Unreviewed bridge operation')
    if job.get('publication_enabled') is not False or job.get('paid_generation_enabled') is not False:
        raise ValueError('Explicit disabled publication and paid generation required')
    if job.get('network_enabled', False) is not False or job.get('paid_services_enabled', False) is not False:
        raise ValueError('Bridge jobs cannot enable network or paid services')
    tool, operation = job['tool'], job['operation']
    module, revision, operations = BRIDGES[tool]
    entries = [entry for entry in registry.get('external_bridges', []) if entry.get('id') == tool]
    if len(entries) != 1 or entries[0].get('revision') != revision or entries[0].get('operations') != list(operations):
        raise ValueError('Bridge registry/source contract mismatch')
    if entries[0].get('offline_bridge_enabled') is not True:
        raise ValueError('Offline bridge is disabled in registry')
    # Dispatch before creating output directories so invalid inputs leave no output state.
    value = _owned_adapter(module).dispatch(job, upstream=None)
    if not isinstance(value, dict) or value.get('status') not in ('PASS', 'BLOCKED'):
        raise ValueError('Invalid offline bridge result')
    if value.get('publication_enabled') is not False or value.get('paid_generation_enabled') is not False or value.get('production_ready') is not False:
        raise ValueError('Bridge result violated free/non-production contract')
    parent_fd, name = _output_parent(job['output'])
    try:
        for candidate in (name, name + '.receipt.json'):
            try:
                os.stat(candidate, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ValueError('Output or receipt already exists; use a new job output path')
        raw = _new_json(parent_fd, name, value)
        receipt = {'schema_version': 1, 'tool': tool, 'operation': operation,
                   'revision': revision, 'status': value['status'], 'execution_kind': 'project_owned_offline_adapter',
                   'verified_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   'output_sha256': hashlib.sha256(raw).hexdigest(),
                   'publication_enabled': False, 'paid_generation_enabled': False,
                   'paid_services_enabled': False, 'network_executed': False,
                   'upstream_runtime_verified': False, 'production_ready': False,
                   'scope': 'Only the named offline import/export/preparation/status operation; no upstream service execution'}
        _new_json(parent_fd, name + '.receipt.json', receipt)
        return receipt
    finally:
        os.close(parent_fd)
