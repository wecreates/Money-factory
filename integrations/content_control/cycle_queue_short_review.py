"""Bind queue-produced Short findings and caption revision handoffs.

This module records repair findings, not approval.  It replays the durable queue
consumer before binding the exact derivative video, captions, authored selection,
and parent cycle.  A caption revision writes a new sidecar plus an immutable
handoff; it never changes the video, voices, queue, publishing, or paid settings.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil

from integrations.content_control.cycle_caption_revision import correct_vtt
from integrations.content_control.cycle_editorial import _text, _timestamp
from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.cycle_queue_short_attestation import (
    verify_recorded_value,
)
from integrations.content_control.cycle_queue_short import verify_consumed_short
from integrations.content_control.cycle_short import COMPACT_STYLE, SAFE_CAPTION_STYLE
from integrations.content_control.review_package import digest, no_symlinks, require


FLAGS = {key: False for key in (
    'publication_enabled', 'paid_generation_enabled', 'production_approved',
    'full_av_review', 'production_ready')}
FINDING_CHECKS = frozenset({
    'caption_accuracy', 'caption_readability', 'voice_and_sound',
    'visual_storytelling', 'pacing', 'creative_coherence',
    'reference_comparison', 'phone_playback',
})
MAX_JSON = 64 * 1024
ATTESTATION_JSON_LIMIT = 1024 * 1024
RECORDED_REVIEW_LIMIT = 2 * 1024 * 1024
REVIEW_SCOPE = ('Exact queue Short repair findings and identities only; no complete '
                'watch/listen, competitor, phone, creative, or publishing acceptance.')
ATTESTATION_REVIEW_SCOPE = (
    'Repair findings derived from a supplied complete-duration direct Short watch/listen '
    'attestation; the observations are not independently verified and do not grant creative, '
    'competitor, phone, production, publishing, or paid-generation acceptance.')
REVISION_SCOPE = ('Caption-only revision handoff for the exact sidecar derivative; '
                  'not a revised consumable Short and not audiovisual acceptance.')
# The pre-safe-area recorder only recognized sidecar and the exact compact burn.
PRE_SAFE_AREA_REVIEW_TOOL_SHA256 = '904910540c80840cddb8107ce206554c053933f56abfc3a80fd34852b348a91a'
COMPACT_OVERLAY = {
    'style': COMPACT_STYLE,
    'audio_mode': 'stream_copy_from_excerpt',
    'scope': 'Burned rebased sidecar into a private phone-size review derivative.',
}
# Match the safe-area exporter receipt exactly after durable media replay.
SAFE_AREA_OVERLAY = {
    **COMPACT_OVERLAY,
    'style': SAFE_CAPTION_STYLE,
    'picture_layout': {
        'mode': 'scaled_picture_safe_caption_area_v1',
        'source_scale_percent': 90,
        'scaled_picture_size': [648, 1152],
        'canvas_size': [720, 1280],
        'picture_offset': [36, 0],
        'background_rgb': '#f7f1e6',
        'caption_bottom_clearance_target_pixels': 125,
    },
}

ATTESTATION_FINDING_MAP = {
    'watcher.picture_continuity': 'visual_storytelling',
    'watcher.caption_readability': 'caption_readability',
    'watcher.audio_visual_sync': 'voice_and_sound',
    'watcher.pacing_and_transitions': 'pacing',
    'watcher.creative_coherence': 'creative_coherence',
    'listener.naturalness': 'voice_and_sound',
    'listener.pronunciation': 'voice_and_sound',
    'listener.character_consistency': 'voice_and_sound',
    'listener.music_and_sfx': 'voice_and_sound',
    'listener.transitions': 'voice_and_sound',
    'listener.mix_balance': 'voice_and_sound',
}


def _regular(path, limit=MAX_JSON):
    no_symlinks(path)
    require(path.is_file() and path.stat().st_size <= limit,
            'Missing or oversized input: ' + path.name)
    return path


def _read_json(path, limit=MAX_JSON):
    raw = _regular(path, limit).read_bytes()
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('UTF-8 JSON object required: ' + path.name) from error
    require(isinstance(value, dict), 'JSON object required: ' + path.name)
    return raw, value


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                               allow_nan=False) + '\n')


def _snapshot(queue_root, job_id, short_dir):
    short_dir = Path(os.path.abspath(short_dir))
    no_symlinks(short_dir)
    receipt = verify_consumed_short(queue_root, job_id, short_dir)
    queue_short = short_dir / 'queue-short.json'
    short = short_dir / 'short.json'
    captions = short_dir / 'captions.vtt'
    queue_raw, queue_receipt = _read_json(queue_short)
    short_raw, short_receipt = _read_json(short)
    caption_bytes = _regular(captions, 1024 * 1024).read_bytes()
    require(queue_receipt == receipt,
            'Queue Short receipt changed after verification')
    artifacts = receipt.get('artifacts_sha256')
    require(isinstance(artifacts, dict)
            and hashlib.sha256(short_raw).hexdigest() == artifacts.get('short.json')
            and hashlib.sha256(caption_bytes).hexdigest() == artifacts.get('captions.vtt'),
            'Re-read Short artifacts differ from verified receipt')
    current_artifacts = {}
    for name in sorted(artifacts):
        path = short_dir / name
        no_symlinks(path)
        require(path.is_file() and not path.is_symlink(),
                'Verified Short artifact became unavailable: ' + name)
        current_artifacts[name] = digest(path)
    require(current_artifacts == artifacts,
            'Re-read Short artifact map differs from verified receipt')
    mode = short_receipt.get('preview_caption_mode')
    safe_area = False
    if mode == 'sidecar':
        require('caption_overlay' not in short_receipt,
                'Sidecar Short cannot carry a burned-caption overlay')
    elif mode == 'burned':
        overlay = json.dumps(short_receipt.get('caption_overlay'), sort_keys=True, allow_nan=False)
        safe_area = overlay == json.dumps(SAFE_AREA_OVERLAY, sort_keys=True)
        require(safe_area or overlay == json.dumps(COMPACT_OVERLAY, sort_keys=True),
                'Burned-caption Short overlay contract is invalid')
    else:
        raise ValueError('Short caption presentation mode is invalid')
    result = {
        'receipt': receipt,
        'queue_short_sha256': hashlib.sha256(queue_raw).hexdigest(),
        'short_receipt_sha256': hashlib.sha256(short_raw).hexdigest(),
        'caption_bytes_sha256': hashlib.sha256(caption_bytes).hexdigest(),
        'caption_bytes': caption_bytes,
        'preview_caption_mode': mode,
        'uses_safe_caption_area': safe_area,
        'artifacts_sha256': current_artifacts,
    }
    require(verify_consumed_short(queue_root, job_id, short_dir) == receipt
            and digest(queue_short) == result['queue_short_sha256']
            and digest(short) == result['short_receipt_sha256']
            and digest(captions) == result['caption_bytes_sha256']
            and all(digest(short_dir / name) == expected
                    for name, expected in current_artifacts.items()),
            'Durable Short changed during snapshot')
    return result


def _known_review_tool(value, snapshot):
    if value == PRE_SAFE_AREA_REVIEW_TOOL_SHA256:
        return not snapshot['uses_safe_caption_area']
    return value == digest(Path(__file__))


def _findings(value):
    require(isinstance(value, list) and 1 <= len(value) <= 50,
            'One to 50 repair findings required')
    normalized = []
    for item in value:
        require(isinstance(item, dict)
                and set(item) == {'check', 'evidence', 'action'},
                'Exact check/evidence/action finding fields required')
        check = item['check']
        require(check in FINDING_CHECKS, 'Unsupported Short review check')
        normalized.append({
            'check': check,
            'evidence': _text(item['evidence'], 'finding.evidence', 4000,
                              minimum=12),
            'action': _text(item['action'], 'finding.action', 4000,
                            minimum=12),
        })
    return normalized


def _review_submission(value, snapshot):
    fields = {'candidate_sha256', 'caption_sha256', 'reviewer', 'reviewed_at',
              'queue_short_sha256', 'short_receipt_sha256',
              'preview_caption_mode', 'basis', 'findings'}
    require(isinstance(value, dict) and set(value) == fields,
            'Exact Short repair-review fields required')
    receipt = snapshot['receipt']
    require(value['candidate_sha256'] == receipt.get('candidate_sha256')
            and value['caption_sha256'] == receipt.get('caption_sha256')
            and value['queue_short_sha256'] == snapshot['queue_short_sha256']
            and value['short_receipt_sha256'] == snapshot['short_receipt_sha256']
            and value['preview_caption_mode'] == snapshot['preview_caption_mode'],
            'Short review targets different derivative identities or caption mode')
    require(value['basis'] == 'supplied_repair_findings_not_acceptance',
            'Repair-only review basis required')
    reviewer = _text(value['reviewer'], 'reviewer', 200)
    reviewed_at = _timestamp(value['reviewed_at'], 'reviewed_at')
    require(datetime.fromisoformat(reviewed_at) >=
            datetime.fromisoformat(receipt['finished_at']),
            'Short review predates completed derivative')
    return {
        'candidate_sha256': value['candidate_sha256'],
        'caption_sha256': value['caption_sha256'],
        'queue_short_sha256': value['queue_short_sha256'],
        'short_receipt_sha256': value['short_receipt_sha256'],
        'preview_caption_mode': value['preview_caption_mode'],
        'reviewer': reviewer,
        'reviewed_at': reviewed_at,
        'basis': value['basis'],
        'findings': _findings(value['findings']),
    }


def _bound_source(snapshot):
    receipt = snapshot['receipt']
    require(snapshot['caption_bytes_sha256'] == receipt.get('caption_sha256'),
            'Short caption bytes differ from consumer receipt')
    return {
        'job_id': receipt['job_id'],
        'candidate_sha256': receipt['candidate_sha256'],
        'caption_sha256': receipt['caption_sha256'],
        'queue_short_sha256': snapshot['queue_short_sha256'],
        'short_receipt_sha256': snapshot['short_receipt_sha256'],
        'parent_candidate_sha256': receipt['parent_candidate_sha256'],
        'parent_cycle_sha256': receipt['parent_cycle_sha256'],
        'selection': receipt['selection'],
        'encoded_streams_sha256': receipt['encoded_streams_sha256'],
        'decoded_picture_sha256': receipt['decoded_picture_sha256'],
        'preview_caption_mode': snapshot['preview_caption_mode'],
    }


def record_short_review(queue_root, job_id, short_dir, review_path, output):
    """Record exact repair findings for a durable queue-produced Short."""
    require(all(os.environ.get(key, 'false').lower() == 'false'
                for key in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    queue_root = Path(os.path.abspath(queue_root))
    short_dir = Path(os.path.abspath(short_dir))
    review_path = Path(os.path.abspath(review_path))
    output = Path(os.path.abspath(output))
    for path in (queue_root, short_dir, review_path, output):
        no_symlinks(path)
    require(not output.exists() and output != review_path
            and not output.is_relative_to(short_dir)
            and not output.is_relative_to(queue_root),
            'Fresh review output outside the Short and queue required')
    raw, submitted = _read_json(review_path)
    snapshot = _snapshot(queue_root, job_id, short_dir)
    review = _review_submission(submitted, snapshot)
    result = {
        'schema_version': 1,
        'status': 'REVISION_REQUIRED',
        **FLAGS,
        **_bound_source(snapshot),
        'reviewer': review['reviewer'],
        'reviewed_at': review['reviewed_at'],
        'basis': review['basis'],
        'findings': review['findings'],
        'submitted_review_sha256': hashlib.sha256(raw).hexdigest(),
        'submitted_review_json': raw.decode('utf-8'),
        'human_av_acceptance_recorded': False,
        'phone_playback_verified': False,
        'independent_verification': False,
        'tool_sha256': digest(Path(__file__)),
        'scope': REVIEW_SCOPE,
    }
    require(_snapshot(queue_root, job_id, short_dir) == snapshot
            and _regular(review_path).read_bytes() == raw,
            'Short or review input changed while recording')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True,
                  allow_nan=False)
        stream.write('\n')
    return result


def _attestation_findings(attestation):
    feedback = attestation.get('feedback')
    require(isinstance(feedback, list) and feedback,
            'A failed Short watch/listen check is required before repair routing')
    findings = []
    for item in feedback:
        require(isinstance(item, dict) and set(item) == {'check', 'action'},
                'Exact attestation feedback fields required')
        source_check = item['check']
        mapped = ATTESTATION_FINDING_MAP.get(source_check)
        require(mapped is not None, 'Unsupported Short attestation check')
        role, check = source_check.split('.', 1)
        section = attestation.get(role + '_review')
        require(isinstance(section, dict), 'Recorded Short ' + role + ' review required')
        checks = section.get('checks')
        require(isinstance(checks, dict) and isinstance(checks.get(check), dict),
                'Recorded Short check evidence required')
        evidence = checks[check].get('evidence')
        findings.append({
            'check': mapped,
            'evidence': _text(evidence, source_check + '.evidence', 4000, minimum=12),
            'action': _text(item['action'], source_check + '.action', 4000, minimum=12),
        })
    return _findings(findings)


def _attestation_review(attestation, snapshot):
    watcher = attestation['watcher_review']
    listener = attestation['listener_review']
    names = [watcher['watcher'], listener['listener']]
    reviewer = names[0] if names[0] == names[1] else 'Separate direct watcher and listener'
    reviewed_times = [_timestamp(watcher['watched_at'], 'watched_at'),
                      _timestamp(listener['listened_at'], 'listened_at')]
    reviewed_at = max(reviewed_times, key=datetime.fromisoformat)
    result = {
        **_bound_source(snapshot),
        'reviewer': _text(reviewer, 'reviewer', 200, minimum=1),
        'reviewed_at': _timestamp(reviewed_at, 'reviewed_at'),
        'basis': 'direct_watch_listen_attestation_repair_findings',
        'findings': _attestation_findings(attestation),
    }
    return result


def record_attestation_findings(queue_root, job_id, short_dir, attestation_path, output):
    """Route failed exact watch/listen checks into the Short repair path."""
    require(all(os.environ.get(key, 'false').lower() == 'false'
                for key in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    queue_root = Path(os.path.abspath(queue_root))
    short_dir = Path(os.path.abspath(short_dir))
    attestation_path = Path(os.path.abspath(attestation_path))
    output = Path(os.path.abspath(output))
    for path in (queue_root, short_dir, attestation_path, output):
        no_symlinks(path)
    require(not output.exists() and output != attestation_path
            and not output.is_relative_to(short_dir)
            and not output.is_relative_to(queue_root),
            'Fresh review output outside the Short and queue required')
    raw, attestation = _read_json(attestation_path, ATTESTATION_JSON_LIMIT)
    snapshot = _snapshot(queue_root, job_id, short_dir)
    verified = verify_recorded_value(queue_root, job_id, short_dir, attestation)
    require(verified.get('status') == 'REVISION_REQUIRED',
            'Only a failed Short watch/listen attestation requires repair routing')
    review = _attestation_review(verified, snapshot)
    feedback_sha = hashlib.sha256(json.dumps(
        verified['feedback'], sort_keys=True, separators=(',', ':'),
        allow_nan=False).encode()).hexdigest()
    result = {
        'schema_version': 2,
        'status': 'REVISION_REQUIRED',
        **FLAGS,
        **review,
        'source_attestation_sha256': hashlib.sha256(raw).hexdigest(),
        'source_attestation_feedback_sha256': feedback_sha,
        'source_attestation_json': raw.decode('utf-8'),
        'human_av_acceptance_recorded': False,
        'phone_playback_verified': False,
        'independent_verification': False,
        'tool_sha256': digest(Path(__file__)),
        'scope': ATTESTATION_REVIEW_SCOPE,
    }
    require(_snapshot(queue_root, job_id, short_dir) == snapshot
            and _regular(attestation_path, ATTESTATION_JSON_LIMIT).read_bytes() == raw,
            'Short or attestation changed while routing repair findings')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return result


def verify_recorded_short_review(queue_root, job_id, short_dir, recorded_review):
    """Replay a recorded repair review against the current durable derivative."""
    recorded_review = Path(os.path.abspath(recorded_review))
    _, value = _read_json(recorded_review, RECORDED_REVIEW_LIMIT)
    snapshot = _snapshot(queue_root, job_id, short_dir)
    source_fields = set(_bound_source(snapshot))
    legacy_required = ({'schema_version', 'status', *FLAGS, *source_fields,
                 'reviewer', 'reviewed_at', 'basis', 'findings',
                 'submitted_review_sha256', 'submitted_review_json',
                 'human_av_acceptance_recorded', 'phone_playback_verified',
                 'independent_verification', 'tool_sha256', 'scope'})
    attestation_required = ({'schema_version', 'status', *FLAGS, *source_fields,
                 'reviewer', 'reviewed_at', 'basis', 'findings',
                 'source_attestation_sha256', 'source_attestation_feedback_sha256',
                 'source_attestation_json', 'human_av_acceptance_recorded',
                 'phone_playback_verified', 'independent_verification',
                 'tool_sha256', 'scope'})
    version = value.get('schema_version')
    require(((version == 1 and set(value) == legacy_required)
             or (version == 2 and set(value) == attestation_required))
            and value.get('status') == 'REVISION_REQUIRED'
            and all(value.get(key) is False for key in FLAGS)
            and value.get('human_av_acceptance_recorded') is False
            and value.get('phone_playback_verified') is False
            and value.get('independent_verification') is False
            and _known_review_tool(value.get('tool_sha256'), snapshot)
            and value.get('scope') == (REVIEW_SCOPE if version == 1
                                       else ATTESTATION_REVIEW_SCOPE),
            'Recorded Short review scope or flags are invalid')
    if version == 1:
        raw_text = value.get('submitted_review_json')
        require(isinstance(raw_text, str)
                and hashlib.sha256(raw_text.encode()).hexdigest() ==
                    value.get('submitted_review_sha256'),
                'Recorded submitted review identity changed')
        try:
            submitted = json.loads(raw_text, object_pairs_hook=_pairs,
                                   parse_constant=_constant)
        except json.JSONDecodeError as error:
            raise ValueError('Recorded submitted review JSON is invalid') from error
        normalized = _review_submission(submitted, snapshot)
        expected = {
            **_bound_source(snapshot),
            'reviewer': normalized['reviewer'],
            'reviewed_at': normalized['reviewed_at'],
            'basis': normalized['basis'],
            'findings': normalized['findings'],
        }
    else:
        raw_text = value.get('source_attestation_json')
        require(isinstance(raw_text, str)
                and hashlib.sha256(raw_text.encode()).hexdigest() ==
                    value.get('source_attestation_sha256'),
                'Recorded source attestation identity changed')
        try:
            attestation = json.loads(raw_text, object_pairs_hook=_pairs,
                                     parse_constant=_constant)
        except json.JSONDecodeError as error:
            raise ValueError('Recorded source attestation JSON is invalid') from error
        verified = verify_recorded_value(queue_root, job_id, short_dir, attestation)
        require(verified.get('status') == 'REVISION_REQUIRED',
                'Recorded source attestation does not require repair')
        feedback_sha = hashlib.sha256(json.dumps(
            verified['feedback'], sort_keys=True, separators=(',', ':'),
            allow_nan=False).encode()).hexdigest()
        require(feedback_sha == value.get('source_attestation_feedback_sha256'),
                'Recorded source attestation feedback changed')
        expected = _attestation_review(verified, snapshot)
    require(all(value.get(key) == item for key, item in expected.items()),
            'Recorded Short review no longer binds the durable derivative')
    require(_snapshot(queue_root, job_id, short_dir) == snapshot,
            'Durable Short changed while verifying recorded review')
    return value


def prepare_caption_revision(queue_root, job_id, short_dir, recorded_review,
                             revision_path, output):
    """Write corrected sidecar captions plus a non-consumable revision handoff."""
    require(all(os.environ.get(key, 'false').lower() == 'false'
                for key in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    queue_root = Path(os.path.abspath(queue_root))
    short_dir = Path(os.path.abspath(short_dir))
    recorded_review = Path(os.path.abspath(recorded_review))
    revision_path = Path(os.path.abspath(revision_path))
    output = Path(os.path.abspath(output))
    for path in (queue_root, short_dir, recorded_review, revision_path, output):
        no_symlinks(path)
    require(not output.exists() and not output.is_relative_to(short_dir)
            and not output.is_relative_to(queue_root)
            and not recorded_review.is_relative_to(output)
            and not revision_path.is_relative_to(output),
            'Fresh caption revision output separate from inputs required')
    snapshot = _snapshot(queue_root, job_id, short_dir)
    receipt = snapshot['receipt']
    require(snapshot['preview_caption_mode'] == 'sidecar',
            'Burned-caption Short requires a fresh video render, not sidecar-only revision')
    recorded = verify_recorded_short_review(
        queue_root, job_id, short_dir, recorded_review)
    require(recorded.get('preview_caption_mode') == 'sidecar',
            'Recorded reviewer evidence does not bind a sidecar-caption Short')
    raw, submitted = _read_json(revision_path)
    fields = {'candidate_sha256', 'caption_sha256', 'recorded_review_sha256',
              'editor', 'rationale', 'caption_edits'}
    require(set(submitted) == fields,
            'Exact Short caption revision fields required')
    review_sha = digest(recorded_review)
    require(submitted['candidate_sha256'] == receipt['candidate_sha256']
            and submitted['caption_sha256'] == receipt['caption_sha256']
            and submitted['recorded_review_sha256'] == review_sha,
            'Short caption revision identity mismatch')
    require(any(item['check'] in ('caption_accuracy', 'caption_readability')
                for item in recorded['findings']),
            'Recorded caption finding required before caption revision')
    editor = _text(submitted['editor'], 'editor', 200)
    rationale = _text(submitted['rationale'], 'rationale', 4000,
                      minimum=12)
    corrected = correct_vtt(snapshot['caption_bytes'],
                            submitted['caption_edits'])
    revised_caption_sha = hashlib.sha256(corrected).hexdigest()
    result = {
        'schema_version': 1,
        'status': 'CAPTION_REVISION_HANDOFF_READY',
        **FLAGS,
        **_bound_source(snapshot),
        'recorded_review_sha256': review_sha,
        'submitted_revision_sha256': hashlib.sha256(raw).hexdigest(),
        'submitted_revision_json': raw.decode('utf-8'),
        'editor': editor,
        'rationale': rationale,
        'revised_caption_sha256': revised_caption_sha,
        'candidate_media_unchanged': True,
        'voice_audio_unchanged': True,
        'listening_verified': False,
        'human_av_acceptance_recorded': False,
        'phone_playback_verified': False,
        'tool_sha256': digest(Path(__file__)),
        'scope': REVISION_SCOPE,
    }
    require(_snapshot(queue_root, job_id, short_dir) == snapshot
            and digest(recorded_review) == review_sha
            and _regular(revision_path).read_bytes() == raw,
            'Short, review, or revision input changed before handoff')
    output.mkdir(parents=True, exist_ok=False)
    try:
        (output / 'captions.vtt').write_bytes(corrected)
        _write(output / 'short-caption-revision.json', result)
        require(digest(output / 'captions.vtt') == revised_caption_sha,
                'Written revised captions differ from handoff')
        require(verify_caption_revision(
            queue_root, job_id, short_dir, recorded_review, output) == result,
            'Written caption revision failed replay')
    except BaseException:
        shutil.rmtree(output)
        raise
    return result


def verify_caption_revision(queue_root, job_id, short_dir, recorded_review,
                            revision_output):
    """Replay a caption-revision handoff without modifying any input."""
    revision_output = Path(os.path.abspath(revision_output))
    no_symlinks(revision_output)
    require(revision_output.is_dir()
            and {path.name for path in revision_output.iterdir()} ==
                {'captions.vtt', 'short-caption-revision.json'}
            and all(path.is_file() and not path.is_symlink()
                    for path in revision_output.iterdir()),
            'Exact regular caption-revision handoff files required')
    receipt_path = revision_output / 'short-caption-revision.json'
    _, value = _read_json(receipt_path)
    snapshot = _snapshot(queue_root, job_id, short_dir)
    source = _bound_source(snapshot)
    require(snapshot['preview_caption_mode'] == 'sidecar',
            'Caption revision replay requires a sidecar Short')
    review = verify_recorded_short_review(
        queue_root, job_id, short_dir, recorded_review)
    review_sha = digest(recorded_review)
    fields = ({'schema_version', 'status', *FLAGS, *source,
               'recorded_review_sha256', 'submitted_revision_sha256',
               'submitted_revision_json', 'editor', 'rationale',
               'revised_caption_sha256', 'candidate_media_unchanged',
               'voice_audio_unchanged', 'listening_verified',
               'human_av_acceptance_recorded', 'phone_playback_verified',
               'tool_sha256', 'scope'})
    require(set(value) == fields
            and value.get('schema_version') == 1
            and value.get('status') == 'CAPTION_REVISION_HANDOFF_READY'
            and all(value.get(key) is False for key in FLAGS)
            and value.get('candidate_media_unchanged') is True
            and value.get('voice_audio_unchanged') is True
            and value.get('listening_verified') is False
            and value.get('human_av_acceptance_recorded') is False
            and value.get('phone_playback_verified') is False
            and _known_review_tool(value.get('tool_sha256'), snapshot)
            and (value.get('tool_sha256') != PRE_SAFE_AREA_REVIEW_TOOL_SHA256
                 or review['tool_sha256'] == PRE_SAFE_AREA_REVIEW_TOOL_SHA256)
            and value.get('scope') == REVISION_SCOPE
            and value.get('recorded_review_sha256') == review_sha,
            'Caption revision handoff scope or flags are invalid')
    require(all(value.get(key) == item for key, item in source.items()),
            'Caption revision no longer binds the durable derivative')
    raw_text = value.get('submitted_revision_json')
    require(isinstance(raw_text, str)
            and hashlib.sha256(raw_text.encode()).hexdigest() ==
                value.get('submitted_revision_sha256'),
            'Recorded submitted revision identity changed')
    try:
        submitted = json.loads(raw_text, object_pairs_hook=_pairs,
                               parse_constant=_constant)
    except json.JSONDecodeError as error:
        raise ValueError('Recorded submitted revision JSON is invalid') from error
    expected_fields = {'candidate_sha256', 'caption_sha256',
                       'recorded_review_sha256', 'editor', 'rationale',
                       'caption_edits'}
    require(isinstance(submitted, dict) and set(submitted) == expected_fields
            and submitted['candidate_sha256'] == source['candidate_sha256']
            and submitted['caption_sha256'] == source['caption_sha256']
            and submitted['recorded_review_sha256'] == review_sha
            and any(item['check'] in ('caption_accuracy', 'caption_readability')
                    for item in review['findings']),
            'Recorded caption revision identities are invalid')
    editor = _text(submitted['editor'], 'editor', 200)
    rationale = _text(submitted['rationale'], 'rationale', 4000, minimum=12)
    corrected = correct_vtt(snapshot['caption_bytes'],
                            submitted['caption_edits'])
    revised_sha = hashlib.sha256(corrected).hexdigest()
    require(value.get('editor') == editor
            and value.get('rationale') == rationale
            and value.get('revised_caption_sha256') == revised_sha
            and (revision_output / 'captions.vtt').read_bytes() == corrected,
            'Caption revision content or identity changed')
    require(_snapshot(queue_root, job_id, short_dir) == snapshot,
            'Durable Short changed while verifying caption revision')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    record = commands.add_parser('record')
    record_attestation = commands.add_parser('record-attestation-findings')
    revise = commands.add_parser('revise-captions')
    for command in (record, record_attestation, revise):
        command.add_argument('--queue-root', required=True)
        command.add_argument('--job-id', required=True)
        command.add_argument('--short-dir', required=True)
        command.add_argument('--output', required=True)
    record.add_argument('--review', required=True)
    record_attestation.add_argument('--attestation', required=True)
    revise.add_argument('--recorded-review', required=True)
    revise.add_argument('--revision', required=True)
    args = parser.parse_args()
    if args.command == 'record':
        result = record_short_review(args.queue_root, args.job_id,
                                     args.short_dir, args.review, args.output)
    elif args.command == 'record-attestation-findings':
        result = record_attestation_findings(
            args.queue_root, args.job_id, args.short_dir,
            args.attestation, args.output)
    else:
        result = prepare_caption_revision(
            args.queue_root, args.job_id, args.short_dir,
            args.recorded_review, args.revision, args.output)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
