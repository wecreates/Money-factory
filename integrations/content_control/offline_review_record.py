"""Replay an exported private-review record without granting creative approval."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from integrations.content_control.review_package import SHA, no_symlinks, require


MAX_RECORD_BYTES = 1024 * 1024
FALSE_SAFETY_FLAGS = (
    'independent_acceptance',
    'full_av_acceptance',
    'production_approved',
    'publication_enabled',
    'paid_generation_enabled',
    'competitor_comparison_included',
    'physical_phone_verified',
)
FINDING_CATEGORIES = {
    'pronunciation', 'naturalness', 'character_voice', 'intelligibility',
    'timing', 'music_sfx', 'mix', 'caption_sync', 'movement_staging',
    'typography_legibility', 'transition_payoff',
}


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _read_record(path):
    path = Path(path).absolute()
    no_symlinks(path)
    require(path.is_file(), 'Regular review record required')
    with path.open('rb') as stream:
        raw = stream.read(MAX_RECORD_BYTES + 1)
    require(0 < len(raw) <= MAX_RECORD_BYTES,
            'Review record is empty or exceeds the size limit')
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('Valid UTF-8 JSON review record required') from error
    require(isinstance(value, dict), 'Review record must be an object')
    return value


def validate_record(record, *, video_sha256, caption_sha256):
    """Validate an in-memory record without granting creative approval."""
    require(isinstance(video_sha256, str) and SHA.fullmatch(video_sha256),
            'Expected video SHA-256 required')
    require(isinstance(caption_sha256, str) and SHA.fullmatch(caption_sha256),
            'Expected caption SHA-256 required')
    require(isinstance(record, dict), 'Review record must be an object')
    require(record.get('schema_version') == 2, 'Review record schema version 2 required')
    require(record.get('candidate_sha256') == video_sha256,
            'Review record candidate identity mismatch')
    require(record.get('caption_sha256') == caption_sha256,
            'Review record caption identity mismatch')

    digest = record.get('record_sha256')
    require(isinstance(digest, str) and SHA.fullmatch(digest),
            'Review record SHA-256 required')
    unsigned = dict(record)
    unsigned.pop('record_sha256', None)
    require(hashlib.sha256(canonical_bytes(unsigned)).hexdigest() == digest,
            'Review record SHA-256 mismatch')

    for key in FALSE_SAFETY_FLAGS:
        require(record.get(key) is False, f'{key} must remain false')

    machine = record.get('machine_observation')
    reviewer = record.get('reviewer_attestation')
    require(isinstance(machine, dict), 'Machine observation object required')
    require(isinstance(reviewer, dict), 'Reviewer attestation object required')
    require(machine.get('identity_verified') is True,
            'Machine observation must retain verified exact identities')
    require(isinstance(machine.get('events'), list), 'Playback event list required')
    require(isinstance(machine.get('playback_intervals'), list),
            'Playback intervals required')
    duration = machine.get('browser_duration_seconds')
    require(isinstance(duration, (int, float)) and not isinstance(duration, bool)
            and math.isfinite(duration) and duration > 0,
            'Finite positive browser duration required')
    intervals = machine['playback_intervals']
    for interval in intervals:
        require(isinstance(interval, list) and len(interval) == 2,
                'Playback interval must contain start and end')
        start, end = interval
        require(all(isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value) for value in interval)
                and 0 <= start <= end <= duration + .25,
                'Playback interval is invalid or outside the video')

    require(isinstance(reviewer.get('reviewer'), str) and reviewer['reviewer'].strip(),
            'Reviewer label required')
    require(isinstance(reviewer.get('device_environment'), str)
            and reviewer['device_environment'].strip(),
            'Reviewer device and environment required')
    roles = reviewer.get('roles')
    require(isinstance(roles, list) and roles
            and all(isinstance(role, str) for role in roles)
            and len(roles) == len(set(roles))
            and set(roles) <= {'watcher', 'listener', 'reviewer'},
            'Valid unique reviewer roles required')
    require(reviewer.get('review_round') in {'initial', 'post_repair'},
            'Valid review round required')
    require(reviewer.get('audio_output') in {'headphones', 'speakers', 'phone'},
            'Valid audio output required')
    require(reviewer.get('disposition') in
            {'no_blocker_seen', 'repair_required', 'blocked'},
            'Valid review disposition required')
    require(isinstance(reviewer.get('summary'), str) and reviewer['summary'].strip(),
            'Reviewer summary required')

    parent = record.get('parent_video_sha256')
    supersedes = record.get('supersedes_record_sha256')
    if reviewer['review_round'] == 'post_repair':
        require(isinstance(parent, str) and SHA.fullmatch(parent)
                and parent != video_sha256,
                'Post-repair review requires a different parent video SHA-256')
        require(isinstance(supersedes, str) and SHA.fullmatch(supersedes),
                'Post-repair review requires a superseded record SHA-256')
    else:
        require(parent in {None, ''} and supersedes in {None, ''},
                'Initial review must not claim revision lineage')

    findings = record.get('findings')
    require(isinstance(findings, list), 'Findings list required')
    has_blocker = False
    for finding in findings:
        require(isinstance(finding, dict), 'Each finding must be an object')
        start = finding.get('start_seconds')
        end = finding.get('end_seconds')
        require(isinstance(start, (int, float)) and not isinstance(start, bool)
                and isinstance(end, (int, float)) and not isinstance(end, bool)
                and math.isfinite(start) and math.isfinite(end)
                and 0 <= start <= end <= duration + .25,
                'Finding interval is invalid or outside the video')
        require(finding.get('category') in FINDING_CATEGORIES,
                'Finding category is invalid')
        require(finding.get('severity') in {'note', 'blocker'},
                'Finding severity is invalid')
        require(isinstance(finding.get('observation'), str)
                and finding['observation'].strip(), 'Finding observation required')
        require(finding.get('resolution_state') in {'open', 'resolved', 'not_applicable'},
                'Finding resolution state is invalid')
        if finding['severity'] == 'blocker':
            require(isinstance(finding.get('requested_repair'), str)
                    and finding['requested_repair'].strip(),
                    'Blocker finding requires a requested repair')
        has_blocker = has_blocker or finding['severity'] == 'blocker'

    if has_blocker:
        require(reviewer['disposition'] != 'no_blocker_seen',
                'A blocker finding requires repair or blocked disposition')

    complete = (machine.get('natural_pass_complete') is True
                and reviewer.get('watched_every_interval') is True
                and reviewer.get('listened_every_interval') is True
                and reviewer.get('checked_voice') is True
                and reviewer.get('checked_mix') is True
                and reviewer.get('checked_picture_and_captions') is True)
    if complete:
        require(isinstance(machine.get('started_at'), str) and machine['started_at'].strip()
                and isinstance(machine.get('ended_at'), str) and machine['ended_at'].strip(),
                'Complete review requires playback start and end timestamps')
        require(intervals, 'Complete review requires playback intervals')
        ordered = sorted(intervals)
        require(ordered[0][0] <= .25 and ordered[-1][1] >= duration - .25,
                'Complete review intervals must cover the video endpoints')
        for before, after in zip(ordered, ordered[1:]):
            require(after[0] <= before[1] + .25,
                    'Complete review intervals contain a playback gap')
        events = machine['events']
        require(all(isinstance(event, dict) and isinstance(event.get('type'), str)
                    for event in events), 'Playback events must be typed objects')
        start_indexes = [index for index, event in enumerate(events)
                         if event['type'] == 'natural_pass_started'
                         and event.get('valid') is True]
        end_indexes = [index for index, event in enumerate(events)
                       if event['type'] == 'playback_ended'
                       and event.get('natural_pass_complete') is True]
        require(start_indexes,
                'Complete review requires a valid natural-pass start event')
        require(end_indexes,
                'Complete review requires a terminal natural-pass event')
        require(any(start < end for start in start_indexes for end in end_indexes),
                'Complete review requires natural-pass start before terminal end')
        require(not any(event['type'] == 'pass_invalidated' for event in events),
                'Complete review cannot contain an invalidated pass')
        require(machine.get('invalidations') == [],
                'Complete review cannot retain pass invalidations')
    require(record.get('review_coverage_complete') is complete,
            'Review coverage flag does not match the retained evidence')
    expected_status = 'FULL_REVIEW_RECORDED' if complete else 'OBSERVATIONS_RECORDED'
    require(record.get('status') == expected_status,
            'Review status does not match the retained evidence')
    require(record.get('reviewer_attested_full_watch_listen') is
            (reviewer.get('watched_every_interval') is True
             and reviewer.get('listened_every_interval') is True),
            'Watch/listen attestation flag does not match the retained evidence')

    return {
        'status': record['status'],
        'candidate_sha256': video_sha256,
        'caption_sha256': caption_sha256,
        'record_sha256': digest,
        'review_coverage_complete': complete,
        'independent_acceptance': False,
    }


def verify_record(path, *, video_sha256, caption_sha256):
    """Read and validate a record's integrity, identities, and acceptance scope."""
    return validate_record(_read_record(path), video_sha256=video_sha256,
                           caption_sha256=caption_sha256)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True)
    parser.add_argument('--video-sha256', required=True)
    parser.add_argument('--caption-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(verify_record(args.record, video_sha256=args.video_sha256,
                                   caption_sha256=args.caption_sha256), sort_keys=True))
