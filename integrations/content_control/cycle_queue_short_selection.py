"""Record a title and frame-derived thumbnail choice for one exact queue Short.

The parent package supplies authored title/copy only.  Thumbnail pixels are
always rendered from the verified derivative MP4, never copied from the parent.
No audience, creative, production or publishing approval is inferred.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time

from integrations.content_control.cycle_editorial import (
    _flags, _text, _timestamp, normalize_thumbnail_copy,
)
from integrations.content_control.cycle_package import make_thumbnail, run
from integrations.content_control.cycle_queue_short import (
    _source, verify_consumed_short,
)
from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control.cycle_selection import _read_selection
from integrations.content_control.review_package import digest, no_symlinks, require


INPUT_FIELDS = {
    'schema_version', 'short_candidate_sha256', 'parent_candidate_sha256',
    'parent_package_sha256', 'title', 'thumbnail_copy',
    'frame_timestamp_seconds', 'thumbnail_variant', 'reviewer', 'reviewed_at',
    'rationale', 'next_idea_hypotheses',
}
OUTPUT_FILES = {'selection.json', 'thumbnail.png'}
SAFE_LAYOUT_FIELDS = {
    'background_rgb', 'canvas_size', 'caption_bottom_clearance_target_pixels',
    'mode', 'picture_offset', 'scaled_picture_size', 'source_scale_percent',
}


def _canonical_sha(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(',', ':'), allow_nan=False,
    ).encode()).hexdigest()


def _bounded_file(path, limit):
    """Read one stable regular file without following a replacement symlink."""
    flags = os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0)
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    if hasattr(os, 'O_NONBLOCK'):
        flags |= os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= limit,
                'Missing, unsafe or oversized derivative selection output')
        chunks, remaining = [], limit + 1
        while remaining:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block); remaining -= len(block)
        value = b''.join(chunks)
        after = os.fstat(descriptor)
        stable = tuple(getattr(before, name) for name in
                       ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
        require(len(value) <= limit and stable == tuple(getattr(after, name) for name in
                ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')),
                'Derivative selection output changed while reading')
        current = path.lstat()
        require(not stat.S_ISLNK(current.st_mode)
                and (current.st_dev, current.st_ino) == (after.st_dev, after.st_ino),
                'Derivative selection output was replaced while reading')
        return value
    finally:
        os.close(descriptor)


def _output_snapshot(root):
    no_symlinks(root)
    require(root.is_dir() and not root.is_symlink(),
            'Exact derivative selection output required')
    children = list(root.iterdir())
    require(set(path.name for path in children) == OUTPUT_FILES
            and all(path.is_file() and not path.is_symlink() for path in children),
            'Exact derivative selection output required')
    values = {
        'selection.json': _bounded_file(root / 'selection.json', 1024 * 1024),
        'thumbnail.png': _bounded_file(root / 'thumbnail.png', 16 * 1024 * 1024),
    }
    require(set(path.name for path in root.iterdir()) == OUTPUT_FILES,
            'Derivative selection output changed while reading')
    return values


def _safe_layout(receipt):
    overlay = receipt.get('caption_overlay')
    layout = overlay.get('picture_layout') if isinstance(overlay, dict) else None
    require(isinstance(layout, dict) and set(layout) == SAFE_LAYOUT_FIELDS,
            'Exact caption-safe-area picture layout required')
    require(layout == {
        'background_rgb': '#f7f1e6',
        'canvas_size': [720, 1280],
        'caption_bottom_clearance_target_pixels': 125,
        'mode': 'scaled_picture_safe_caption_area_v1',
        'picture_offset': [36, 0],
        'scaled_picture_size': [648, 1152],
        'source_scale_percent': 90,
    }, 'Unsupported caption-safe-area picture layout')
    require(receipt.get('media', {}).get('width') == 720
            and receipt.get('media', {}).get('height') == 1280,
            'Phone-size Short media required')
    return overlay


def _state(queue_root, job_id, short_dir, selection_path):
    queue = Path(os.path.abspath(queue_root))
    short = Path(os.path.abspath(short_dir))
    source = Path(os.path.abspath(selection_path))
    no_symlinks(queue); no_symlinks(short); no_symlinks(source)
    receipt = verify_consumed_short(queue, job_id, short)
    overlay = _safe_layout(receipt)
    cycle, provenance = _source(queue, job_id)
    snapshot = inspect_cycle(cycle)
    require(provenance == receipt.get('source_provenance'),
            'Short parent provenance changed')
    require(snapshot['candidate_sha256'] == receipt.get('parent_candidate_sha256')
            == provenance.get('candidate_sha256'),
            'Short parent candidate changed')
    parent_package = snapshot['files_sha256']['delivery/package.json']
    require(parent_package == provenance.get('package_sha256'),
            'Short parent package changed')
    selection, source_sha = _read_selection(source)
    return {
        'queue': queue, 'short': short, 'source': source, 'receipt': receipt,
        'overlay': overlay, 'cycle': cycle, 'provenance': provenance,
        'snapshot': snapshot, 'selection': selection, 'source_sha': source_sha,
        'queue_receipt_sha': digest(short / 'queue-short.json'),
        'short_receipt_sha': digest(short / 'short.json'),
        'parent_package_sha': parent_package,
    }


def _validated_choice(state, recorded_at):
    selection = state['selection']
    _flags(selection)
    require(isinstance(selection, dict) and set(selection) == INPUT_FIELDS
            and type(selection.get('schema_version')) is int
            and selection['schema_version'] == 1,
            'Exact derivative selection schema version 1 required')
    receipt, snapshot = state['receipt'], state['snapshot']
    require(selection.get('short_candidate_sha256') == receipt.get('candidate_sha256'),
            'Selection targets a different Short candidate')
    require(selection.get('parent_candidate_sha256') == snapshot['candidate_sha256'],
            'Selection targets a different parent candidate')
    require(selection.get('parent_package_sha256') == state['parent_package_sha'],
            'Selection targets a different parent package')
    title = _text(selection.get('title'), 'title', 120)
    require(title == snapshot['editorial']['title'],
            'Title must match the parent package')
    expected_copy = normalize_thumbnail_copy(
        snapshot['editorial'].get('thumbnail_copy', ' '.join(title.split())))
    thumbnail_copy = normalize_thumbnail_copy(selection.get('thumbnail_copy'))
    require(thumbnail_copy == expected_copy,
            'Thumbnail copy must match the parent package')
    timestamp = selection.get('frame_timestamp_seconds')
    duration = receipt.get('media', {}).get('duration_seconds')
    require(type(timestamp) in (int, float) and not isinstance(timestamp, bool)
            and math.isfinite(timestamp) and type(duration) in (int, float)
            and math.isfinite(duration) and 0 <= timestamp < duration,
            'Frame timestamp must be inside the exact Short')
    timestamp = round(float(timestamp), 6)
    variant = selection.get('thumbnail_variant')
    require(type(variant) is int and variant in (0, 1, 2),
            'Thumbnail variant must be 0, 1 or 2')
    reviewer = _text(selection.get('reviewer'), 'reviewer', 200)
    reviewed_at = _timestamp(selection.get('reviewed_at'), 'reviewed_at')
    require(datetime.fromisoformat(reviewed_at)
            >= datetime.fromisoformat(receipt['finished_at']),
            'Selection predates the completed Short')
    require(datetime.fromisoformat(recorded_at) >= datetime.fromisoformat(reviewed_at),
            'Receipt predates selection')
    rationale = _text(selection.get('rationale'), 'rationale', 4000, minimum=12)
    hypotheses = selection.get('next_idea_hypotheses')
    require(isinstance(hypotheses, list) and len(hypotheses) <= 10,
            'At most ten next-idea hypotheses allowed')
    hypotheses = [_text(value, 'next_idea_hypothesis', 1000, minimum=12)
                  for value in hypotheses]
    return {
        'title': title, 'thumbnail_copy': thumbnail_copy,
        'frame_timestamp_seconds': timestamp, 'thumbnail_variant': variant,
        'reviewer': reviewer, 'reviewed_at': reviewed_at, 'rationale': rationale,
        'next_idea_hypotheses': hypotheses,
    }


def _render_thumbnail(short, target, choice, *, deadline=None):
    raw = target.with_name('.thumbnail-frame.png')
    run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-n',
         '-protocol_whitelist', 'file,pipe', '-threads', '2',
         '-ss', format(choice['frame_timestamp_seconds'], '.6f'),
         '-f', 'mov', '-enable_drefs', '0', '-use_absolute_path', '0',
         '-i', str(short / 'video.mp4'), '-frames:v', '1', '-threads', '1',
         str(raw)], 60, deadline=deadline)
    require(raw.is_file() and not raw.is_symlink(), 'Short frame extraction failed')
    try:
        artwork = make_thumbnail(raw, target, choice['thumbnail_copy'],
                                 choice['thumbnail_variant'])
    finally:
        raw.unlink(missing_ok=True)
    require(target.is_file() and not target.is_symlink(), 'Thumbnail render failed')
    return artwork


def _result(state, choice, thumbnail, artwork_sha, recorded_at):
    receipt, snapshot = state['receipt'], state['snapshot']
    result = {
        'schema_version': 1,
        'status': 'DERIVATIVE_THUMBNAIL_MATERIALIZED_AWAITING_VISUAL_REVIEW',
        'job_id': receipt['job_id'],
        'short_candidate_sha256': receipt['candidate_sha256'],
        'short_caption_sha256': receipt['caption_sha256'],
        'thumbnail_source_candidate_sha256': receipt['candidate_sha256'],
        'thumbnail_frame_timestamp_seconds': choice['frame_timestamp_seconds'],
        'thumbnail_variant': choice['thumbnail_variant'],
        'thumbnail_file': 'thumbnail.png',
        'thumbnail_sha256': digest(thumbnail),
        'thumbnail_artwork_sha256': artwork_sha,
        'parent_candidate_sha256': snapshot['candidate_sha256'],
        'parent_package_sha256': state['parent_package_sha'],
        'parent_pipeline_receipt_sha256': state['provenance']['pipeline_receipt_sha256'],
        'queue_short_receipt_sha256': state['queue_receipt_sha'],
        'short_export_receipt_sha256': state['short_receipt_sha'],
        'caption_overlay_sha256': _canonical_sha(state['overlay']),
        'short_artifacts_sha256': receipt['artifacts_sha256'],
        'title': choice['title'],
        'thumbnail_copy': choice['thumbnail_copy'],
        'reviewer': choice['reviewer'],
        'reviewed_at': choice['reviewed_at'],
        'rationale': choice['rationale'],
        'recorded_at': recorded_at,
        'submitted_selection_sha256': state['source_sha'],
        'next_idea_hypotheses': choice['next_idea_hypotheses'],
        'performance': {
            'status': 'UNAVAILABLE', 'impressions': None, 'clicks': None,
            'ctr': None, 'audience_performance_verified': False,
            'winner_inferred': False,
            'scope': 'No attributable audience evidence supplied; no performance winner inferred.',
        },
        'learning_scope': ('Reviewer hypotheses for subsequent ideation; not proven audience '
                           'preferences or autonomous learning.'),
        'selection_scope': ('Submitted frame, variant and copy were materialized from the exact '
                            'Short. A separate inspection of this PNG is still required.'),
        'exact_derivative_visual_review_verified': False,
        'independent_verification': False,
        'publication_enabled': False,
        'paid_generation_enabled': False,
        'production_approved': False,
        'full_av_review': False,
        'production_ready': False,
    }
    return result


def _unchanged(before, queue_root, job_id, short_dir, selection_path):
    after = _state(queue_root, job_id, short_dir, selection_path)
    require(after['receipt'] == before['receipt']
            and after['provenance'] == before['provenance']
            and after['snapshot']['files_sha256'] == before['snapshot']['files_sha256']
            and after['source_sha'] == before['source_sha'],
            'Selection inputs changed while rendering')
    return after


def record_short_selection(queue_root, job_id, short_dir, selection_path, output):
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    before = _state(queue_root, job_id, short_dir, selection_path)
    recorded_at = datetime.now(timezone.utc).isoformat()
    choice = _validated_choice(before, recorded_at)
    destination = Path(os.path.abspath(output))
    no_symlinks(destination)
    require(not destination.exists(), 'Output already exists')
    require(all(not destination.is_relative_to(path) and destination != path
                for path in (before['queue'], before['short'], before['cycle'], before['source'])),
            'Output must be separate from queue, media, parent and input')
    destination.parent.mkdir(parents=True, exist_ok=True)
    no_symlinks(destination.parent)
    temporary = Path(tempfile.mkdtemp(prefix=f'.{destination.name}-',
                                      dir=destination.parent))
    try:
        thumbnail = temporary / 'thumbnail.png'
        artwork = _render_thumbnail(before['short'], thumbnail, choice,
                                    deadline=time.monotonic() + 90)
        after = _unchanged(before, queue_root, job_id, short_dir, selection_path)
        result = _result(after, choice, thumbnail, artwork, recorded_at)
        (temporary / 'selection.json').write_text(json.dumps(
            result, indent=2, sort_keys=True, allow_nan=False) + '\n')
        require(set(path.name for path in temporary.iterdir()) == OUTPUT_FILES,
                'Unexpected derivative selection output')
        _unchanged(before, queue_root, job_id, short_dir, selection_path)
        os.replace(temporary, destination)
        return result
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_short_selection(queue_root, job_id, short_dir, selection_path, output):
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    state = _state(queue_root, job_id, short_dir, selection_path)
    root = Path(os.path.abspath(output))
    initial = _output_snapshot(root)
    recorded, receipt_sha = _read_selection(root / 'selection.json')
    require(hashlib.sha256(initial['selection.json']).hexdigest() == receipt_sha,
            'Selection receipt changed while reading')
    recorded_at = _timestamp(recorded.get('recorded_at'), 'recorded_at')
    choice = _validated_choice(state, recorded_at)
    with tempfile.TemporaryDirectory(prefix='.short-selection-replay-',
                                     dir=root.parent) as directory:
        replay = Path(directory) / 'thumbnail.png'
        artwork = _render_thumbnail(state['short'], replay, choice,
                                    deadline=time.monotonic() + 90)
        require(replay.read_bytes() == initial['thumbnail.png'],
                'Thumbnail pixels do not replay from the exact Short')
        expected = _result(state, choice, replay, artwork, recorded_at)
    require(recorded == expected,
            'Derivative selection receipt does not match its inputs and thumbnail')
    _unchanged(state, queue_root, job_id, short_dir, selection_path)
    require(_output_snapshot(root) == initial,
            'Derivative selection output changed while verifying')
    return expected, receipt_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('record', 'verify'))
    parser.add_argument('--queue-root', required=True)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--short', required=True)
    parser.add_argument('--selection', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.action == 'record':
        result = record_short_selection(args.queue_root, args.job_id, args.short,
                                        args.selection, args.output)
    else:
        result = verify_short_selection(args.queue_root, args.job_id, args.short,
                                        args.selection, args.output)[0]
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
