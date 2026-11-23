"""Bounded offline signals and review handoff for each new, unpublished video."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

from integrations.content_control.cycle_package import inspect_media, run
from integrations.content_control.review_package import check_deadline, digest, require


def _filter_log(log, name):
    return '\n'.join(re.findall(rf'^\[(?:Parsed_)?{name}(?:_\d+)? @ 0x[\da-fA-F]+\] (.+)$', log, re.M))


def _intervals(log, start_key, end_key, duration):
    pattern = rf'\b({start_key}|{end_key})\s*:\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)'
    start = None
    intervals = []
    for key, raw in re.findall(pattern, log):
        stamp = max(0, min(duration, float(raw)))
        if key == start_key:
            start = stamp
        elif start is not None:
            if stamp > start:
                intervals.append([start, stamp])
            start = None
    if start is not None and duration > start:
        intervals.append([start, duration])
    return intervals


def _seconds(intervals):
    return round(sum(end - start for start, end in intervals), 6)


def _level(log, key):
    match = re.search(rf'\b{key}_volume:\s*(-?\d+(?:\.\d+)?) dB', log)
    require(match is not None, 'Audio-level evidence missing')
    return float(match[1])


def scan_media(path, *, deadline, media=None):
    """Scan the complete picture and primary audio tracks without network or inference."""
    media = inspect_media(path, deadline=deadline, decode=False) if media is None else media
    duration = media['duration_seconds']
    log = run(['ffmpeg', '-hide_banner', '-nostdin', '-nostats', '-loglevel', 'info', '-xerror',
               '-protocol_whitelist', 'file,pipe', '-f', 'mov', '-enable_drefs', '0',
               '-use_absolute_path', '0', '-threads', '2', '-i', str(path), '-map', '0:v:0', '-map', '0:a:0',
               '-filter_threads', '1', '-threads', '2',
               '-vf', 'blackdetect=d=0.25:pix_th=0.10,freezedetect=n=-50dB:d=1.5',
               '-af', 'silencedetect=n=-45dB:d=0.6,volumedetect', '-f', 'null', '-'],
              deadline=deadline, stderr=True).decode('utf-8', 'replace')
    black = _intervals(_filter_log(log, 'blackdetect'), 'black_start', 'black_end', duration)
    frozen = _intervals(_filter_log(log, 'freezedetect'), 'freeze_start', 'freeze_end', duration)
    silence = _intervals(_filter_log(log, 'silencedetect'), 'silence_start', 'silence_end', duration)
    levels = _filter_log(log, 'volumedetect')
    return {'media': {key: media[key] for key in ('width', 'height', 'duration_seconds')},
            'watcher': {'status': 'SIGNALS_MEASURED', 'black_intervals': black, 'frozen_intervals': frozen,
                        'black_seconds': _seconds(black), 'frozen_seconds': _seconds(frozen)},
            'listener': {'status': 'SIGNALS_MEASURED', 'silence_intervals': silence,
                         'silence_seconds': _seconds(silence), 'peak_dbfs': _level(levels, 'max'),
                         'mean_dbfs': _level(levels, 'mean')}}


def write_automated_review(directory, candidate, captions, *, deadline, media):
    from integrations.content_control.cycle_av_benchmarks import compare_benchmarks

    directory = Path(directory)
    video, sidecar = directory / 'video.mp4', directory / 'captions.vtt'
    # Keep room on the parent budget for thumbnails, the receipt and the review ZIP.
    now = time.monotonic()
    review_deadline = now + (120 if deadline is None else min(120, (deadline - now) / 2))
    try:
        signals = scan_media(video, deadline=review_deadline, media=media)
    except (OSError, ValueError, RuntimeError, TimeoutError):
        signals = {'watcher': {'status': 'BLOCKED'}, 'listener': {'status': 'BLOCKED'}}
        comparison = {'status': 'BLOCKED', 'reason': 'Candidate signal scan unavailable'}
    else:
        comparison = compare_benchmarks(candidate, signals, scan=scan_media, deadline=review_deadline)
    watch, listen = signals['watcher'], signals['listener']
    attention = [key for key, role in (('black_intervals', watch), ('frozen_intervals', watch),
                                      ('silence_intervals', listen)) if role.get(key)]
    check_deadline(deadline)
    require(digest(video, deadline) == candidate and digest(sidecar, deadline) == captions,
            'Candidate or captions changed during automated review')
    receipt = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
               'candidate_sha256': candidate, 'caption_sha256': captions,
               **signals, 'competitor_comparison': comparison,
               'analysis': {'status': 'DIAGNOSTICS_AVAILABLE' if watch['status'] == 'SIGNALS_MEASURED' else 'BLOCKED',
                            'intervals_to_review': attention},
               'reviewer': {'status': 'FULL_REVIEW_REQUIRED',
                            'picture_checks': ['staging', 'animation', 'readability', 'pacing', 'payoff'],
                            'audio_checks': ['naturalness', 'pronunciation', 'character voices', 'music and effects', 'mix'],
                            'comparison_checks': ['hook', 'storytelling', 'visual pacing', 'voice and mix', 'originality']},
               'full_audiovisual_review_verified': False, 'competitor_audiovisual_comparison_verified': False,
               'publication_enabled': False, 'paid_generation_enabled': False, 'production_approved': False}
    with (directory / 'automated-review.json').open('x') as out:
        json.dump(receipt, out, indent=2, sort_keys=True, allow_nan=False)
        out.write('\n')
    return receipt
