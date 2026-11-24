"""Consume one durably completed cycle into an unpublished, queue-bound Short.

This is deliberately read-only with respect to the queue.  The immutable job,
durable completion and exact parent-cycle artifacts are rechecked before and after
the existing Short exporter runs.  No success or approval transfers from the
parent video.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import time

from integrations.content_control.cycle_short import make_short, media_identities, _probe
from integrations.content_control.review_delivery import read_json, verify_delivery
from integrations.content_control.review_package import digest, no_symlinks

FLAGS = {key: False for key in ('publication_enabled', 'paid_generation_enabled',
                                'production_approved', 'full_av_review',
                                'production_ready')}
ARTIFACTS = ('video.mp4', 'captions.vtt', 'automated-review.json',
             'index.html', 'short.json')
SHA = re.compile(r'[0-9a-f]{64}')

# Exact schema-1 pair from main before compact quote support (0b42130).
# These receipts already carry the current selection and artifact fields.
PRE_COMPACT_QUOTE_TOOL_PAIR = (
    '7d1273737a50aff80b49494df857e3866a2c40bc4fa7e5f1a6c6c4691374f592',
    'd2c21d9f9e1cefc2b9f153697372e9e30c6fea086e445e32274b172e2a0bc436',
)


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                               allow_nan=False) + '\n')


def _verified_tool_pair(receipt):
    retained = (receipt.get('consumer_tool_sha256'), receipt.get('exporter_tool_sha256'))
    current = (digest(Path(__file__)), digest(Path(make_short.__code__.co_filename)))
    return retained in (current, PRE_COMPACT_QUOTE_TOOL_PAIR)


def _source(queue_root, job_id):
    review, provenance = verify_delivery(queue_root, job_id)
    if provenance.get('adapter') != 'content-control-cycle':
        raise ValueError('Only a durably completed content cycle can feed a Short')
    cycle = review.parent
    if cycle.is_symlink() or not cycle.is_dir():
        raise ValueError('Verified source cycle is unavailable')
    return cycle, provenance


def _artifacts(output):
    values = {}
    for name in ARTIFACTS:
        path = output / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Short artifact is missing or unsafe')
        values[name] = digest(path)
    return values


def _scene_selection(cycle, scene_ids):
    """Resolve exact contiguous authored scenes from the bound render receipt."""
    if (not isinstance(scene_ids, (list, tuple)) or not scene_ids
            or any(not isinstance(value, str) or not value or len(value) > 128
                   for value in scene_ids)
            or len(set(scene_ids)) != len(scene_ids)):
        raise ValueError('Scene selection requires unique nonempty scene IDs')
    path = cycle / 'delivery/render.json'
    if (path.is_symlink() or not path.is_file()
            or path.stat().st_size > 1024 * 1024):
        raise ValueError('Bound render receipt is unavailable for scene selection')
    render = read_json(path)
    rows = render.get('scenes') if isinstance(render, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError('Bound render receipt has no authored scene timeline')
    ordered, positions = [], {}
    previous_end = None
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('Bound authored scene timeline is invalid')
        scene_id, start, end = row.get('scene_id'), row.get('start'), row.get('end')
        if (not isinstance(scene_id, str) or not scene_id or scene_id in positions
                or type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or not 0 <= start < end
                or (previous_end is not None and abs(start - previous_end) > .001)):
            raise ValueError('Bound authored scene timeline is invalid')
        ordered.append((scene_id, float(start), float(end)))
        positions[scene_id] = index
        previous_end = end
    try:
        indexes = [positions[value] for value in scene_ids]
    except KeyError as error:
        raise ValueError('Requested scene is absent from the bound render receipt') from error
    if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
        raise ValueError('Short scenes must be contiguous and in authored order')
    raw_start, raw_end = ordered[indexes[0]][1], ordered[indexes[-1]][2]
    start, end = round(raw_start * 1000) / 1000, round(raw_end * 1000) / 1000
    if start >= end:
        raise ValueError('Authored scene span is shorter than one exporter millisecond')
    if end - start > 60:
        raise ValueError('Authored scene span exceeds the 60-second Short limit')
    return {
        'method': 'authored_contiguous_scene_span_v1',
        'scene_ids': list(scene_ids),
        'render_receipt_sha256': digest(path),
        'start_seconds': start,
        'end_seconds': end,
        'editorial_selection_verified': False,
        'scope': ('Contiguous authored scene boundaries from the durable parent render receipt, '
                  'canonicalized to the exporter millisecond contract. This binds the cut; it does not '
                  'establish that the scenes are the best creative selection.'),
    }


def _selection(cycle, start, end, scene_ids):
    if scene_ids:
        if start is not None or end is not None:
            raise ValueError('Use either authored scenes or explicit time bounds, not both')
        return _scene_selection(cycle, scene_ids)
    if start is None or end is None:
        raise ValueError('Both explicit time bounds or at least one authored scene are required')
    if (type(start) not in (int, float) or type(end) not in (int, float)
            or not math.isfinite(start) or not math.isfinite(end)
            or not 0 <= start < end or end - start > 60):
        raise ValueError('Explicit finite interval of at most 60 seconds required')
    start, end = round(start * 1000) / 1000, round(end * 1000) / 1000
    if start >= end:
        raise ValueError('Explicit interval must span at least one exporter millisecond')
    return {
        'method': 'explicit_time_bounds_v1', 'scene_ids': [],
        'render_receipt_sha256': None, 'start_seconds': start, 'end_seconds': end,
        'editorial_selection_verified': False,
        'scope': 'Explicit supplied time bounds; not automatic editorial selection or creative approval.',
    }


def _verify_payload(cycle, source, output, receipt, deadline):
    """Cross-check both receipts, every named artifact and decoded media."""
    short = read_json(output / 'short.json')
    artifacts = _artifacts(output)
    streams, picture = media_identities(output / 'video.mp4', output.parent, deadline)
    media = _probe(output / 'video.mp4', deadline)
    actual = {
        'candidate_sha256': artifacts['video.mp4'],
        'caption_sha256': artifacts['captions.vtt'],
        'automated_review_sha256': artifacts['automated-review.json'],
        'preview_sha256': artifacts['index.html'],
        'source_caption_sha256': digest(cycle / 'delivery/captions.vtt'),
        'parent_candidate_sha256': source.get('candidate_sha256'),
        'parent_cycle_sha256': source.get('pipeline_receipt_sha256'),
        'encoded_streams_sha256': streams,
        'decoded_picture_sha256': picture,
        'media': media,
    }
    selection = receipt.get('selection')
    if not isinstance(selection, dict):
        raise ValueError('Short selection receipt is missing')
    if selection.get('method') == 'authored_contiguous_scene_span_v1':
        expected_selection = _scene_selection(cycle, selection.get('scene_ids'))
    elif selection.get('method') == 'explicit_time_bounds_v1':
        expected_selection = _selection(cycle, selection.get('start_seconds'),
                                        selection.get('end_seconds'), None)
    else:
        raise ValueError('Short selection method is unsupported')
    if (selection != expected_selection
            or selection.get('start_seconds') != receipt.get('start_seconds')
            or selection.get('end_seconds') != receipt.get('end_seconds')):
        raise ValueError('Short selection no longer matches the durable parent')
    if (short.get('schema_version') != 1
            or receipt.get('schema_version') != 1
            or short.get('status') != 'AWAITING_REVIEW'
            or short.get('technical_status') != 'PASS'
            or any(short.get(key) is not False for key in FLAGS)
            or receipt.get('status') != 'AWAITING_REVIEW'
            or receipt.get('technical_status') != 'PASS'
            or any(receipt.get(key) is not False for key in FLAGS)
            or receipt.get('artifacts_sha256') != artifacts
            or any(short.get(key) != value or receipt.get(key) != value
                   for key, value in actual.items())
            or any(short.get(key) != receipt.get(key)
                   for key in ('start_seconds', 'end_seconds'))
            or type(receipt.get('start_seconds')) not in (int, float)
            or type(receipt.get('end_seconds')) not in (int, float)
            or not all(math.isfinite(receipt[key]) for key in ('start_seconds', 'end_seconds'))
            or not 0 <= receipt['start_seconds'] < receipt['end_seconds']
            or receipt['end_seconds'] - receipt['start_seconds'] > 60):
        raise ValueError('Short receipts do not bind the durable source and exact output')
    return artifacts, short


def consume_short(queue_root, job_id, output, *, start=None, end=None, scene_ids=None,
                  timeout=180, hide_source_counter=False, compact_captions=False):
    """Run the existing exporter against one exact durable queue completion."""
    if any(os.environ.get(key, 'false').lower() != 'false'
           for key in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')):
        raise ValueError('Publishing and paid generation must stay disabled')
    output = Path(os.path.abspath(output))
    no_symlinks(output)
    if output.exists() or output.is_relative_to(Path(os.path.abspath(queue_root))):
        raise ValueError('Fresh Short output directory outside the queue required')
    cycle, before = _source(queue_root, job_id)
    selection = _selection(cycle, start, end, scene_ids)
    start, end = selection['start_seconds'], selection['end_seconds']
    result = make_short(cycle, output, start=start, end=end, timeout=timeout,
                        hide_source_counter=hide_source_counter,
                        compact_captions=compact_captions)
    consumer_path = output / 'queue-short.json'
    receipt = {'schema_version': 1, 'status': 'BLOCKED', **FLAGS,
               'job_id': job_id, 'source_provenance': before,
               'selection': selection,
               'started_at': datetime.now(timezone.utc).isoformat(),
               'scope': ('Exact durable parent-cycle queue completion consumed by the existing '
                         'bounded Short exporter; no creative, listening, phone or publishing approval.')}
    try:
        if (result.get('status') != 'AWAITING_REVIEW'
                or result.get('technical_status') != 'PASS'
                or any(result.get(key) is not False for key in FLAGS)
                or result.get('parent_candidate_sha256') != before.get('candidate_sha256')
                or result.get('parent_cycle_sha256') != before.get('pipeline_receipt_sha256')):
            raise ValueError('Short exporter did not retain the durable parent identity')
        streams = result.get('encoded_streams_sha256')
        if (not isinstance(streams, dict) or set(streams) != {'video', 'audio'}
                or any(not isinstance(value, str) or not SHA.fullmatch(value)
                       for value in streams.values())
                or not isinstance(result.get('decoded_picture_sha256'), str)
                or not SHA.fullmatch(result['decoded_picture_sha256'])):
            raise ValueError('Short encoded-stream or decoded-frame identity is missing')
        cycle_after, after = _source(queue_root, job_id)
        current_selection = (_scene_selection(cycle_after, selection['scene_ids'])
                             if selection['scene_ids'] else
                             _selection(cycle_after, selection['start_seconds'],
                                        selection['end_seconds'], None))
        if cycle_after != cycle or after != before or current_selection != selection:
            raise ValueError('Durable source changed while producing the Short')
        artifacts = _artifacts(output)
        if (artifacts['video.mp4'] != result.get('candidate_sha256')
                or artifacts['captions.vtt'] != result.get('caption_sha256')
                or artifacts['automated-review.json'] != result.get('automated_review_sha256')
                or artifacts['index.html'] != result.get('preview_sha256')):
            raise ValueError('Short artifacts do not match the exporter receipt')
        receipt.update(status='AWAITING_REVIEW', technical_status='PASS',
                       candidate_sha256=result['candidate_sha256'],
                       caption_sha256=result['caption_sha256'],
                       automated_review_sha256=result['automated_review_sha256'],
                       preview_sha256=result['preview_sha256'],
                       decoded_picture_sha256=result['decoded_picture_sha256'],
                       encoded_streams_sha256=streams,
                       media=result['media'],
                       parent_candidate_sha256=result['parent_candidate_sha256'],
                       parent_cycle_sha256=result['parent_cycle_sha256'],
                       source_caption_sha256=result['source_caption_sha256'],
                       start_seconds=result['start_seconds'],
                       end_seconds=result['end_seconds'],
                       artifacts_sha256=artifacts,
                       consumer_tool_sha256=digest(Path(__file__)),
                       exporter_tool_sha256=result['tool_sha256'])
        _verify_payload(cycle, before, output, receipt, time.monotonic() + 60)
        # The queue is read again after every output identity is known.  The
        # receipt is written last so a crash cannot leave a false PASS.
        final_cycle, final_source = _source(queue_root, job_id)
        if final_cycle != cycle or final_source != before or _artifacts(output) != artifacts:
            raise ValueError('Source or Short artifacts changed before completion')
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
        receipt.update(status='BLOCKED', technical_status='FAIL', reason=str(error))
    finally:
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        _write(consumer_path, receipt)
    return receipt


def verify_consumed_short(queue_root, job_id, output):
    """Replay queue and artifact identities without producing or modifying media."""
    output = Path(os.path.abspath(output))
    no_symlinks(output)
    receipt_path = output / 'queue-short.json'
    if receipt_path.is_symlink() or not receipt_path.is_file() or receipt_path.stat().st_size > 1024 * 1024:
        raise ValueError('Missing bounded Short consumer receipt')
    receipt = read_json(receipt_path)
    if (not isinstance(receipt, dict) or receipt.get('status') != 'AWAITING_REVIEW'
            or receipt.get('technical_status') != 'PASS'
            or any(receipt.get(key) is not False for key in FLAGS)
            or receipt.get('job_id') != job_id
            or not _verified_tool_pair(receipt)):
        raise ValueError('Short consumer receipt is not an unpublished PASS')
    cycle, source = _source(queue_root, job_id)
    if source != receipt.get('source_provenance'):
        raise ValueError('Durable source no longer matches the Short')
    if _artifacts(output) != receipt.get('artifacts_sha256'):
        raise ValueError('Short artifact identity changed')
    artifacts, short = _verify_payload(cycle, source, output, receipt,
                                       time.monotonic() + 60)
    if (not isinstance(receipt.get('candidate_sha256'), str)
            or not SHA.fullmatch(receipt['candidate_sha256'])
            or short.get('candidate_sha256') != receipt.get('candidate_sha256')
            or short.get('caption_sha256') != receipt.get('caption_sha256')
            or short.get('tool_sha256') != receipt.get('exporter_tool_sha256')
            or artifacts != receipt.get('artifacts_sha256')):
        raise ValueError('Short receipt does not bind the durable source and output')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue-root', required=True)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--start', type=float)
    parser.add_argument('--end', type=float)
    parser.add_argument('--scene', action='append', dest='scene_ids',
                        help='Authored scene ID; repeat for one contiguous span')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--hide-source-counter', action='store_true')
    parser.add_argument('--compact-captions', action='store_true')
    args = parser.parse_args()
    result = consume_short(args.queue_root, args.job_id, args.output,
                           start=args.start, end=args.end, scene_ids=args.scene_ids,
                           timeout=args.timeout,
                           hide_source_counter=args.hide_source_counter,
                           compact_captions=args.compact_captions)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'AWAITING_REVIEW' else 2


if __name__ == '__main__':
    raise SystemExit(main())
