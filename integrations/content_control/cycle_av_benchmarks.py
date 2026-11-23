"""Offline technical comparison against two operator-selected exact videos.

CYZOR_REVIEW_BENCHMARKS is the absolute path to a local JSON object with
schema_version 1 and either two references or reference_sets with one pair per
configured portrait, landscape or square format. Each reference supplies a public
HTTPS url, a local MP4 path (absolute or relative to the manifest), sha256,
authorized=true, selection_rationale, selection_evidence_url and timezone-aware
selected_at. URLs are provenance only. This adapter never opens them or accepts
Instagram media, which is reserved for permitted live review.
"""
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from subprocess import SubprocessError, TimeoutExpired
from urllib.parse import parse_qs, urlsplit

from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.review_package import SHA, check_deadline, no_symlinks, require


MANIFEST_LIMIT = 64 * 1024
MEDIA_LIMIT = 512 * 1024 * 1024
REFERENCE_FIELDS = {'url', 'path', 'sha256', 'authorized', 'selection_rationale',
                    'selection_evidence_url', 'selected_at'}
INSTAGRAM_HOSTS = ('instagram.com', 'instagr.am', 'cdninstagram.com')
FORMATS = {'portrait', 'landscape', 'square'}


def _url(value):
    require(isinstance(value, str) and 0 < len(value) <= 2048 and value.isascii()
            and not any(char.isspace() for char in value) and '\\' not in value, 'Invalid public URL')
    parsed = urlsplit(value)
    host = parsed.hostname or ''
    require(parsed.scheme == 'https' and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443) and not parsed.fragment
            and re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}', host)
            and not host.endswith(('.local', '.internal', '.localhost', '.test', '.invalid')), 'Invalid public URL')
    return parsed


def _reference_id(parsed):
    host = parsed.hostname
    require(not any(host == h or host.endswith('.' + h) for h in INSTAGRAM_HOSTS),
            'Instagram references require live observation')
    path = parsed.path.rstrip('/')
    if host in ('www.youtube.com', 'm.youtube.com', 'youtube.com', 'youtu.be'):
        if host == 'youtu.be':
            video_id = path[1:]
        elif path == '/watch':
            ids = parse_qs(parsed.query).get('v', [])
            video_id = ids[0] if len(ids) == 1 else ''
        else:
            match = re.fullmatch(r'/(?:shorts|live|embed)/([\w-]+)', path)
            video_id = match[1] if match else ''
        require(re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id), 'A specific YouTube video is required')
        return 'youtube', video_id
    require(path or parsed.query, 'A specific public video URL is required')
    return host.removeprefix('www.'), path, parsed.query


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read(path, limit, *, media, deadline):
    check_deadline(deadline)
    no_symlinks(path)
    require(stat.S_ISREG(path.lstat().st_mode), 'A regular local file is required')
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit, 'Invalid local file type or size')
        if media:
            header = stream.read(16)
            require(len(header) == 16 and header[4:8] == b'ftyp', 'A local MP4 is required')
            result = hashlib.sha256(header)
            while chunk := stream.read(min(1024 * 1024, info.st_size - stream.tell() + 1)):
                check_deadline(deadline)
                require(stream.tell() <= info.st_size, 'Local file grew during review')
                result.update(chunk)
            result = result.hexdigest()
        else:
            result = stream.read(limit + 1)
        require(stream.tell() == info.st_size and _identity(os.fstat(stream.fileno())) == _identity(info)
                and _identity(path.lstat()) == _identity(info), 'Local file changed during review')
    check_deadline(deadline)
    return result, _identity(info)


def _reference(row, root):
    require(isinstance(row, dict) and row.keys() == REFERENCE_FIELDS and row['authorized'] is True,
            'An affirmatively authorized benchmark record is required')
    identity = _reference_id(_url(row['url']))
    _url(row['selection_evidence_url'])
    require(isinstance(row['selection_rationale'], str) and 12 <= len(row['selection_rationale'].strip()) <= 1200,
            'Selection rationale required')
    selected = row['selected_at']
    require(isinstance(selected, str) and len(selected) <= 45 and 'T' in selected
            and datetime.fromisoformat(selected).utcoffset() is not None, 'Selection timestamp required')
    require(isinstance(row['sha256'], str) and SHA.fullmatch(row['sha256']), 'Exact reference hash required')
    location = row['path']
    require(isinstance(location, str) and 0 < len(location) <= 4096 and '://' not in location, 'Local MP4 path required')
    path = root / location
    require('..' not in path.parts and path.suffix.lower() == '.mp4', 'Local MP4 path required')
    return identity, path


def _fraction(seconds, duration):
    require(type(seconds) in (int, float) and 0 <= seconds <= duration, 'Invalid temporal diagnostic')
    return seconds / duration


def _signals(signal):
    media, watcher, listener = (signal[key] for key in ('media', 'watcher', 'listener'))
    duration, width, height = (media[key] for key in ('duration_seconds', 'width', 'height'))
    require(type(duration) in (int, float) and 0 < duration <= 3600
            and type(width) is int and type(height) is int and width > 0 and height > 0, 'Invalid media diagnostic')
    orientation = 'landscape' if width > height else 'portrait' if width < height else 'square'
    values = {'duration_seconds': duration, 'orientation': orientation,
              'black_fraction': _fraction(watcher['black_seconds'], duration),
              'frozen_fraction': _fraction(watcher['frozen_seconds'], duration),
              'silence_fraction': _fraction(listener['silence_seconds'], duration)}
    for name in ('peak_dbfs', 'mean_dbfs'):
        value = listener[name]
        require(type(value) in (int, float) and math.isfinite(value), 'Finite audio diagnostic required')
        values[name] = value
    return values


def compare_benchmarks(candidate_sha256, candidate_signals, *, scan, deadline):
    """Run the caller's bounded local scanner against immutable reference bytes."""
    result = {'status': 'BLOCKED', 'candidate_sha256': candidate_sha256, 'comparisons': [],
              'reason': 'BENCHMARK_MANIFEST_UNCONFIGURED', 'publication_enabled': False,
              'paid_generation_enabled': False, 'full_av_review': False,
              'reference_selection_independently_verified': False,
              'scope': 'Technical signal differences only. Creative perception and competitor rank are unverified.'}
    configured = os.environ.get('CYZOR_REVIEW_BENCHMARKS')
    if not configured:
        return result
    try:
        require(isinstance(candidate_sha256, str) and SHA.fullmatch(candidate_sha256), 'Exact candidate hash required')
        manifest = Path(configured)
        require(manifest.is_absolute() and '..' not in manifest.parts, 'Absolute manifest required')
        raw, token = _read(manifest, MANIFEST_LIMIT, media=False, deadline=deadline)
        plan = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        require(isinstance(plan, dict) and plan.keys() in ({'schema_version', 'references'},
                                                            {'schema_version', 'reference_sets'})
                and type(plan['schema_version']) is int and plan['schema_version'] == 1,
                'Invalid benchmark manifest fields')
        candidate = _signals(candidate_signals)
        orientation = candidate['orientation']
        if 'reference_sets' in plan:
            sets = plan['reference_sets']
            require(isinstance(sets, dict) and sets and sets.keys() <= FORMATS
                    and all(isinstance(pair, list) and len(pair) == 2 for pair in sets.values()),
                    'Exactly two benchmark references per format required')
            if orientation not in sets:
                return {**result, 'reason': 'BENCHMARK_FORMAT_UNCONFIGURED', 'reference_format': orientation}
            rows = sets[orientation]
        else:
            rows = plan['references']
            require(isinstance(rows, list) and len(rows) == 2, 'Exactly two benchmark references required')
        inputs = [_reference(row, manifest.parent) for row in rows]
        require(len({identity for identity, _ in inputs}) == 2
                and len({candidate_sha256, *(row['sha256'] for row in rows)}) == 3,
                'References must have distinct media and identities')
        sources = [_read(path, MEDIA_LIMIT, media=True, deadline=deadline) for _, path in inputs]
        require(all(row['sha256'] == media_hash for row, (media_hash, _) in zip(rows, sources)),
                'Reference bytes differ from the selected digest')
        comparisons = []
        for row, (_, path) in zip(rows, inputs):
            check_deadline(deadline)
            reference = _signals(scan(path, deadline=deadline))
            require(orientation == reference['orientation'], 'Incompatible reference orientation')
            deltas = {key: candidate[key] - reference[key] for key in reference if key != 'orientation'}
            require(all(math.isfinite(delta) for delta in deltas.values()), 'Invalid comparison difference')
            comparisons.append({key: row[key] for key in REFERENCE_FIELDS - {'path', 'authorized'}} | {
                'reference_signals': reference,
                'candidate_minus_reference': deltas,
            })
        require(all(_read(path, MEDIA_LIMIT, media=True, deadline=deadline) == before
                    for (_, path), before in zip(inputs, sources)), 'Reference bytes changed during comparison')
        require(_read(manifest, MANIFEST_LIMIT, media=False, deadline=deadline) == (raw, token), 'Manifest changed during comparison')
        result.update(status='TECHNICAL_COMPARISON_COMPLETE', reason=None, reference_format=orientation,
                      manifest_sha256=hashlib.sha256(raw).hexdigest(), comparisons=comparisons)
    except (TimeoutError, TimeoutExpired):
        result['reason'] = 'BENCHMARK_COMPARISON_TIMED_OUT'
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RuntimeError, SubprocessError):
        result['reason'] = 'BENCHMARK_INPUT_OR_SCAN_INVALID'
    return result
