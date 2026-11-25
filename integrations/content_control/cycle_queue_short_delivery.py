"""Immutable private delivery for a queue-bound unpublished Short derivative.

The generic review packager expects the standalone ``run.json`` packet schema.
Queue Shorts have a different, already verified receipt contract, so this module
copies and archives that exact contract without pretending the parent cycle is
the derivative.  It never grants playback, creative, production or publishing
approval.
"""
import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED
from urllib.parse import parse_qsl, urlsplit

from integrations.local_agent_queue import canonical
from integrations.content_control.cycle_checkpoint import _publish_restore
from integrations.content_control.cycle_queue_short import (
    FLAGS, _source as _queue_source, verify_consumed_short,
)
from integrations.content_control.cycle_short import (
    COMPACT_STYLE, SAFE_CAPTION_STYLE, _preview_html, _probe, make_short,
    media_identities,
)
from integrations.content_control.cycle_av_review import scan_media, verify_automated_review
from integrations.content_control import cycle_av_benchmarks as benchmarks
from integrations.content_control.cycle_package import run
from integrations.content_control.review_delivery import CYCLE_QUEUE_ADAPTERS
from integrations.content_control.review_package import no_symlinks, require, SHA

FILES = ('video.mp4', 'captions.vtt', 'automated-review.json', 'index.html',
         'short.json', 'queue-short.json')
DELIVERY_BASE_FILES = tuple(name for name in FILES if name != 'queue-short.json')
PROOF_FIELDS = ('verified_intake', 'verified_revision_discovery')
FLAGS_SET = frozenset(FLAGS)
MAX_JSON = 1024 * 1024
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
SCOPE = ('Exact unpublished Short derivative delivery; technical replay does not establish '
         'listening, creative, competitor, phone, production or publishing acceptance.')
QUEUE_SCOPE = ('Exact durable parent-cycle queue completion consumed by the existing bounded '
               'Short exporter; no creative, listening, phone or publishing approval.')
SHORT_SCOPE = ('Unreviewed portrait excerpt; no long-form, creative, listening, phone or '
               'publishing acceptance.')
CAPTION_SCOPE = ('Intersecting source cues clipped/rebased; whole cue text retained even at cut '
                 'boundaries. Review boundary words against audio.')
SHORT_SELECTION_SCOPE = 'Explicit supplied time bounds; not automatic editorial selection.'
PROVENANCE_SCOPE = 'Verified durable queue completion; delivery is not creative or publishing approval'
AUTHORED_SELECTION_SCOPE = ('Contiguous authored scene boundaries from the durable parent render '
                            'receipt, canonicalized to the exporter millisecond contract. This binds '
                            'the cut; it does not establish that the scenes are the best creative selection.')
EXPLICIT_SELECTION_SCOPE = ('Explicit supplied time bounds; not automatic editorial selection or '
                            'creative approval.')
QUEUE_BINDING_SCOPE = ('Verified queue binding projection; complex intake proofs are represented by '
                       'canonical SHA-256 only and do not transfer approval.')
REPORT_FIELDS = frozenset({
    'schema_version', 'status', 'technical_status', *FLAGS_SET,
    'candidate_sha256', 'caption_sha256', 'encoded_streams_sha256',
    'decoded_picture_sha256', 'queue_receipt_sha256', 'parent_provenance',
    'selection', 'files_sha256', 'manifest_sha256', 'archive', 'archive_sha256',
    'entrypoint', 'entrypoint_sha256', 'delivery_identity_sha256', 'scope',
})
OPEN_FLAGS = (os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0)
              | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
METADATA = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')


def _path(path):
    value = Path(os.path.abspath(path))
    no_symlinks(value)
    return value


def _same_metadata(left, right):
    return all(getattr(left, key) == getattr(right, key) for key in METADATA)


def _open_regular(path, limit, label):
    path = Path(path)
    no_symlinks(path.parent)
    require(getattr(os, 'O_NOFOLLOW', 0) and getattr(os, 'O_NONBLOCK', 0),
            'Safe Short delivery descriptor flags are unavailable')
    try:
        descriptor = os.open(path, OPEN_FLAGS)
    except OSError as error:
        raise ValueError(label + ' is unavailable or unsafe') from error
    try:
        opened = os.fstat(descriptor)
        require(stat.S_ISREG(opened.st_mode) and 0 <= opened.st_size <= limit,
                label + ' is missing, special or oversized')
        return descriptor, opened
    except BaseException:
        os.close(descriptor)
        raise


def _capture(path, limit, label, output=None, collect=False):
    descriptor, opened = _open_regular(path, limit, label)
    target = None
    try:
        if output is not None:
            output = Path(output)
            no_symlinks(output.parent)
            target = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        value = hashlib.sha256()
        raw = bytearray() if collect else None
        count = 0
        while chunk := os.read(descriptor, min(1024 * 1024, limit + 1 - count)):
            count += len(chunk)
            require(count <= limit, label + ' grew past its size limit')
            value.update(chunk)
            if collect:
                raw.extend(chunk)
            if target is not None:
                view = memoryview(chunk)
                while view:
                    written = os.write(target, view)
                    require(written > 0, 'Short delivery copy made no progress')
                    view = view[written:]
        finished = os.fstat(descriptor)
        require(count == opened.st_size and _same_metadata(opened, finished),
                label + ' changed while being read')
        if target is not None:
            os.fsync(target)
        return value.hexdigest(), bytes(raw) if collect else None, count
    finally:
        if target is not None:
            os.close(target)
        os.close(descriptor)


def _hash_regular(path, limit=MAX_FILE, label='Short delivery file'):
    return _capture(path, limit, label)[0]


def _copy_regular(source, target, limit=MAX_FILE, label='Short delivery file'):
    return _capture(source, limit, label, output=target)[0]


def _copy_to_stream(source, target, limit=MAX_FILE, label='Short delivery file'):
    descriptor, opened = _open_regular(source, limit, label)
    try:
        value = hashlib.sha256()
        count = 0
        while chunk := os.read(descriptor, min(1024 * 1024, limit + 1 - count)):
            count += len(chunk)
            require(count <= limit, label + ' grew past its size limit')
            value.update(chunk)
            target.write(chunk)
        require(count == opened.st_size and _same_metadata(opened, os.fstat(descriptor)),
                label + ' changed while being archived')
        return value.hexdigest()
    finally:
        os.close(descriptor)


def _write_durable(path, raw):
    path = Path(path)
    no_symlinks(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            require(written > 0, 'Short delivery write made no progress')
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
                         | getattr(os, 'O_NOFOLLOW', 0))
    try:
        require(stat.S_ISDIR(os.fstat(descriptor).st_mode), 'Short delivery directory is unsafe')
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _inventory(directory, expected_files, expected_directories=()):
    directory = Path(directory)
    no_symlinks(directory)
    require(directory.is_dir() and not directory.is_symlink(),
            'Short delivery directory is unavailable')
    entries = {entry.name: entry for entry in os.scandir(directory)}
    require(set(entries) == set(expected_files) | set(expected_directories),
            'Short delivery inventory changed')
    require(all(entries[name].is_file(follow_symlinks=False) for name in expected_files)
            and all(entries[name].is_dir(follow_symlinks=False) for name in expected_directories),
            'Short delivery inventory contains a symlink or special entry')


def _schema(value, required, optional=(), label='Short evidence'):
    require(isinstance(value, dict)
            and set(value) >= set(required)
            and set(value) <= set(required) | set(optional),
            label + ' schema is invalid')


def _false_flags(value, fields=FLAGS_SET, label='Short evidence'):
    require(all(value.get(field) is False for field in fields),
            label + ' contains an enabled acceptance claim')


def _number(value, label, *, minimum=None, maximum=None):
    require(type(value) in (int, float) and math.isfinite(value)
            and (minimum is None or value >= minimum)
            and (maximum is None or value <= maximum),
            label + ' must be a bounded finite number')


def _text(value, label, maximum=4096):
    require(isinstance(value, str) and 0 < len(value) <= maximum,
            label + ' must be bounded text')


def _sha(value, label):
    require(isinstance(value, str) and SHA.fullmatch(value), label + ' must be a SHA-256')


def _timestamp(value, label):
    _text(value, label, 64)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError(label + ' must be an ISO timestamp') from error
    require(parsed.tzinfo is not None, label + ' must include a timezone')


def _media(value, label):
    _schema(value, {'width', 'height', 'duration_seconds'}, label=label)
    require(type(value['width']) is int and type(value['height']) is int
            and 16 <= value['width'] <= 8192 and 16 <= value['height'] <= 8192,
            label + ' dimensions are invalid')
    _number(value['duration_seconds'], label + ' duration', minimum=0.001, maximum=1800)


def _intervals(value, duration, label):
    require(isinstance(value, list) and len(value) <= 10000,
            label + ' must be a bounded interval list')
    total = 0.0
    for interval in value:
        require(isinstance(interval, list) and len(interval) == 2,
                label + ' contains an invalid interval')
        start, end = interval
        _number(start, label + ' start', minimum=0, maximum=duration)
        _number(end, label + ' end', minimum=0, maximum=duration)
        require(start < end, label + ' interval must have positive duration')
        total += end - start
    return round(total, 6)


def _validate_caption_overlay(value):
    _schema(value, {'style', 'audio_mode', 'scope'}, {'picture_layout'}, 'Caption overlay')
    require(value['audio_mode'] == 'stream_copy_from_excerpt'
            and value['scope'] == 'Burned rebased sidecar into a private phone-size review derivative.'
            and value['style'] in (COMPACT_STYLE, SAFE_CAPTION_STYLE),
            'Caption overlay values are invalid')
    if 'picture_layout' in value:
        _schema(value['picture_layout'], {
            'mode', 'source_scale_percent', 'scaled_picture_size', 'canvas_size',
            'picture_offset', 'background_rgb', 'caption_bottom_clearance_target_pixels',
        }, label='Caption picture layout')
        require(value['style'] == SAFE_CAPTION_STYLE and value['picture_layout'] == {
            'mode': 'scaled_picture_safe_caption_area_v1',
            'source_scale_percent': 90,
            'scaled_picture_size': [648, 1152],
            'canvas_size': [720, 1280],
            'picture_offset': [36, 0],
            'background_rgb': '#f7f1e6',
            'caption_bottom_clearance_target_pixels': 125,
        }, 'Caption picture layout values are invalid')
    else:
        require(value['style'] == COMPACT_STYLE, 'Compact caption overlay style is invalid')


QUEUE_FIELDS = frozenset({
    'schema_version', 'status', 'technical_status', *FLAGS_SET, 'job_id',
    'source_provenance', 'selection', 'started_at', 'finished_at', 'scope',
    'candidate_sha256', 'caption_sha256', 'automated_review_sha256', 'preview_sha256',
    'decoded_picture_sha256', 'encoded_streams_sha256', 'media',
    'parent_candidate_sha256', 'parent_cycle_sha256', 'source_caption_sha256',
    'start_seconds', 'end_seconds', 'artifacts_sha256', 'consumer_tool_sha256',
    'exporter_tool_sha256',
})
SHORT_FIELDS = frozenset({
    'schema_version', 'status', 'technical_status', *FLAGS_SET, 'source_counter',
    'tool_sha256', 'parent_candidate_sha256', 'parent_cycle_sha256',
    'source_caption_sha256', 'start_seconds', 'end_seconds', 'boundary_cue_numbers',
    'selection_scope', 'caption_scope', 'scope', 'started_at', 'finished_at',
    'encoded_picture_duration_seconds', 'encoded_container_duration_seconds',
    'media', 'candidate_sha256', 'caption_sha256', 'automated_review_sha256',
    'preview_sha256', 'encoded_streams_sha256', 'decoded_picture_sha256',
    'preview_caption_mode',
})
PROVENANCE_FIELDS = frozenset({
    'job_id', 'job_digest', 'attempt', 'completed_at_unix', 'candidate_sha256',
    'pipeline_receipt_sha256', 'adapter_receipt_sha256', *FLAGS_SET, 'scope',
    'adapter', 'brief_sha256', 'production_brief_sha256', 'package_sha256',
    'review_archive_sha256',
})
PROVENANCE_OPTIONAL = frozenset({
    'minimum_duration_seconds', 'checkpoint_sha256', 'caption_sha256',
})
SELECTION_FIELDS = frozenset({
    'method', 'scene_ids', 'render_receipt_sha256', 'start_seconds', 'end_seconds',
    'editorial_selection_verified', 'scope',
})


def _validate_queue_receipt(value):
    _schema(value, QUEUE_FIELDS, {'caption_overlay'}, 'Queue Short receipt')
    _false_flags(value, label='Queue Short receipt')
    require(type(value['schema_version']) is int and value['schema_version'] == 1
            and value['status'] == 'AWAITING_REVIEW' and value['technical_status'] == 'PASS'
            and value['scope'] == QUEUE_SCOPE,
            'Queue Short receipt scalar values are invalid')
    require(isinstance(value['job_id'], str)
            and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value['job_id']),
            'Queue Short job ID is invalid')
    for field in ('started_at', 'finished_at'):
        _timestamp(value[field], 'Queue Short ' + field)
    for field in ('candidate_sha256', 'caption_sha256', 'automated_review_sha256',
                  'preview_sha256', 'decoded_picture_sha256', 'parent_candidate_sha256',
                  'parent_cycle_sha256', 'source_caption_sha256', 'consumer_tool_sha256',
                  'exporter_tool_sha256'):
        _sha(value[field], 'Queue Short ' + field)
    _number(value['start_seconds'], 'Queue Short start', minimum=0, maximum=1800)
    _number(value['end_seconds'], 'Queue Short end', minimum=0.001, maximum=1800)
    require(value['start_seconds'] < value['end_seconds']
            and value['end_seconds'] - value['start_seconds'] <= 60,
            'Queue Short interval is invalid')
    _schema(value['source_provenance'], PROVENANCE_FIELDS, PROVENANCE_OPTIONAL,
            'Short source provenance')
    _false_flags(value['source_provenance'], label='Short source provenance')
    provenance = value['source_provenance']
    require(provenance['job_id'] == value['job_id']
            and isinstance(provenance['job_digest'], str) and SHA.fullmatch(provenance['job_digest'])
            and type(provenance['attempt']) is int and provenance['attempt'] >= 1
            and provenance['adapter'] in CYCLE_QUEUE_ADAPTERS
            and provenance['scope'] == PROVENANCE_SCOPE,
            'Short source provenance scalar values are invalid')
    _number(provenance['completed_at_unix'], 'Short source completion time', minimum=0.001)
    for field in ('candidate_sha256', 'pipeline_receipt_sha256', 'adapter_receipt_sha256',
                  'brief_sha256', 'production_brief_sha256', 'package_sha256',
                  'review_archive_sha256', 'checkpoint_sha256', 'caption_sha256'):
        if field in provenance:
            _sha(provenance[field], 'Short source ' + field)
    if 'minimum_duration_seconds' in provenance:
        _number(provenance['minimum_duration_seconds'], 'Short source minimum duration',
                minimum=0.001, maximum=1800)
    _schema(value['selection'], SELECTION_FIELDS, label='Short selection')
    require(value['selection']['editorial_selection_verified'] is False,
            'Short selection contains an enabled acceptance claim')
    require(isinstance(value['selection']['scene_ids'], list)
            and len(value['selection']['scene_ids']) <= 100
            and all(isinstance(item, str) and 0 < len(item) <= 128
                    for item in value['selection']['scene_ids']),
            'Short selection scene IDs are invalid')
    selection = value['selection']
    require(selection['method'] in ('authored_contiguous_scene_span_v1',
                                    'explicit_time_bounds_v1'),
            'Short selection method is invalid')
    _number(selection['start_seconds'], 'Short selection start', minimum=0, maximum=1800)
    _number(selection['end_seconds'], 'Short selection end', minimum=0.001, maximum=1800)
    require(selection['start_seconds'] == value['start_seconds']
            and selection['end_seconds'] == value['end_seconds'],
            'Short selection interval does not match the receipt')
    if selection['method'] == 'authored_contiguous_scene_span_v1':
        require(selection['scene_ids'] and isinstance(selection['render_receipt_sha256'], str)
                and SHA.fullmatch(selection['render_receipt_sha256'])
                and selection['scope'] == AUTHORED_SELECTION_SCOPE,
                'Authored Short selection values are invalid')
    else:
        require(selection['scene_ids'] == [] and selection['render_receipt_sha256'] is None
                and selection['scope'] == EXPLICIT_SELECTION_SCOPE,
                'Explicit Short selection values are invalid')
    _schema(value['encoded_streams_sha256'], {'video', 'audio'}, label='Short stream identities')
    for field in ('video', 'audio'):
        _sha(value['encoded_streams_sha256'][field], 'Short stream ' + field)
    _media(value['media'], 'Short media')
    _schema(value['artifacts_sha256'], set(FILES) - {'queue-short.json'}, label='Short artifacts')
    for name, identity in value['artifacts_sha256'].items():
        _sha(identity, 'Short artifact ' + name)
    if 'caption_overlay' in value:
        _validate_caption_overlay(value['caption_overlay'])


def _project_queue_receipt(value, queue_receipt_sha256):
    _sha(queue_receipt_sha256, 'Exact queue receipt')
    require(isinstance(value, dict) and isinstance(value.get('source_provenance'), dict),
            'Queue Short receipt cannot be projected')
    # JSON round-trip makes a detached data projection and rejects non-JSON values.
    sanitized = json.loads(json.dumps(value, allow_nan=False))
    provenance = sanitized['source_provenance']
    proofs = {}
    for field in PROOF_FIELDS:
        if field in provenance:
            proof = provenance.pop(field)
            require(isinstance(proof, dict), 'Verified queue proof must be an object')
            encoded = canonical(proof).encode()
            require(0 < len(encoded) <= MAX_JSON, 'Verified queue proof is oversized')
            proofs[field] = hashlib.sha256(encoded).hexdigest()
    require(len(proofs) <= 1, 'Queue provenance contains conflicting verified proofs')
    _validate_queue_receipt(sanitized)
    if not proofs:
        return sanitized, None
    binding = {
        'schema_version': 1, 'status': 'QUEUE_BINDING_VERIFIED', **FLAGS,
        'queue_receipt_sha256': queue_receipt_sha256,
        'verified_receipt': sanitized,
        'verified_proofs_sha256': proofs,
        'scope': QUEUE_BINDING_SCOPE,
    }
    return sanitized, binding


def _validate_queue_binding(value):
    _schema(value, {
        'schema_version', 'status', *FLAGS_SET, 'queue_receipt_sha256',
        'verified_receipt', 'verified_proofs_sha256', 'scope',
    }, label='Queue binding projection')
    _false_flags(value, label='Queue binding projection')
    require(type(value['schema_version']) is int and value['schema_version'] == 1
            and value['status'] == 'QUEUE_BINDING_VERIFIED'
            and value['scope'] == QUEUE_BINDING_SCOPE,
            'Queue binding projection values are invalid')
    _sha(value['queue_receipt_sha256'], 'Projected queue receipt')
    _validate_queue_receipt(value['verified_receipt'])
    proofs = value['verified_proofs_sha256']
    require(isinstance(proofs, dict) and len(proofs) == 1
            and set(proofs) <= set(PROOF_FIELDS),
            'Queue binding proof inventory is invalid')
    for field, identity in proofs.items():
        _sha(identity, 'Projected queue proof ' + field)
    return value['verified_receipt']


def _validate_short_receipt(value):
    _schema(value, SHORT_FIELDS, {'caption_overlay'}, 'Short producer receipt')
    _false_flags(value, label='Short producer receipt')
    require(type(value['schema_version']) is int and value['schema_version'] == 1
            and value['status'] == 'AWAITING_REVIEW' and value['technical_status'] == 'PASS'
            and value['scope'] == SHORT_SCOPE and value['caption_scope'] == CAPTION_SCOPE
            and value['selection_scope'] == SHORT_SELECTION_SCOPE
            and value['preview_caption_mode'] in ('burned', 'sidecar'),
            'Short producer scalar values are invalid')
    for field in ('started_at', 'finished_at'):
        _timestamp(value[field], 'Short producer ' + field)
    for field in ('tool_sha256', 'parent_candidate_sha256', 'parent_cycle_sha256',
                  'source_caption_sha256', 'candidate_sha256', 'caption_sha256',
                  'automated_review_sha256', 'preview_sha256', 'decoded_picture_sha256'):
        _sha(value[field], 'Short producer ' + field)
    for field in ('start_seconds', 'end_seconds', 'encoded_picture_duration_seconds',
                  'encoded_container_duration_seconds'):
        _number(value[field], 'Short producer ' + field, minimum=0, maximum=1800)
    require(value['start_seconds'] < value['end_seconds']
            and value['end_seconds'] - value['start_seconds'] <= 60
            and value['encoded_picture_duration_seconds'] > 0
            and value['encoded_container_duration_seconds'] > 0
            and value['encoded_container_duration_seconds'] == value['media']['duration_seconds']
            and abs(value['encoded_picture_duration_seconds']
                    - (value['end_seconds'] - value['start_seconds'])) <= .1
            and abs(value['encoded_container_duration_seconds']
                    - (value['end_seconds'] - value['start_seconds'])) <= .1,
            'Short producer timing values are invalid')
    _schema(value['encoded_streams_sha256'], {'video', 'audio'}, label='Short producer streams')
    for field in ('video', 'audio'):
        _sha(value['encoded_streams_sha256'][field], 'Short producer stream ' + field)
    _media(value['media'], 'Short producer media')
    require(isinstance(value['boundary_cue_numbers'], list)
            and len(value['boundary_cue_numbers']) <= 10000
            and all(type(item) is int and item >= 1 for item in value['boundary_cue_numbers']),
            'Short boundary cue numbers are invalid')
    require(len(value['boundary_cue_numbers']) == len(set(value['boundary_cue_numbers'])),
            'Short boundary cue numbers must be unique')
    counter = value['source_counter']
    _schema(counter, {'action'}, {'rectangle_xywh', 'fill_rgb', 'scope'}, 'Short source counter')
    require(counter['action'] in ('preserve', 'hide_source_scene_counter'),
            'Short source counter action is invalid')
    require((counter['action'] == 'preserve' and set(counter) == {'action'})
            or (counter['action'] == 'hide_source_scene_counter'
                and set(counter) == {'action', 'rectangle_xywh', 'fill_rgb', 'scope'}),
            'Short source counter schema does not match its action')
    if counter['action'] == 'hide_source_scene_counter':
        require(counter['rectangle_xywh'] == [570, 40, 110, 45]
                and counter['fill_rgb'] == '#f7f1e6'
                and counter['scope'] == ('Known renderer scene-counter region only; no reframing '
                                         'or automatic media cleanup.'),
                'Short source counter values are invalid')
    if 'caption_overlay' in value:
        _validate_caption_overlay(value['caption_overlay'])
    require((value['preview_caption_mode'] == 'burned') == ('caption_overlay' in value),
            'Short preview caption mode does not match its overlay')


def _validate_automated_review(value):
    top = {
        'schema_version', 'created_at', 'candidate_sha256', 'caption_sha256',
        'watcher', 'listener', 'analysis', 'competitor_comparison', 'reviewer',
        'full_audiovisual_review_verified', 'competitor_audiovisual_comparison_verified',
        'publication_enabled', 'paid_generation_enabled', 'production_approved',
    }
    _schema(value, top, {'media'}, 'Automated review')
    _false_flags(value, {
        'full_audiovisual_review_verified', 'competitor_audiovisual_comparison_verified',
        'publication_enabled', 'paid_generation_enabled', 'production_approved',
    }, 'Automated review')
    require(type(value['schema_version']) is int and value['schema_version'] == 1,
            'Automated review schema version is invalid')
    _timestamp(value['created_at'], 'Automated review created_at')
    _sha(value['candidate_sha256'], 'Automated review candidate')
    _sha(value['caption_sha256'], 'Automated review captions')
    if 'media' in value:
        _media(value['media'], 'Review media')
    duration = value.get('media', {}).get('duration_seconds')
    watcher = value['watcher']
    _schema(watcher, {'status'}, {
        'black_intervals', 'frozen_intervals', 'black_seconds', 'frozen_seconds',
    }, 'Automated watcher')
    require((watcher['status'] == 'BLOCKED' and set(watcher) == {'status'})
            or (watcher['status'] == 'SIGNALS_MEASURED' and set(watcher) == {
                'status', 'black_intervals', 'frozen_intervals', 'black_seconds', 'frozen_seconds'}),
            'Automated watcher status schema is invalid')
    if watcher['status'] == 'SIGNALS_MEASURED':
        require(duration is not None, 'Measured watcher requires bound media')
        for key in ('black', 'frozen'):
            measured = _intervals(watcher[key + '_intervals'], duration,
                                  'Watcher ' + key + ' intervals')
            _number(watcher[key + '_seconds'], 'Watcher ' + key + ' seconds',
                    minimum=0, maximum=duration)
            require(abs(watcher[key + '_seconds'] - measured) <= 1e-6,
                    'Watcher ' + key + ' seconds do not match its intervals')
    listener = value['listener']
    _schema(listener, {'status'}, {
        'silence_intervals', 'silence_seconds', 'peak_dbfs', 'mean_dbfs',
    }, 'Automated listener')
    require((listener['status'] == 'BLOCKED' and set(listener) == {'status'})
            or (listener['status'] == 'SIGNALS_MEASURED' and set(listener) == {
                'status', 'silence_intervals', 'silence_seconds', 'peak_dbfs', 'mean_dbfs'}),
            'Automated listener status schema is invalid')
    if listener['status'] == 'SIGNALS_MEASURED':
        require(duration is not None, 'Measured listener requires bound media')
        measured = _intervals(listener['silence_intervals'], duration,
                              'Listener silence intervals')
        _number(listener['silence_seconds'], 'Listener silence seconds',
                minimum=0, maximum=duration)
        require(abs(listener['silence_seconds'] - measured) <= 1e-6,
                'Listener silence seconds do not match its intervals')
        _number(listener['peak_dbfs'], 'Listener peak level')
        _number(listener['mean_dbfs'], 'Listener mean level')
    _schema(value['analysis'], {'status', 'intervals_to_review'}, {'scan_failure_code'},
            'Automated analysis')
    analysis = value['analysis']
    allowed_intervals = {'black_intervals', 'frozen_intervals', 'silence_intervals'}
    require(analysis['status'] in ('DIAGNOSTICS_AVAILABLE', 'BLOCKED')
            and isinstance(analysis['intervals_to_review'], list)
            and len(analysis['intervals_to_review']) <= len(allowed_intervals)
            and all(isinstance(item, str) and item in allowed_intervals
                    for item in analysis['intervals_to_review']),
            'Automated analysis values are invalid')
    require(len(analysis['intervals_to_review']) == len(set(analysis['intervals_to_review'])),
            'Automated analysis intervals must be unique')
    failure_codes = {
        'CANDIDATE_SCAN_TIMED_OUT', 'CANDIDATE_SCAN_INPUT_OR_TOOL_MISSING',
        'CANDIDATE_SCAN_IO_FAILED', 'CANDIDATE_SCAN_INPUT_OR_SIGNALS_INVALID',
        'CANDIDATE_SCAN_PROCESS_FAILED',
    }
    require(('scan_failure_code' not in analysis
             and analysis['status'] == 'DIAGNOSTICS_AVAILABLE')
            or (analysis.get('scan_failure_code') in failure_codes
                and analysis['status'] == 'BLOCKED'),
            'Automated analysis failure code is invalid')
    measured = watcher['status'] == listener['status'] == 'SIGNALS_MEASURED'
    expected_attention = ([key for key, stage in (
        ('black_intervals', watcher), ('frozen_intervals', watcher),
        ('silence_intervals', listener)) if stage.get(key)] if measured else [])
    require((measured and analysis['status'] == 'DIAGNOSTICS_AVAILABLE'
             and 'scan_failure_code' not in analysis)
            or (not measured and watcher['status'] == listener['status'] == 'BLOCKED'
                and analysis['status'] == 'BLOCKED'
                and analysis.get('scan_failure_code') in failure_codes),
            'Automated analysis status differs from watcher/listener stages')
    require(analysis['intervals_to_review'] == expected_attention,
            'Automated analysis attention intervals differ from measured signals')
    _schema(value['reviewer'], {'status', 'picture_checks', 'audio_checks', 'comparison_checks'},
            label='Automated reviewer')
    require(value['reviewer'] == {
        'status': 'FULL_REVIEW_REQUIRED',
        'picture_checks': ['staging', 'animation', 'readability', 'pacing', 'payoff'],
        'audio_checks': ['naturalness', 'pronunciation', 'character voices',
                         'music and effects', 'mix'],
        'comparison_checks': ['hook', 'storytelling', 'visual pacing',
                              'voice and mix', 'originality'],
    }, 'Automated reviewer values are invalid')
    comparison = value['competitor_comparison']
    degraded_comparison = {'status': 'BLOCKED', 'reason': 'Candidate signal scan unavailable'}
    if comparison == degraded_comparison:
        require(watcher['status'] == listener['status'] == 'BLOCKED'
                and analysis['status'] == 'BLOCKED'
                and analysis.get('scan_failure_code') in failure_codes,
                'Degraded competitor comparison lacks a scan failure')
        return
    _schema(comparison, {
        'status', 'candidate_sha256', 'comparisons', 'reason', 'publication_enabled',
        'paid_generation_enabled', 'full_av_review',
        'reference_selection_independently_verified', 'scope',
    }, {'reference_format', 'manifest_sha256'}, 'Technical competitor comparison')
    _false_flags(comparison, {
        'publication_enabled', 'paid_generation_enabled', 'full_av_review',
        'reference_selection_independently_verified',
    }, 'Technical competitor comparison')
    require(isinstance(comparison['status'], str)
            and (comparison['reason'] is None or isinstance(comparison['reason'], str))
            and comparison['candidate_sha256'] == value['candidate_sha256']
            and comparison['scope'] == ('Technical signal differences only. Creative perception '
                                        'and competitor rank are unverified.')
            and isinstance(comparison['comparisons'], list),
            'Technical competitor comparison binding is invalid')
    blocked_reasons = {
        'BENCHMARK_MANIFEST_UNCONFIGURED', 'BENCHMARK_FORMAT_UNCONFIGURED',
        'BENCHMARK_COMPARISON_TIMED_OUT', 'BENCHMARK_INPUT_OR_SCAN_INVALID',
    }
    if comparison['status'] == 'TECHNICAL_COMPARISON_COMPLETE':
        require(comparison['reason'] is None
                and set(comparison) == {
                    'status', 'candidate_sha256', 'comparisons', 'reason',
                    'publication_enabled', 'paid_generation_enabled', 'full_av_review',
                    'reference_selection_independently_verified', 'scope',
                    'reference_format', 'manifest_sha256'}
                and comparison['reference_format'] in ('portrait', 'landscape', 'square')
                and isinstance(comparison['manifest_sha256'], str)
                and SHA.fullmatch(comparison['manifest_sha256'])
                and len(comparison['comparisons']) == 2,
                'Completed technical competitor comparison is invalid')
    else:
        require(comparison['status'] == 'BLOCKED'
                and comparison['reason'] in blocked_reasons
                and comparison['comparisons'] == [],
                'Blocked technical competitor comparison is invalid')
        if comparison['reason'] == 'BENCHMARK_FORMAT_UNCONFIGURED':
            require(set(comparison) == {
                'status', 'candidate_sha256', 'comparisons', 'reason',
                'publication_enabled', 'paid_generation_enabled', 'full_av_review',
                'reference_selection_independently_verified', 'scope', 'reference_format'}
                and comparison['reference_format'] in ('portrait', 'landscape', 'square'),
                'Format-blocked technical competitor comparison is invalid')
        else:
            require('reference_format' not in comparison and 'manifest_sha256' not in comparison,
                    'Blocked technical competitor comparison has unsupported optionals')
    comparison_fields = {
        'url', 'sha256', 'selection_rationale', 'selection_evidence_url', 'selected_at',
        'reference_signals', 'candidate_minus_reference',
    }
    signal_fields = {
        'duration_seconds', 'orientation', 'black_fraction', 'frozen_fraction',
        'silence_fraction', 'peak_dbfs', 'mean_dbfs',
    }
    candidate_orientation = ('landscape' if value['media']['width'] > value['media']['height']
                             else 'portrait' if value['media']['width'] < value['media']['height']
                             else 'square')
    if comparison['status'] == 'TECHNICAL_COMPARISON_COMPLETE':
        require(comparison['reference_format'] == candidate_orientation,
                'Technical comparison format differs from the candidate')
    candidate_signals = {
        'duration_seconds': value['media']['duration_seconds'],
        'black_fraction': value['watcher']['black_seconds'] / value['media']['duration_seconds'],
        'frozen_fraction': value['watcher']['frozen_seconds'] / value['media']['duration_seconds'],
        'silence_fraction': value['listener']['silence_seconds'] / value['media']['duration_seconds'],
        'peak_dbfs': value['listener']['peak_dbfs'],
        'mean_dbfs': value['listener']['mean_dbfs'],
    } if value['watcher']['status'] == value['listener']['status'] == 'SIGNALS_MEASURED' else None
    reference_hashes = []
    for row in comparison['comparisons']:
        _schema(row, comparison_fields, label='Technical comparison row')
        _schema(row['reference_signals'], signal_fields, label='Reference signals')
        _schema(row['candidate_minus_reference'], signal_fields - {'orientation'},
                label='Technical comparison deltas')
        require(all(isinstance(row[key], str) for key in (
            'url', 'sha256', 'selection_rationale', 'selection_evidence_url', 'selected_at')),
            'Technical comparison provenance values are invalid')
        require(SHA.fullmatch(row['sha256']), 'Technical comparison media SHA is invalid')
        reference_hashes.append(row['sha256'])
        for field in ('url', 'selection_evidence_url'):
            parsed = urlsplit(row[field])
            require(parsed.scheme == 'https' and parsed.hostname
                    and parsed.username is None and parsed.password is None
                    and parsed.port in (None, 443) and not parsed.fragment,
                    'Technical comparison URL is invalid')
        _timestamp(row['selected_at'], 'Technical comparison selected_at')
        _text(row['selection_rationale'], 'Technical comparison rationale', 2000)
        require(row['reference_signals']['orientation'] == comparison.get('reference_format'),
                'Technical comparison orientation is invalid')
        for key, number in row['reference_signals'].items():
            if key != 'orientation':
                _number(number, 'Reference signal ' + key)
        _number(row['reference_signals']['duration_seconds'], 'Reference duration', minimum=0.001, maximum=3600)
        for key in ('black_fraction', 'frozen_fraction', 'silence_fraction'):
            _number(row['reference_signals'][key], 'Reference ' + key, minimum=0, maximum=1)
        for key, number in row['candidate_minus_reference'].items():
            _number(number, 'Technical comparison delta ' + key)
            require(candidate_signals is not None and math.isclose(
                number, candidate_signals[key] - row['reference_signals'][key],
                rel_tol=1e-9, abs_tol=1e-9),
                'Technical comparison delta does not match the bound signals: ' + key)
    require(len(reference_hashes) == len(set(reference_hashes))
            and all(identity != value['candidate_sha256'] for identity in reference_hashes),
            'Technical comparison references are not distinct')
def _validate_comparison_manifest(comparison, review_created_at):
    """Re-open the selected local benchmark manifest and exact reference media."""
    configured = os.environ.get('CYZOR_REVIEW_BENCHMARKS')
    require(isinstance(configured, str) and configured,
            'Completed technical comparison requires its benchmark manifest')
    manifest = Path(configured)
    require(manifest.is_absolute() and '..' not in manifest.parts,
            'Completed technical comparison manifest path is invalid')
    manifest_sha256, raw, _ = _capture(
        manifest, benchmarks.MANIFEST_LIMIT, 'Technical comparison manifest',
        collect=True)
    require(manifest_sha256 == comparison['manifest_sha256'],
            'Technical comparison manifest identity changed')

    def unique(items):
        value = {}
        for key, nested in items:
            require(key not in value, 'Duplicate technical comparison manifest key')
            value[key] = nested
        return value

    plan = json.loads(
        raw, object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError('Nonfinite technical comparison manifest value')))
    require(isinstance(plan, dict) and set(plan) in (
        {'schema_version', 'references'}, {'schema_version', 'reference_sets'})
        and type(plan['schema_version']) is int and plan['schema_version'] == 1,
        'Technical comparison manifest schema is invalid')
    if 'references' in plan:
        rows = plan['references']
    else:
        sets = plan['reference_sets']
        require(isinstance(sets, dict)
                and comparison['reference_format'] in sets,
                'Technical comparison format is absent from its manifest')
        rows = sets[comparison['reference_format']]
    require(isinstance(rows, list) and len(rows) == 2,
            'Technical comparison manifest must retain exactly two references')

    deadline = time.monotonic() + 120
    projected = []
    reference_ids = []
    evidence_ids = []
    created = datetime.fromisoformat(review_created_at)
    for row in rows:
        reference_id, path = benchmarks._reference(row, manifest.parent)
        reference_ids.append(reference_id)
        evidence = benchmarks._url(row['selection_evidence_url'])
        evidence_ids.append((
            evidence.hostname.removeprefix('www.'),
            evidence.path.rstrip('/') or '/',
            tuple(sorted(parse_qsl(evidence.query, keep_blank_values=True)))))
        require(datetime.fromisoformat(row['selected_at']) <= created,
                'Technical comparison selection is later than its review')
        before = benchmarks._read(
            path, benchmarks.MEDIA_LIMIT, media=True, deadline=deadline)
        require(before[0] == row['sha256'],
                'Technical comparison reference bytes changed')
        signals = benchmarks._signals(scan_media(path, deadline=deadline))
        require(benchmarks._read(
            path, benchmarks.MEDIA_LIMIT, media=True, deadline=deadline) == before,
            'Technical comparison reference changed during its rescan')
        projected.append({
            key: row[key] for key in benchmarks.REFERENCE_FIELDS - {'path', 'authorized'}
        } | {'reference_signals': signals})
    require(len(set(reference_ids)) == 2 and len(set(evidence_ids)) == 2,
            'Technical comparison reference provenance is not distinct')
    require(all(observed['reference_signals'] == expected['reference_signals']
                and all(observed[key] == expected[key] for key in (
                    'url', 'sha256', 'selection_rationale',
                    'selection_evidence_url', 'selected_at'))
                for observed, expected in zip(comparison['comparisons'], projected)),
            'Technical comparison rows differ from the retained manifest and media')
    require(_capture(
        manifest, benchmarks.MANIFEST_LIMIT, 'Technical comparison manifest',
        collect=True)[:2] == (manifest_sha256, raw),
        'Technical comparison manifest changed during its rescan')


def _burned_caption_cues(path, duration):
    _, raw, _ = _capture(path, MAX_JSON, 'Burned-caption sidecar', collect=True)
    text = raw.decode('utf-8')
    require(text.startswith('WEBVTT\n'), 'Burned-caption replay requires plain WebVTT')
    cues = []
    for block in re.split(r'\n\s*\n', text.strip())[1:]:
        lines = block.splitlines()
        if lines and re.fullmatch(r'\d+', lines[0]):
            lines = lines[1:]
        require(len(lines) >= 2 and len(lines[0].split(' --> ')) == 2,
                'Burned-caption cue is invalid')
        left, right = lines[0].split(' --> ')
        match_left = re.fullmatch(
            r'(\d{2,}):([0-5]\d):([0-5]\d)\.(\d{3})', left)
        match_right = re.fullmatch(
            r'(\d{2,}):([0-5]\d):([0-5]\d)\.(\d{3})', right)
        require(match_left is not None and match_right is not None,
                'Burned-caption cue timestamp is invalid')
        def seconds(match):
            hours, minutes, value, millis = map(int, match.groups())
            return ((hours * 60 + minutes) * 60 + value) + millis / 1000
        start, end = seconds(match_left), seconds(match_right)
        cue_text = ' '.join(lines[1:]).strip()
        require(0 <= start < end <= duration and end - start >= .1
                and len(re.findall(r'[A-Za-z0-9]', cue_text)) >= 2,
                'Burned-caption cue is too sparse for pixel verification')
        cues.append((start, end))
    require(cues, 'Burned-caption replay requires at least one cue')
    return cues


def _verify_burned_replay(queue_root, job_id, source, receipt):
    """Prove a burned-caption claim by reproducing the exact private derivative."""
    short = _read_json(Path(source) / 'short.json')
    if short['preview_caption_mode'] != 'burned':
        return
    cycle, provenance = _queue_source(queue_root, job_id)
    require(provenance == receipt['source_provenance'],
            'Burned-caption replay source provenance changed')
    try:
        with tempfile.TemporaryDirectory(prefix='short-burned-replay-') as directory:
            replay = Path(directory) / 'short'
            result = make_short(
                cycle, replay, start=receipt['start_seconds'],
                end=receipt['end_seconds'], timeout=180,
                hide_source_counter=short['source_counter']['action']
                == 'hide_source_scene_counter',
                compact_captions=True,
                caption_safe_area='picture_layout' in short['caption_overlay'])
            deadline = time.monotonic() + 120
            stats = Path(directory) / 'active-caption-ssim.log'
            run([
                'ffmpeg', '-hide_banner', '-nostdin', '-nostats', '-loglevel', 'error',
                '-xerror', '-protocol_whitelist', 'file,pipe', '-threads', '2',
                '-i', str(Path(source) / 'video.mp4'),
                '-i', str(replay / 'video.mp4'), '-filter_complex', (
                    '[0:v:0]crop=iw:320:0:ih-320[left];'
                    '[1:v:0]crop=iw:320:0:ih-320[right];'
                    f'[left][right]ssim=stats_file={stats}'),
                '-an', '-f', 'null', '-',
            ], deadline=deadline, stderr=True)
            _, stats_raw, _ = _capture(
                stats, MAX_JSON, 'Burned-caption active-frame comparison',
                collect=True)
            scores = [float(value) for value in re.findall(
                rb'\bAll:([0-9]+(?:\.[0-9]+)?)\b', stats_raw)]
            cues = _burned_caption_cues(
                Path(source) / 'captions.vtt', receipt['media']['duration_seconds'])
            require(scores, 'Burned-caption active-frame comparison is empty')
            frames_per_second = len(scores) / receipt['media']['duration_seconds']
            active_scores = [
                score for index, score in enumerate(scores)
                if any(start <= index / frames_per_second < end
                       for start, end in cues)
            ]
            require(active_scores and min(active_scores) >= .999,
                    'Burned-caption active frames differ from the exporter replay')
            require(result.get('status') == 'AWAITING_REVIEW'
                    and result.get('technical_status') == 'PASS'
                    and result.get('caption_overlay') == short['caption_overlay']
                    and result.get('caption_sha256') == receipt['caption_sha256']
                    and result.get('media') == receipt['media']
                    and result.get('encoded_streams_sha256', {}).get('audio')
                        == receipt['encoded_streams_sha256']['audio']
                    and _hash_regular(replay / 'captions.vtt', MAX_JSON,
                                      'Replayed Short captions')
                        == receipt['caption_sha256'],
                    'Burned-caption candidate does not match a deterministic exporter replay')
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        raise ValueError(
            'Burned-caption candidate does not match a deterministic exporter replay'
        ) from error


def _read_json(path):
    _, raw, _ = _capture(path, MAX_JSON, 'Short delivery metadata', collect=True)
    def unique(items):
        value = {}
        for key, nested in items:
            require(key not in value, 'Duplicate Short delivery metadata key')
            value[key] = nested
        return value
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda value: (_ for _ in ()).throw(
        ValueError('Nonfinite Short delivery metadata')))
    require(isinstance(value, dict), 'Short delivery metadata must be an object')
    return value


def _identities(root, names):
    result = {}
    total = 0
    for name in names:
        path = root / name
        identity, _, size = _capture(path, MAX_FILE, 'Short delivery file: ' + name)
        total += size
        require(size <= MAX_FILE and total <= MAX_TOTAL, 'Short delivery size limit exceeded')
        result[name] = identity
    return result


def _base(receipt, files, queue_receipt_sha256):
    _validate_queue_receipt(receipt)
    streams = receipt.get('encoded_streams_sha256')
    require(isinstance(streams, dict) and set(streams) == {'video', 'audio'}
            and all(isinstance(value, str) and SHA.fullmatch(value) for value in streams.values()),
            'Short stream identities are invalid')
    values = {
        'schema_version': 1,
        'status': 'AWAITING_REVIEW',
        'technical_status': 'PASS',
        **FLAGS,
        'candidate_sha256': receipt.get('candidate_sha256'),
        'caption_sha256': receipt.get('caption_sha256'),
        'encoded_streams_sha256': streams,
        'decoded_picture_sha256': receipt.get('decoded_picture_sha256'),
        'queue_receipt_sha256': queue_receipt_sha256,
        'parent_provenance': receipt.get('source_provenance'),
        'selection': receipt.get('selection'),
        'entrypoint': 'review/index.html',
        'entrypoint_sha256': files['index.html'],
        'scope': SCOPE,
    }
    require(all(isinstance(values[key], str) and SHA.fullmatch(values[key]) for key in (
        'candidate_sha256', 'caption_sha256', 'decoded_picture_sha256',
        'queue_receipt_sha256', 'entrypoint_sha256')),
        'Short delivery identities are invalid')
    require(files['video.mp4'] == values['candidate_sha256']
            and files['captions.vtt'] == values['caption_sha256'],
            'Short delivery files do not match the verified receipt')
    require(isinstance(values['parent_provenance'], dict)
            and all(values['parent_provenance'].get(key) is False for key in FLAGS_SET)
            and isinstance(values['selection'], dict)
            and values['selection'].get('editorial_selection_verified') is False,
            'Short parent provenance or selection is not an unapproved review')
    return values


def _verify_semantics(root, receipt):
    """Replay diagnostics, preview and media identities from exact local bytes."""
    root = Path(root)
    short = _read_json(root / 'short.json')
    diagnostics = _read_json(root / 'automated-review.json')
    _validate_queue_receipt(receipt)
    _validate_short_receipt(short)
    _validate_automated_review(diagnostics)
    shared = {
        'candidate_sha256', 'caption_sha256', 'automated_review_sha256', 'preview_sha256',
        'decoded_picture_sha256', 'encoded_streams_sha256', 'media',
        'parent_candidate_sha256', 'parent_cycle_sha256', 'source_caption_sha256',
        'start_seconds', 'end_seconds',
    }
    require(all(short.get(field) == receipt.get(field) for field in shared)
            and short.get('caption_overlay') == receipt.get('caption_overlay')
            and receipt['source_provenance']['candidate_sha256'] == receipt['parent_candidate_sha256']
            and receipt['source_provenance']['pipeline_receipt_sha256'] == receipt['parent_cycle_sha256']
            and receipt['source_provenance'].get('caption_sha256', receipt['source_caption_sha256'])
                == receipt['source_caption_sha256'],
            'Short source receipts do not share exact artifact identities')
    require(diagnostics.get('candidate_sha256') == receipt['candidate_sha256']
            and diagnostics.get('caption_sha256') == receipt['caption_sha256']
            and ((diagnostics['watcher']['status'] == 'SIGNALS_MEASURED'
                  and diagnostics.get('media') == receipt['media'])
                 or (diagnostics['watcher']['status'] == 'BLOCKED'
                     and 'media' not in diagnostics)),
            'Automated review does not bind the Short media receipt')
    verify_automated_review(
        root / 'automated-review.json', receipt['automated_review_sha256'],
        receipt['candidate_sha256'], receipt['caption_sha256'])
    mode = short.get('preview_caption_mode')
    require(mode in ('burned', 'sidecar'), 'Short preview caption mode is invalid')
    expected_preview = _preview_html(short, burned_captions=mode == 'burned').encode()
    _, actual_preview, _ = _capture(
        root / 'index.html', MAX_JSON, 'Short preview', collect=True)
    require(actual_preview == expected_preview
            and hashlib.sha256(actual_preview).hexdigest() == receipt['preview_sha256'],
            'Short preview does not reconstruct from the verified receipts')

    deadline = time.monotonic() + 120
    media = _probe(root / 'video.mp4', deadline)
    with tempfile.TemporaryDirectory(prefix='.short-delivery-identities-') as directory:
        streams, picture = media_identities(
            root / 'video.mp4', Path(directory), deadline)
    require(media == receipt.get('media')
            and streams == receipt.get('encoded_streams_sha256')
            and picture == receipt.get('decoded_picture_sha256'),
            'Short media identities do not replay from the copied candidate')
    return short, diagnostics


def _identity(report):
    return hashlib.sha256(canonical({key: value for key, value in report.items()
                                    if key != 'delivery_identity_sha256'}).encode()).hexdigest()


def export_short_delivery(queue_root, job_id, short_dir, output_dir):
    """Copy one exact verified derivative into a fresh immutable review archive."""
    queue = _path(queue_root)
    source = _path(short_dir)
    output = _path(output_dir)
    require(source.is_dir() and not source.is_symlink(), 'Short source directory is unavailable')
    require(not output.exists() and not output.is_relative_to(queue)
            and not output.is_relative_to(source),
            'Fresh Short delivery directory outside queue and source required')
    require(output.parent.is_dir() and not output.parent.is_symlink(),
            'Existing Short delivery parent directory required for durable publication')
    retained_receipt = verify_consumed_short(queue, job_id, source)
    _inventory(source, FILES)
    source_files = _identities(source, FILES)
    receipt, binding = _project_queue_receipt(
        retained_receipt, source_files['queue-short.json'])
    _, diagnostics = _verify_semantics(source, receipt)
    if diagnostics['competitor_comparison'].get('status') == 'TECHNICAL_COMPARISON_COMPLETE':
        _validate_comparison_manifest(
            diagnostics['competitor_comparison'], diagnostics['created_at'])
    _verify_burned_replay(queue, job_id, source, retained_receipt)
    delivery_files = list(DELIVERY_BASE_FILES)
    if binding is None:
        delivery_files.append('queue-short.json')

    temporary = Path(tempfile.mkdtemp(prefix='.short-delivery-', dir=output.parent))
    try:
        review = temporary / 'review'
        review.mkdir(mode=0o700)
        for name in delivery_files:
            require(_copy_regular(source / name, review / name,
                                  label='Short source file: ' + name) == source_files[name],
                    'Short source changed while being copied: ' + name)
        copied = _identities(review, delivery_files)
        require(copied == {name: source_files[name] for name in delivery_files},
                'Short source changed while being copied')
        if binding is not None:
            _write_durable(review / 'queue-binding.json', (json.dumps(
                binding, indent=2, sort_keys=True, allow_nan=False) + '\n').encode())
            copied['queue-binding.json'] = _hash_regular(
                review / 'queue-binding.json', MAX_JSON, 'Queue binding projection')

        manifest = _base(receipt, copied, source_files['queue-short.json'])
        manifest['files_sha256'] = copied
        manifest_path = review / 'delivery-manifest.json'
        _write_durable(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True,
                                                  allow_nan=False) + '\n').encode())
        all_files = {**copied, 'delivery-manifest.json': _hash_regular(
            manifest_path, MAX_JSON, 'Short delivery manifest')}

        archive_path = temporary / 'review-package.zip'
        with ZipFile(archive_path, 'x', ZIP_DEFLATED) as archive:
            for name in sorted(all_files):
                with archive.open('review/' + name, 'w') as target:
                    require(_copy_to_stream(review / name, target,
                                            MAX_JSON if name.endswith('.json') else MAX_FILE,
                                            'Short archive input: ' + name) == all_files[name],
                            'Short archive input identity changed: ' + name)
        archive_descriptor, _ = _open_regular(
            archive_path, MAX_TOTAL, 'Short delivery archive')
        try:
            os.fsync(archive_descriptor)
        finally:
            os.close(archive_descriptor)

        report = dict(manifest, files_sha256={f'review/{name}': value
                                               for name, value in all_files.items()},
                      manifest_sha256=all_files['delivery-manifest.json'],
                      archive='review-package.zip', archive_sha256=_hash_regular(
                          archive_path, MAX_TOTAL, 'Short delivery archive'))
        report['delivery_identity_sha256'] = _identity(report)
        _write_durable(temporary / 'package.json', (json.dumps(
            report, indent=2, sort_keys=True, allow_nan=False) + '\n').encode())
        _sync_directory(review)
        _sync_directory(temporary)

        # Re-open both representations and the queue source before the atomic,
        # no-replace publication.  A concurrent mutation cannot become a PASS.
        verify_short_delivery(temporary, report['delivery_identity_sha256'])
        require(verify_consumed_short(queue, job_id, source) == retained_receipt
                and _identities(source, FILES) == source_files,
                'Short source changed during delivery')
        _publish_restore(temporary, output)
        _sync_directory(output.parent)
        return report
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def verify_short_delivery(output_dir, expected_delivery_identity_sha256):
    """Reopen an exported Short without trusting its package receipt."""
    output = _path(output_dir)
    require(isinstance(expected_delivery_identity_sha256, str)
            and SHA.fullmatch(expected_delivery_identity_sha256),
            'Trusted expected Short delivery identity required')
    _inventory(output, {'package.json', 'review-package.zip'}, {'review'})
    report = _read_json(output / 'package.json')
    require(set(report) == REPORT_FIELDS, 'Short delivery report schema is invalid')
    require(report.get('delivery_identity_sha256') == expected_delivery_identity_sha256
            and _identity(report) == expected_delivery_identity_sha256,
            'Short delivery identity receipt changed')
    require(report.get('schema_version') == 1
            and report.get('status') == 'AWAITING_REVIEW'
            and report.get('technical_status') == 'PASS'
            and all(report.get(key) is False for key in FLAGS_SET)
            and report.get('scope') == SCOPE
            and report.get('archive') == 'review-package.zip'
            and report.get('entrypoint') == 'review/index.html',
            'Short delivery is not an unpublished technical review')

    review = output / 'review'
    observed_names = {entry.name for entry in os.scandir(review)}
    raw_names = set(FILES) | {'delivery-manifest.json'}
    projected_names = set(DELIVERY_BASE_FILES) | {'queue-binding.json', 'delivery-manifest.json'}
    require(observed_names in (raw_names, projected_names),
            'Short review inventory variant is invalid')
    expected_names = observed_names
    _inventory(review, expected_names)
    files = report.get('files_sha256')
    require(isinstance(files, dict)
            and set(files) == {f'review/{name}' for name in expected_names}
            and all(isinstance(value, str) and SHA.fullmatch(value) for value in files.values()),
            'Short delivery file inventory is invalid')
    actual = {f'review/{name}': _hash_regular(
        review / name, MAX_JSON if name.endswith('.json') else MAX_FILE,
        'Copied Short file: ' + name) for name in expected_names}
    require(actual == files, 'Short delivery file identity changed')
    require(report.get('manifest_sha256') == files['review/delivery-manifest.json']
            and report.get('entrypoint_sha256') == files['review/index.html']
            and report.get('candidate_sha256') == files['review/video.mp4']
            and report.get('caption_sha256') == files['review/captions.vtt'],
            'Short delivery report does not bind the copied files')

    manifest = _read_json(review / 'delivery-manifest.json')
    source_names = expected_names - {'delivery-manifest.json'}
    source_files = {name: files['review/' + name] for name in source_names}
    require(manifest == {**{key: report[key] for key in (
        'schema_version', 'status', 'technical_status', *FLAGS_SET,
        'candidate_sha256', 'caption_sha256', 'encoded_streams_sha256',
        'decoded_picture_sha256', 'queue_receipt_sha256', 'parent_provenance',
        'selection', 'entrypoint', 'entrypoint_sha256', 'scope')},
        'files_sha256': source_files},
        'Short delivery manifest changed')

    if 'queue-short.json' in source_names:
        receipt = _read_json(review / 'queue-short.json')
        require(report.get('queue_receipt_sha256') == files['review/queue-short.json'],
                'Short delivery does not bind its raw queue receipt')
    else:
        binding = _read_json(review / 'queue-binding.json')
        receipt = _validate_queue_binding(binding)
        require(report.get('queue_receipt_sha256') == binding['queue_receipt_sha256'],
                'Short delivery does not bind its projected queue receipt')
    short = _read_json(review / 'short.json')
    _validate_queue_receipt(receipt)
    _validate_short_receipt(short)
    require(receipt.get('status') == 'AWAITING_REVIEW'
            and receipt.get('technical_status') == 'PASS'
            and short.get('status') == 'AWAITING_REVIEW'
            and short.get('technical_status') == 'PASS'
            and all(receipt.get(key) is False and short.get(key) is False for key in FLAGS_SET)
            and receipt.get('candidate_sha256') == report['candidate_sha256']
            and short.get('candidate_sha256') == report['candidate_sha256']
            and receipt.get('caption_sha256') == report['caption_sha256']
            and short.get('caption_sha256') == report['caption_sha256']
            and receipt.get('encoded_streams_sha256') == report['encoded_streams_sha256']
            and receipt.get('decoded_picture_sha256') == report['decoded_picture_sha256']
            and receipt.get('source_provenance') == report['parent_provenance']
            and receipt.get('selection') == report['selection'],
            'Copied Short receipts do not bind the delivery report')
    _verify_semantics(review, receipt)

    archive_path = output / 'review-package.zip'
    descriptor, opened = _open_regular(archive_path, MAX_TOTAL, 'Short delivery archive')
    try:
        with os.fdopen(descriptor, 'rb') as stream:
            require(hashlib.file_digest(stream, 'sha256').hexdigest()
                    == report.get('archive_sha256'),
                    'Short delivery archive identity changed')
            stream.seek(0)
            with ZipFile(stream) as archive:
                members = archive.infolist()
                names = {item.filename for item in members}
                require(len(names) == len(members)
                        and names == {f'review/{name}' for name in expected_names},
                        'Short delivery archive inventory changed')
                total = 0
                for item in members:
                    mode = item.external_attr >> 16
                    total += item.file_size
                    require(stat.S_IFMT(mode) in (0, stat.S_IFREG)
                            and not item.is_dir() and not item.flag_bits & 1
                            and 0 <= item.file_size <= MAX_FILE and total <= MAX_TOTAL,
                            'Short delivery archive member is invalid')
                require(archive.testzip() is None,
                        'Short delivery archive member failed its CRC check')
                for item in members:
                    with archive.open(item) as member:
                        require(hashlib.file_digest(member, 'sha256').hexdigest()
                                == files[item.filename],
                                'Short delivery archive member changed: ' + item.filename)
            require(_same_metadata(opened, os.fstat(stream.fileno())),
                    'Short delivery archive changed while being read')
    except BadZipFile as error:
        raise ValueError('Short delivery archive is invalid') from error
    # Detect concurrent replacement or insertion after semantic and archive replay.
    _inventory(output, {'package.json', 'review-package.zip'}, {'review'})
    _inventory(review, expected_names)
    require({f'review/{name}': _hash_regular(
        review / name, MAX_JSON if name.endswith('.json') else MAX_FILE,
        'Copied Short file: ' + name) for name in expected_names} == files,
        'Short delivery files changed during verification')
    return {'status': 'PASS', **FLAGS,
            'candidate_sha256': report['candidate_sha256'],
            'delivery_identity_sha256': expected_delivery_identity_sha256,
            'archive_sha256': report['archive_sha256'],
            'scope': SCOPE}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export')
    export.add_argument('--queue-root', required=True)
    export.add_argument('--job-id', required=True)
    export.add_argument('--short', required=True)
    export.add_argument('--output', required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('--output', required=True)
    verify.add_argument('--expected-delivery-identity', required=True)
    args = parser.parse_args(argv)
    if args.command == 'export':
        result = export_short_delivery(args.queue_root, args.job_id, args.short, args.output)
    else:
        result = verify_short_delivery(args.output, args.expected_delivery_identity)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
