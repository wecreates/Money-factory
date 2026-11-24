"""Retain exact-candidate, live-view-only competitor comparison attestations.

This module validates the shape and full-interval coverage of supplied playback
observations.  It never opens a competitor URL, downloads media, infers rank, or
turns a reviewer statement into independent creative approval.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from urllib.parse import parse_qs, parse_qsl, quote_from_bytes, unquote_to_bytes

from integrations.content_control.cycle_av_benchmarks import _url as _public_url
from integrations.content_control.cycle_editorial import _text, _timestamp
from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control.review_package import SHA, no_symlinks, require


LIMIT = 256 * 1024
ROOT_FIELDS = {'schema_version', 'candidate_sha256', 'reviewer', 'reviewed_at',
               'candidate_observation', 'references'}
OBSERVATION_FIELDS = {'duration_seconds', 'intervals'}
REFERENCE_FIELDS = {'url', 'topic', 'format', 'selection_basis',
                    'selection_evidence_url', 'selected_at', 'observed_at',
                    'access', 'duration_seconds', 'intervals',
                    'candidate_differences', 'actionable_findings'}
ACCESS_FIELDS = {'mode', 'playback_permitted', 'media_downloaded', 'accessible',
                 'picture_accessible', 'sound_accessible'}
INTERVAL_FIELDS = {'start_seconds', 'end_seconds', 'audio_observation',
                   'visual_observation', 'pacing_observation', 'story_observation'}
FORMATS = {'portrait', 'landscape', 'square'}
DIFFERENCE_FIELDS = {'audio', 'visual', 'pacing', 'story'}
FLAGS = ('publication_enabled', 'paid_generation_enabled', 'production_approved',
         'full_av_review', 'production_ready', 'competitor_comparison_verified')
SCOPE = ('Exact-candidate live-view comparison attestation with two supplied ranking-evidence links, '
         'explicit candidate differences and actionable findings. Playback observations, rank, '
         'relevance and creative judgments are not independently verified.')


def _canonical_url_identity(value):
    parsed = _public_url(value)
    path = quote_from_bytes(unquote_to_bytes(parsed.path or '/'),
                            safe="/:@-._~!$&'()*+,;=")
    require(all(part not in ('.', '..') for part in path.split('/')),
            'Canonical public URL path required')
    query = tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True,
                                   strict_parsing=False, max_num_fields=100)))
    host = (parsed.hostname or '').lower().removeprefix('www.')
    return host, path.rstrip('/') or '/', query


def _specific_identity(value):
    """Normalize aliases enough to keep the two playback references distinct."""
    parsed = _public_url(value)
    host = (parsed.hostname or '').lower().removeprefix('www.')
    path = parsed.path.rstrip('/')
    if host in ('youtube.com', 'm.youtube.com', 'youtu.be'):
        if host == 'youtu.be':
            video = path[1:]
        elif path == '/watch':
            values = parse_qs(parsed.query).get('v', [])
            video = values[0] if len(values) == 1 else ''
        else:
            match = re.fullmatch(r'/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})', path)
            video = match.group(1) if match else ''
        require(re.fullmatch(r'[A-Za-z0-9_-]{11}', video),
                'A specific YouTube reference is required')
        return 'youtube', video
    if host in ('instagram.com', 'm.instagram.com'):
        match = re.fullmatch(r'/(?:reel|reels)/([A-Za-z0-9_-]+)', path)
        require(match is not None, 'A specific Instagram reel reference is required')
        return 'instagram', match.group(1)
    require(path and path != '/', 'A specific video reference is required')
    return _canonical_url_identity(value)


def _evidence_identity(value):
    """Recognize media aliases while still allowing non-media ranking pages."""
    try:
        return _specific_identity(value)
    except ValueError:
        return 'public-page', *_canonical_url_identity(value)


def _duration(value, field):
    require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 3600,
            field + ': finite duration from 0 to 3600 required')
    return float(value)


def _read_source(path):
    no_symlinks(path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= LIMIT,
                'Bounded live comparison JSON required')
        raw = stream.read(LIMIT + 1)
        after = os.fstat(stream.fileno())
    require(len(raw) == before.st_size <= LIMIT
            and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            'Live comparison JSON changed while reading')
    return raw


def _intervals(value, duration, field):
    require(isinstance(value, list) and 1 <= len(value) <= 600,
            field + ': one to 600 reviewed intervals required')
    normalized, cursor = [], 0.0
    for index, item in enumerate(value):
        require(isinstance(item, dict) and set(item) == INTERVAL_FIELDS,
                field + ': exact interval fields required')
        start = item['start_seconds']; end = item['end_seconds']
        require(type(start) in (int, float) and type(end) in (int, float)
                and math.isfinite(start) and math.isfinite(end)
                and math.isclose(float(start), cursor, abs_tol=0.001)
                and cursor < float(end) <= duration,
                field + ': intervals must be contiguous, ordered and bounded')
        row = {'start_seconds': float(start), 'end_seconds': float(end)}
        for name in INTERVAL_FIELDS - {'start_seconds', 'end_seconds'}:
            row[name] = _text(item.get(name), f'{field}[{index}].{name}', 1200,
                              minimum=12)
        normalized.append(row)
        cursor = float(end)
    require(math.isclose(cursor, duration, abs_tol=0.001),
            field + ': intervals must cover the full playback duration')
    return normalized


def _differences(value, field):
    require(isinstance(value, dict) and set(value) == DIFFERENCE_FIELDS,
            field + ': exact audio, visual, pacing and story differences required')
    return {name: _text(value[name], f'{field}.{name}', 1200, minimum=12)
            for name in sorted(DIFFERENCE_FIELDS)}


def _findings(value, field):
    require(isinstance(value, list) and 1 <= len(value) <= 20,
            field + ': one to 20 actionable findings required')
    return [_text(item, f'{field}[{index}]', 600, minimum=12)
            for index, item in enumerate(value)]


def validate_observations(value, candidate_sha256):
    require(isinstance(value, dict) and set(value) == ROOT_FIELDS,
            'Exact live comparison fields required')
    require(type(value.get('schema_version')) is int and value['schema_version'] == 2,
            'Live comparison schema version 2 required')
    require(isinstance(candidate_sha256, str) and SHA.fullmatch(candidate_sha256)
            and value.get('candidate_sha256') == candidate_sha256,
            'Live comparison targets a different candidate')
    reviewer = _text(value.get('reviewer'), 'reviewer', 200, minimum=3)
    reviewed_at = _timestamp(value.get('reviewed_at'), 'reviewed_at')
    candidate = value.get('candidate_observation')
    require(isinstance(candidate, dict) and set(candidate) == OBSERVATION_FIELDS,
            'Exact candidate observation required')
    candidate_duration = _duration(candidate['duration_seconds'], 'candidate.duration_seconds')
    candidate_result = {'duration_seconds': candidate_duration,
                        'intervals': _intervals(candidate['intervals'], candidate_duration,
                                                'candidate.intervals')}
    references = value.get('references')
    require(isinstance(references, list) and len(references) == 2,
            'Exactly two live-view competitor references required')
    normalized, identities, ranking_urls, ranking_resources, playback_urls = [], [], [], [], []
    for index, row in enumerate(references):
        field = f'references[{index}]'
        require(isinstance(row, dict) and set(row) == REFERENCE_FIELDS,
                field + ': exact reference fields required')
        url = _text(row['url'], field + '.url', 2048)
        _public_url(url)
        identities.append(_specific_identity(url))
        playback_urls.append(_canonical_url_identity(url))
        evidence = _text(row['selection_evidence_url'], field + '.selection_evidence_url', 2048)
        _public_url(evidence)
        ranking_urls.append(_canonical_url_identity(evidence))
        ranking_resources.append(_evidence_identity(evidence))
        access = row['access']
        require(isinstance(access, dict) and set(access) == ACCESS_FIELDS
                and access.get('mode') == 'live_view_only'
                and access.get('playback_permitted') is True
                and access.get('media_downloaded') is False
                and access.get('accessible') is True
                and access.get('picture_accessible') is True
                and access.get('sound_accessible') is True,
                field + ': permitted live picture-and-sound playback is required')
        duration = _duration(row['duration_seconds'], field + '.duration_seconds')
        normalized.append({
            'url': url,
            'topic': _text(row['topic'], field + '.topic', 500, minimum=3),
            'format': row['format'],
            'selection_basis': _text(row['selection_basis'], field + '.selection_basis',
                                     1200, minimum=12),
            'selection_evidence_url': evidence,
            'selected_at': _timestamp(row['selected_at'], field + '.selected_at'),
            'observed_at': _timestamp(row['observed_at'], field + '.observed_at'),
            'access': dict(access),
            'duration_seconds': duration,
            'intervals': _intervals(row['intervals'], duration, field + '.intervals'),
            'candidate_differences': _differences(
                row['candidate_differences'], field + '.candidate_differences'),
            'actionable_findings': _findings(
                row['actionable_findings'], field + '.actionable_findings'),
        })
        require(row['format'] in FORMATS, field + ': supported format required')
        require(datetime.fromisoformat(normalized[-1]['observed_at']) >=
                datetime.fromisoformat(normalized[-1]['selected_at']),
                field + ': playback cannot predate reference selection')
    require(len(set(identities)) == 2, 'Two distinct competitor videos are required')
    require(len(set(ranking_urls)) == 2, 'Separate ranking evidence is required for both references')
    require(len(set(ranking_resources)) == 2,
            'Ranking evidence links must identify two separate resources')
    require(set(ranking_urls).isdisjoint(playback_urls),
            'Ranking evidence must be separate from both playback references')
    require(set(ranking_resources).isdisjoint(identities),
            'Ranking evidence must not alias either competitor video')
    reviewed = datetime.fromisoformat(reviewed_at)
    require(all(reviewed >= datetime.fromisoformat(row['observed_at']) for row in normalized),
            'Review time cannot predate reference playback')
    return {'schema_version': 2, 'candidate_sha256': candidate_sha256,
            'reviewer': reviewer, 'reviewed_at': reviewed_at,
            'candidate_observation': candidate_result, 'references': normalized}


def _canonical_sha(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _bind_cycle(root, snapshot, comparison):
    render = json.loads((root / 'delivery/render.json').read_text(),
                        object_pairs_hook=_pairs, parse_constant=_constant)
    encoded_duration = _duration(render.get('duration_seconds'), 'render.duration_seconds')
    require(math.isclose(comparison['candidate_observation']['duration_seconds'],
                         encoded_duration, abs_tol=0.001),
            'Candidate observation does not cover the encoded candidate duration')
    expected_format = 'landscape' if snapshot['editorial'].get('layout') == 'landscape' else 'portrait'
    expected_topic = snapshot['editorial']['topic']
    require(all(row['format'] == expected_format for row in comparison['references']),
            'Competitor format differs from the exact candidate')
    require(all(row['topic'] == expected_topic for row in comparison['references']),
            'Competitor topic differs from the exact candidate')
    require(datetime.fromisoformat(comparison['reviewed_at']) >=
            datetime.fromisoformat(snapshot['cycle']['finished_at']),
            'Live comparison predates the completed candidate')


def _recorded_result(snapshot, comparison, submitted_sha, recorded_at):
    require(isinstance(submitted_sha, str) and SHA.fullmatch(submitted_sha),
            'Submitted live comparison identity required')
    recorded_at = _timestamp(recorded_at, 'recorded_at')
    recorded = datetime.fromisoformat(recorded_at)
    require(recorded >= datetime.fromisoformat(comparison['reviewed_at']),
            'Live comparison receipt predates its review')
    require(recorded <= datetime.now(timezone.utc),
            'Live comparison receipt cannot be future dated')
    return {
        **comparison,
        'status': 'COMPARISON_ATTESTATION_RECORDED',
        'recorded_at': recorded_at,
        'submitted_observations_sha256': submitted_sha,
        'normalized_observations_sha256': _canonical_sha(comparison),
        'source_files_sha256': snapshot['files_sha256'],
        'full_interval_schema_validated': True,
        'independent_verification': False,
        **dict.fromkeys(FLAGS, False),
        'scope': SCOPE,
    }


def validate_recorded_comparison(cycle_dir, value):
    """Replay an embedded comparison receipt against the exact current candidate."""
    root = Path(os.path.abspath(cycle_dir))
    snapshot = inspect_cycle(root)
    require(isinstance(value, dict) and ROOT_FIELDS <= set(value),
            'Recorded live comparison receipt required')
    submitted = {name: value[name] for name in ROOT_FIELDS}
    comparison = validate_observations(submitted, snapshot['candidate_sha256'])
    _bind_cycle(root, snapshot, comparison)
    expected = _recorded_result(
        snapshot, comparison, value.get('submitted_observations_sha256'),
        value.get('recorded_at'))
    require(value == expected,
            'Recorded live comparison identity, evidence or scope changed')
    require(inspect_cycle(root)['files_sha256'] == snapshot['files_sha256'],
            'Cycle changed while replaying live comparison evidence')
    return expected


def record_live_comparison(cycle_dir, observations_path, output):
    require(all(os.environ.get(name, 'false').lower() == 'false' for name in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    root = Path(os.path.abspath(cycle_dir))
    snapshot = inspect_cycle(root)
    source = Path(os.path.abspath(observations_path))
    raw = _read_source(source)
    submitted_sha = hashlib.sha256(raw).hexdigest()
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    comparison = validate_observations(value, snapshot['candidate_sha256'])
    _bind_cycle(root, snapshot, comparison)
    result = _recorded_result(
        snapshot, comparison, submitted_sha, datetime.now(timezone.utc).isoformat())
    require(inspect_cycle(root)['files_sha256'] == snapshot['files_sha256']
            and _read_source(source) == raw,
            'Comparison inputs changed while recording')
    output = Path(os.path.abspath(output))
    no_symlinks(output)
    require(not output.exists() and not output.is_relative_to(root) and output != source,
            'Output must be new and separate from inputs')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return result


def verify_live_comparison(cycle_dir, observations_path, receipt_path):
    """Replay both the submitted observations and retained receipt without writes."""
    source = Path(os.path.abspath(observations_path))
    receipt_path = Path(os.path.abspath(receipt_path))
    require(source != receipt_path, 'Comparison observations and receipt must be separate')
    source_raw = _read_source(source)
    receipt_raw = _read_source(receipt_path)
    receipt = json.loads(receipt_raw, object_pairs_hook=_pairs, parse_constant=_constant)
    expected = validate_recorded_comparison(cycle_dir, receipt)
    require(expected['submitted_observations_sha256'] == hashlib.sha256(source_raw).hexdigest(),
            'Submitted live comparison observations changed')
    submitted = json.loads(source_raw, object_pairs_hook=_pairs, parse_constant=_constant)
    normalized = validate_observations(submitted, expected['candidate_sha256'])
    require(_canonical_sha(normalized) == expected['normalized_observations_sha256'],
            'Submitted live comparison no longer matches the receipt')
    require(_read_source(source) == source_raw and _read_source(receipt_path) == receipt_raw,
            'Comparison verification inputs changed')
    return expected, hashlib.sha256(receipt_raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-dir', required=True)
    parser.add_argument('--observations', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output')
    mode.add_argument('--verify-receipt')
    args = parser.parse_args()
    if args.verify_receipt:
        result = verify_live_comparison(
            args.cycle_dir, args.observations, args.verify_receipt)[0]
    else:
        result = record_live_comparison(args.cycle_dir, args.observations, args.output)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
