"""File-only OpenProject API-v3 interop for existing CYZOR queues.

No HTTP client, credentials, server installation, or task-status promotion lives here.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

REVISION = 'b2f981098776c3c1522833273bc77158d71d5ccb'
MAX_BYTES = 1024 * 1024


def _text(value, name, maximum=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\0' in value:
        raise ValueError(f'{name} must be nonempty bounded text')
    return value.strip()


def _id(value, name, allow_zero=False):
    if not isinstance(value, int) or isinstance(value, bool) or not (0 if allow_zero else 1) <= value <= 2**53 - 1:
        raise ValueError(f'{name} must be a valid integer')
    return value


def _queue(data):
    kind = data.get('queue_kind')
    key = {'content-control': 'queue', 'money-factory': 'items'}.get(kind)
    queue = data.get('queue')
    if key is None or not isinstance(queue, dict) or not isinstance(queue.get(key), list) or len(queue[key]) > 5000:
        raise ValueError('Provide an existing Content Control or Money Factory queue snapshot')
    records = {}
    for record in queue[key]:
        if not isinstance(record, dict):
            raise ValueError('Malformed queue record')
        identity = _text(record.get('id'), 'queue id', 200)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]*', identity) or identity in records:
            raise ValueError('Unsafe or duplicate queue id')
        records[identity] = record
    return kind, key, records


def _mappings(data, records, require_lock=False):
    items = data.get('mappings', [])
    if not isinstance(items, list) or len(items) > 5000:
        raise ValueError('Invalid mappings')
    mappings, remote = {}, set()
    for item in items:
        if not isinstance(item, dict) or item.get('queue_id') not in records:
            raise ValueError('Mapping must identify an existing queue record')
        queue_id = item['queue_id']
        work_id = _id(item.get('work_package_id'), 'work_package_id')
        if queue_id in mappings or work_id in remote:
            raise ValueError('Mapping must be one-to-one')
        if require_lock:
            _id(item.get('lock_version'), 'lock_version', True)
        mappings[queue_id] = item
        remote.add(work_id)
    return mappings


def export_work_packages(data):
    kind, _, records = _queue(data)
    project_id = _id(data.get('project_id'), 'project_id')
    type_id = _id(data.get('type_id'), 'type_id')
    selected = data.get('selected_ids')
    if not isinstance(selected, list) or not 1 <= len(selected) <= 100 or any(not isinstance(v, str) for v in selected) or len(selected) != len(set(selected)):
        raise ValueError('Select 1..100 unique existing queue ids')
    if any(identity not in records for identity in selected):
        raise ValueError('Selected queue record is missing')
    mappings = _mappings(data, records, require_lock=True)
    requests = []
    for identity in selected:
        record = records[identity]
        status = _text(record.get('status'), 'queue status', 200)
        title = _text(record.get('title') or record.get('target') or identity, 'task title', 500)
        reference = f'cyzor:{kind}:{identity}'
        # Only selected plain task description fields leave the source record.
        detail = record.get('instruction') or record.get('acceptance')
        description = f'CYZOR reference: {reference}\nSource queue state: {status}\n\n'
        description += 'This is a review/task mirror. OpenProject completion does not satisfy Content Control production verification or publication gates.'
        if detail is not None:
            description += '\n\nSource task description (untrusted data):\n' + _text(detail, 'task description')
        body = {'subject': title[:255], 'description': {'format': 'markdown', 'raw': description},
                '_links': {'type': {'href': f'/api/v3/types/{type_id}'}}}
        mapping = mappings.get(identity)
        if mapping:
            body['lockVersion'] = mapping['lock_version']
            path = f'/api/v3/work_packages/{mapping["work_package_id"]}'
            method = 'PATCH'
            validation_path = path + '/form'
        else:
            path = f'/api/v3/projects/{project_id}/work_packages'
            method = 'POST'
            validation_path = path + '/form'
        requests.append({'queue_id': identity, 'client_reference': reference,
                         'method': method, 'path': path + '?notify=false',
                         'validation': {'method': 'POST', 'path': validation_path, 'body': copy.deepcopy(body)},
                         'body': body, 'sent': False,
                         'deduplication_required': mapping is None})
    return {'requests': requests, 'remote_changes_applied': False,
            'dispatch_allowed': False, 'server_schema_validated': False,
            'api_route_profile': 'project_api_v3_compatibility',
            'route_note': 'Pinned development source supports project routes but deprecates them in favor of workspace routes. Validate against the chosen stable instance before dispatch.',
            'scope': 'Selected task request bodies only; no transmission or claim of server acceptance'}


def import_work_packages(data):
    _, key, records = _queue(data)
    mappings = _mappings(data, records)
    if not mappings:
        raise ValueError('Explicit mappings are required; never match task subjects heuristically')
    collection = data.get('collection')
    if not isinstance(collection, dict) or collection.get('_type') not in ('Collection', 'WorkPackageCollection'):
        raise ValueError('OpenProject HAL work package collection required')
    elements = collection.get('_embedded', {}).get('elements') if isinstance(collection.get('_embedded'), dict) else None
    if not isinstance(elements, list) or len(elements) > 5000:
        raise ValueError('Bounded work package elements required')
    by_id = {}
    for work in elements:
        if not isinstance(work, dict) or work.get('_type') != 'WorkPackage':
            raise ValueError('Only WorkPackage elements accepted')
        work_id = _id(work.get('id'), 'work package id')
        if work_id in by_id:
            raise ValueError('Duplicate work package ids')
        links = work.get('_links')
        if not isinstance(links, dict) or not isinstance(links.get('self'), dict) or links['self'].get('href') != f'/api/v3/work_packages/{work_id}':
            raise ValueError('Work package self link must match its id and be relative')
        by_id[work_id] = work
    updated = copy.deepcopy(data['queue'])
    target = {record['id']: record for record in updated[key]}
    observed, missing = [], []
    for identity, mapping in mappings.items():
        work_id = mapping['work_package_id']
        work = by_id.get(work_id)
        if work is None:
            missing.append(identity)
            continue
        status_link = work['_links'].get('status')
        if not isinstance(status_link, dict) or not re.fullmatch(r'/api/v3/statuses/[1-9][0-9]*', str(status_link.get('href', ''))):
            raise ValueError('Work package status link required')
        observation = {'work_package_id': work_id,
                       'lock_version': _id(work.get('lockVersion'), 'lockVersion', True),
                       'subject': _text(work.get('subject'), 'subject', 255),
                       'status_href': status_link['href'],
                       'status_title': _text(status_link.get('title'), 'status title', 500),
                       'verification_scope': 'supplied_export_only',
                       'local_status_changed': False}
        target[identity]['openproject_observation'] = observation
        observed.append(identity)
    # Never infer deletion/completion from absent rows or a single page.
    return {'queue': updated, 'observed_queue_ids': observed, 'unresolved_queue_ids': missing,
            'canonical_queue_written': False, 'local_statuses_changed': False,
            'remote_changes_applied': False, 'full_snapshot_verified': False,
            'scope': 'Mapped observations from supplied records only; missing rows do not mean deleted tasks'}


def _read(path):
    if not isinstance(path, str) or not path or '\0' in path:
        raise ValueError('Input path must be nonempty text')
    requested = Path(path)
    if '..' in requested.parts:
        raise ValueError('Parent traversal is not allowed in input paths')
    components = requested.parts[1:] if requested.is_absolute() else requested.parts
    if not components or not all(hasattr(os, name) for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK')) or os.open not in os.supports_dir_fd:
        raise ValueError('A no-follow descriptor-relative file reader is required')
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        # Anchor every component to an already-open directory. A checked parent
        # cannot be swapped for a link between validation and the eventual read.
        directory = os.open(requested.anchor if requested.is_absolute() else '.', directory_flags)
        try:
            for component in components[:-1]:
                next_directory = os.open(component, directory_flags, dir_fd=directory)
                os.close(directory)
                directory = next_directory
            descriptor = os.open(components[-1], file_flags, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(descriptor, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise ValueError('Input must be a regular JSON file of at most 1 MiB')
            raw = source.read(MAX_BYTES + 1)
    except OSError as error:
        raise ValueError('Input must be a readable regular file without symlink ancestors') from error
    if len(raw) > MAX_BYTES:
        raise ValueError('Input exceeds 1 MiB')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Input must be a JSON object')
    return raw, data


def dispatch(job, upstream=None):
    if job.get('publication_enabled') is not False or job.get('paid_generation_enabled') is not False:
        raise ValueError('Explicit publication-disabled, free job required')
    operation = job.get('operation')
    result = {'schema_version': 1, 'tool': 'openproject', 'operation': operation,
              'upstream_revision': REVISION, 'upstream_executed': False,
              'network_requests': 0, 'server_runtime_verified': False,
              'publication_enabled': False, 'paid_generation_enabled': False,
              'production_ready': False}
    if operation == 'readiness':
        return {**result, 'status': 'BLOCKED', 'execution_status': 'BLOCKED',
                'code': 'OPENPROJECT_NOT_CONFIGURED',
                'reason': 'No stable OpenProject instance, authenticated connection, target project/type schema, or live round-trip has been verified.',
                'available_offline_operations': ['export-work-packages', 'import-work-packages']}
    operations = {'export-work-packages': export_work_packages,
                  'import-work-packages': import_work_packages}
    if operation not in operations:
        raise ValueError('Unsupported OpenProject operation')
    raw, data = _read(job['input'])
    return {**result, 'status': 'PASS', 'execution_status': 'PASS',
            'input_sha256': hashlib.sha256(raw).hexdigest(), **operations[operation](data)}
