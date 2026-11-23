"""Bounded offline signals and review handoff for each new, unpublished video."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

from integrations.content_control.cycle_package import inspect_media, run
from integrations.content_control.review_package import SHA, check_deadline, digest, no_symlinks, require


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


def write_automated_review(directory, candidate, captions, *, deadline, media=None, output=None):
    from integrations.content_control.cycle_av_benchmarks import compare_benchmarks

    directory = Path(directory)
    video, sidecar = directory / 'video.mp4', directory / 'captions.vtt'
    output = directory / 'automated-review.json' if output is None else Path(output)
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
    with output.open('x') as out:
        json.dump(receipt, out, indent=2, sort_keys=True, allow_nan=False)
        out.write('\n')
    return receipt


def automated_review_command(review_dir, output_path, producer_receipt, deadline):
    return [sys.executable, '-m', 'integrations.content_control.cycle_av_review',
            '--input', str(Path(review_dir).absolute()), '--output', str(Path(output_path).absolute()),
            '--candidate-sha256', producer_receipt['candidate_sha256'],
            '--caption-sha256', producer_receipt['artifacts_sha256']['captions.vtt'],
            '--timeout', str(min(1800, deadline - time.monotonic()))]


def read_automated_review(path, candidate_sha256, caption_sha256, *, sync=False):
    path = Path(path).absolute()
    no_symlinks(path)
    limit = 1024 * 1024
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit, 'Missing or oversized automated review')
        raw = stream.read(limit + 1)
        require(len(raw) == info.st_size, 'Automated review changed during read')
        if sync:
            os.fsync(stream.fileno())
    report = json.loads(raw)
    require(isinstance(report, dict) and type(report.get('schema_version')) is int and report['schema_version'] == 1
            and report.get('candidate_sha256') == candidate_sha256 and report.get('caption_sha256') == caption_sha256
            and all(report.get(flag) is False for flag in ('publication_enabled', 'paid_generation_enabled',
                    'production_approved', 'full_audiovisual_review_verified', 'competitor_audiovisual_comparison_verified')),
            'Automated review does not match the unpublished candidate and captions')
    stages = {'watcher': ('SIGNALS_MEASURED', 'BLOCKED'), 'listener': ('SIGNALS_MEASURED', 'BLOCKED'),
              'analysis': ('DIAGNOSTICS_AVAILABLE', 'BLOCKED'),
              'competitor_comparison': ('TECHNICAL_COMPARISON_COMPLETE', 'BLOCKED'),
              'reviewer': ('FULL_REVIEW_REQUIRED',)}
    for name, statuses in stages.items():
        stage = report.get(name)
        require(isinstance(stage, dict) and stage.get('status') in statuses, 'Missing or invalid automated review stage: ' + name)
    return raw


def verify_automated_review(path, expected_sha256, candidate_sha256, caption_sha256):
    raw = read_automated_review(path, candidate_sha256, caption_sha256)
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'Automated review identity changed')
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--caption-sha256', required=True)
    parser.add_argument('--timeout', type=float, required=True)
    args = parser.parse_args()
    require(math.isfinite(args.timeout) and 0 < args.timeout <= 1800, 'Automated review budget unavailable')
    require(all(os.environ.get(flag, 'false').lower() == 'false'
                for flag in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')), 'Publishing and paid generation must remain disabled')
    require(SHA.fullmatch(args.candidate_sha256) and SHA.fullmatch(args.caption_sha256), 'Exact media and caption hashes required')
    root, output = Path(os.path.abspath(args.input)), Path(os.path.abspath(args.output))
    no_symlinks(output)
    require(not output.is_relative_to(root) and not output.exists(), 'Fresh report outside the source packet required')
    deadline = time.monotonic() + args.timeout
    for path, expected in ((root / 'video.mp4', args.candidate_sha256), (root / 'captions.vtt', args.caption_sha256)):
        no_symlinks(path)
        require(path.is_file() and digest(path, deadline) == expected, 'Source file differs from verified candidate packet')
    write_automated_review(root, args.candidate_sha256, args.caption_sha256, deadline=deadline, output=output)


if __name__ == '__main__':
    main()
