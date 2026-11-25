"""Immutable, candidate-bound reviewer attestations and revision handoffs.

Recording a statement is not independent verification of that statement. Nothing
in this module grants production approval or enables publication.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

from integrations.content_control.cycle_editorial import compile_editorial, _timestamp, _text
from integrations.content_control.cycle_package import declared_speaker_label, editorial_digest
from integrations.content_control.review_package import digest, no_symlinks, require, SHA


CHECKS = ('factual_accuracy', 'full_audiovisual', 'voice_naturalness',
          'visual_readability', 'originality', 'reference_comparison')
LISTENER_CHECKS = ('naturalness', 'pronunciation', 'character_consistency',
                   'music_and_sfx', 'transitions', 'mix_balance')
WATCHER_CHECKS = ('picture_continuity', 'caption_readability', 'audio_visual_sync',
                  'pacing_and_transitions', 'creative_coherence')
FLAGS = ('publication_enabled', 'paid_generation_enabled', 'production_approved', 'full_av_review')


def _regular(path, limit=1024 * 1024):
    no_symlinks(path)
    require(path.is_file() and path.stat().st_size <= limit, 'Missing or oversized file: ' + path.name)
    return path


def _load(path, limit=1024 * 1024):
    value = json.loads(_regular(path, limit).read_text())
    require(isinstance(value, dict), 'JSON object required: ' + path.name)
    return value


def _unapproved(value):
    require(all(value.get(flag) is False for flag in FLAGS), 'Publication and approval flags must remain false')


def _verified_voice(root, editorial, render):
    """Authenticate an optional renderer voice receipt and canonical assignments."""
    from integrations.content_control.cycle_render import VOICE_ASSIGNMENTS

    voice_path = root / 'render/voice.json'
    declared = render.get('voice_receipt_sha256')
    present = voice_path.exists()
    if not present and declared is None:
        return None
    require(present and isinstance(declared, str) and SHA.fullmatch(declared),
            'Voice receipt file and identity must appear together')
    voice = _load(voice_path)
    voice_hash = digest(voice_path)
    require(declared == voice_hash, 'Rendered voice receipt identity mismatch')
    require(voice.get('status') == 'GENERATED_PENDING_LISTENING_REVIEW'
            and voice.get('voice_assignments') == VOICE_ASSIGNMENTS
            and all(voice.get(key) is False for key in
                    ('publication_enabled', 'production_approved', 'full_av_review')),
            'Voice receipt or assignments changed')
    clips = voice.get('clips')
    scenes = editorial.get('scenes')
    require(isinstance(clips, list) and isinstance(scenes, list) and len(clips) == len(scenes),
            'Voice clips do not match authored scenes')
    for clip, scene in zip(clips, scenes):
        speaker = scene.get('speaker', 'narrator')
        require(isinstance(clip, dict) and clip.get('scene_id') == scene.get('id')
                and clip.get('speaker') == speaker
                and clip.get('voice_id') == VOICE_ASSIGNMENTS.get(speaker),
                'Character voice assignment changed')
    assignments_sha = hashlib.sha256(json.dumps(
        VOICE_ASSIGNMENTS, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {'voice_receipt_sha256': voice_hash, 'voice_assignments_sha256': assignments_sha}


def _verified_program_duration(root):
    """Freshly decode the exact candidate and reject divergent receipts.

    Package and render receipts can be rewritten together, so neither is the
    measurement authority at review time.  Hash the candidate on both sides of
    a bounded FFprobe/full FFmpeg decode, then compare that fresh observation
    with both receipts.  Human coverage must span the measured candidate, not
    merely a renderer-declared timeline that can be shorter or stale.
    """
    from integrations.content_control.cycle_package import (declared_layout,
                                                            declared_speaker_label,
                                                            inspect_media)

    package = _load(root / 'delivery/package.json')
    render = _load(root / 'delivery/render.json')
    editorial = _load(root / 'editorial.json')
    media = package.get('media')
    require(isinstance(media, dict) and set(media) == {
        'decode', 'duration_seconds', 'width', 'height'},
        'Exact decoded package media fields required for direct review')
    candidate = _regular(root / 'delivery/video.mp4', 256 * 1024 * 1024)
    expected_candidate = package.get('candidate_sha256')
    before = digest(candidate)
    require(isinstance(expected_candidate, str) and SHA.fullmatch(expected_candidate)
            and before == expected_candidate == render.get('candidate_sha256'),
            'Direct review candidate identity mismatch before media probe')
    layout = declared_layout(editorial, render)
    speaker_label = declared_speaker_label(editorial, render)
    observed = inspect_media(candidate, layout=layout, decode=True)
    after = digest(candidate)
    require(after == before == expected_candidate,
            'Direct review candidate changed during media probe')
    duration = observed.get('duration_seconds')
    width, height = observed.get('width'), observed.get('height')
    render_duration = render.get('duration_seconds')
    require(observed.get('decode') == 'PASS'
            and type(duration) in (int, float) and not isinstance(duration, bool)
            and math.isfinite(duration) and 0 < duration <= 1800
            and type(width) is int and type(height) is int
            and 16 <= width <= 8192 and 16 <= height <= 8192,
            'Valid freshly decoded media required for direct review')
    expected_dimensions = (1280, 720) if layout == 'landscape' else (720, 1280)
    require((width, height) == expected_dimensions
            and (not speaker_label or expected_dimensions == (720, 1280)),
            'Fresh media dimensions disagree with the render contract')
    declared_duration = media.get('duration_seconds')
    require(media.get('decode') == 'PASS'
            and type(declared_duration) in (int, float) and not isinstance(declared_duration, bool)
            and math.isfinite(declared_duration)
            and media.get('width') == width and media.get('height') == height
            and abs(declared_duration - duration) <= .001,
            'Fresh media observation disagrees with the package receipt')
    require(type(render_duration) in (int, float) and not isinstance(render_duration, bool)
            and math.isfinite(render_duration)
            and abs(render_duration - duration) <= .001,
            'Fresh media duration disagrees with the render timeline')
    return duration


def _complete_coverage(root, value, label):
    return _coverage_for_duration(value, label, _verified_program_duration(root))


def _coverage_for_duration(value, label, duration):
    coverage = value.get('coverage')
    require(isinstance(coverage, list) and 1 <= len(coverage) <= 100,
            label.capitalize() + ' coverage intervals required')
    normalized, prior = [], 0.0
    for interval in coverage:
        require(isinstance(interval, dict) and set(interval) == {'start_seconds', 'end_seconds'},
                'Exact ' + label + ' coverage interval fields required')
        start, end = interval['start_seconds'], interval['end_seconds']
        require(all(type(item) in (int, float) and not isinstance(item, bool) for item in (start, end))
                and 0 <= start < end <= duration + .001 and abs(start - prior) <= .001,
                label.capitalize() + ' coverage must be contiguous from zero')
        normalized.append({'start_seconds': start, 'end_seconds': end})
        prior = end
    require(abs(prior - duration) <= .001, label.capitalize() + ' coverage must include the complete program')
    return normalized


def _granular_review_checks(value, expected, label):
    checks = value.get('checks')
    require(isinstance(checks, dict) and set(checks) == set(expected),
            'All granular ' + label + ' checks are required')
    normalized, feedback = {}, []
    for name in expected:
        item = checks[name]
        require(isinstance(item, dict) and set(item) in ({'passed', 'evidence'},
                {'passed', 'evidence', 'feedback'}) and type(item.get('passed')) is bool,
                'Exact granular ' + label + ' check fields required')
        field = label + '_review.' + name
        evidence = _text(item.get('evidence'), field + '.evidence', 4000, minimum=12)
        normalized[name] = {'passed': item['passed'], 'evidence': evidence}
        if item['passed']:
            require('feedback' not in item, 'Passing ' + label + ' checks cannot carry repair feedback')
        else:
            action = _text(item.get('feedback', evidence), field + '.feedback', 4000, minimum=12)
            normalized[name]['feedback'] = action
            feedback.append({'check': label + '.' + name, 'action': action})
    return normalized, feedback


def _watcher_attestation(root, snapshot, value):
    """Bind direct complete audiovisual notes to the exact video and captions."""
    require(isinstance(value, dict) and set(value) == {
        'schema_version', 'candidate_sha256', 'caption_sha256', 'watcher', 'watched_at',
        'basis', 'coverage', 'checks'}, 'Exact watcher review fields required')
    require(type(value.get('schema_version')) is int and value['schema_version'] == 1,
            'Watcher review schema mismatch')
    require(value.get('candidate_sha256') == snapshot['candidate_sha256'],
            'Watcher review targets a different candidate')
    caption_sha256 = snapshot['files_sha256']['delivery/captions.vtt']
    require(value.get('caption_sha256') == caption_sha256,
            'Watcher review targets different captions')
    watcher = _text(value.get('watcher'), 'watcher_review.watcher', 200)
    watched_at = _timestamp(value.get('watched_at'), 'watcher_review.watched_at')
    require(datetime.fromisoformat(watched_at) >= datetime.fromisoformat(snapshot['cycle']['finished_at']),
            'Watcher review predates completed cycle')
    require(value.get('basis') == 'direct_full_audiovisual_watch_and_listen',
            'Frames, transcripts and technical diagnostics cannot substitute for direct audiovisual review')
    coverage = _complete_coverage(root, value, 'watcher')
    normalized_checks, feedback = _granular_review_checks(value, WATCHER_CHECKS, 'watcher')
    return ({'schema_version': 1, 'candidate_sha256': snapshot['candidate_sha256'],
             'caption_sha256': caption_sha256, 'watcher': watcher, 'watched_at': watched_at,
             'basis': 'direct_full_audiovisual_watch_and_listen', 'coverage': coverage,
             'checks': normalized_checks, 'watcher_attestation_recorded': True,
             'independent_full_audiovisual_verification': False,
             'scope': ('Supplied direct complete audiovisual attestation; frames, transcripts and '
                       'technical diagnostics are excluded.')},
            feedback, all(item['passed'] for item in normalized_checks.values()))


def _validate_recorded_watcher(root, snapshot, value):
    require(isinstance(value, dict), 'Recorded watcher review required')
    submitted_fields = {'schema_version', 'candidate_sha256', 'caption_sha256', 'watcher',
                        'watched_at', 'basis', 'coverage', 'checks'}
    require(submitted_fields <= set(value), 'Recorded watcher review is incomplete')
    expected, _, passed = _watcher_attestation(
        root, snapshot, {key: value[key] for key in submitted_fields})
    require(value == expected, 'Recorded watcher review identity or scope changed')
    return passed


def _listener_attestation(root, snapshot, value):
    """Bind direct full-mix listening notes to the exact candidate and voices.

    This records a supplied human judgment.  It deliberately rejects ASR and
    signal diagnostics as substitutes and never promotes the judgment to an
    independently verified approval.
    """
    require(isinstance(value, dict) and set(value) == {
        'schema_version', 'candidate_sha256', 'listener', 'listened_at',
        'basis', 'coverage', 'checks'}, 'Exact listener review fields required')
    require(type(value.get('schema_version')) is int and value['schema_version'] == 1,
            'Listener review schema mismatch')
    require(value.get('candidate_sha256') == snapshot['candidate_sha256'],
            'Listener review targets a different candidate')
    listener = _text(value.get('listener'), 'listener_review.listener', 200)
    listened_at = _timestamp(value.get('listened_at'), 'listener_review.listened_at')
    require(datetime.fromisoformat(listened_at) >= datetime.fromisoformat(snapshot['cycle']['finished_at']),
            'Listener review predates completed cycle')
    require(value.get('basis') == 'direct_full_mix_listening',
            'ASR and technical diagnostics cannot substitute for direct listening')

    render = _load(root / 'delivery/render.json')
    normalized_coverage = _complete_coverage(root, value, 'listener')

    normalized_checks, feedback = _granular_review_checks(value, LISTENER_CHECKS, 'listener')

    voice_identity = _verified_voice(root, snapshot['editorial'], render)
    require(voice_identity is not None, 'Authenticated voice receipt required for listening review')
    return ({'schema_version': 1, 'candidate_sha256': snapshot['candidate_sha256'],
             'listener': listener, 'listened_at': listened_at,
             'basis': 'direct_full_mix_listening', 'coverage': normalized_coverage,
             'checks': normalized_checks, **voice_identity,
             'listener_attestation_recorded': True,
             'independent_listening_verification': False,
             'scope': 'Supplied direct full-mix listening attestation; ASR and signal diagnostics are excluded.'},
            feedback, all(item['passed'] for item in normalized_checks.values()))


def _validate_recorded_listener(root, snapshot, value):
    require(isinstance(value, dict), 'Recorded listener review required')
    submitted_fields = {'schema_version', 'candidate_sha256', 'listener', 'listened_at',
                        'basis', 'coverage', 'checks'}
    require(submitted_fields <= set(value), 'Recorded listener review is incomplete')
    expected, _, passed = _listener_attestation(
        root, snapshot, {key: value[key] for key in submitted_fields})
    require(value == expected, 'Recorded listener review identity or scope changed')
    return passed


def inspect_cycle(cycle_dir):
    """Validate existing artifact identities, without pretending to watch media."""
    root = Path(os.path.abspath(cycle_dir))
    no_symlinks(root)
    require(root.is_dir(), 'Cycle directory required')
    cycle = _load(root / 'cycle.json')
    require(cycle.get('status') == 'AWAITING_REVIEW' and cycle.get('technical_status') == 'PASS',
            'Completed unpublished cycle required')
    _unapproved(cycle)
    if 'revision_lineage' in cycle:
        from integrations.content_control.cycle_lineage import validate_lineage
        validate_lineage(cycle['revision_lineage'], cycle.get('brief_sha256'))
    delivery = root / 'delivery'
    no_symlinks(delivery)
    package = _load(delivery / 'package.json')
    require(digest(delivery / 'package.json') == cycle.get('package_sha256'), 'Package receipt changed')
    _unapproved(package)
    require(package.get('status') == 'AWAITING_REVIEW' and package.get('technical_status') == 'PASS',
            'Completed package required')
    files = package.get('files_sha256')
    required = {'video.mp4', 'captions.vtt', 'render.json', 'editorial.json', 'index.html',
                'thumbnail-1.png', 'thumbnail-2.png', 'thumbnail-3.png'}
    require(isinstance(files, dict) and required <= set(files), 'Incomplete package manifest')
    for name, expected in files.items():
        require(isinstance(name, str) and Path(name).name == name and name not in ('.', '..'),
                'Invalid package path')
        require(isinstance(expected, str) and SHA.fullmatch(expected), 'Invalid package hash')
        _regular(delivery / name, 256 * 1024 * 1024)
        require(digest(delivery / name) == expected, 'Package artifact changed: ' + name)
    require({path.name for path in delivery.iterdir()} == set(files) | {'package.json', 'review-package.zip'},
            'Unexpected package files')
    archive = _regular(delivery / 'review-package.zip', 256 * 1024 * 1024)
    # The archive's receipt is byte-identical to the bound standalone receipt.
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        expected_names = set(files) | {'package.json'}
        require(len(members) == len(expected_names) and {member.filename for member in members} == expected_names,
                'Archive members changed')
        for member in members:
            require(member.file_size == (delivery / member.filename).stat().st_size, 'Archive file size changed')
            with bundle.open(member) as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            require(actual == digest(delivery / member.filename), 'Archive artifact changed: ' + member.filename)
    editorial = _load(root / 'editorial.json')
    require(digest(root / 'editorial.json') == cycle.get('editorial_sha256'), 'Cycle editorial changed')
    require(_load(delivery / 'editorial.json') == editorial, 'Package editorial differs from cycle')
    require(editorial_digest(editorial) == package.get('editorial_sha256'), 'Editorial canonical binding mismatch')
    require(digest(_regular(root / 'brief.json')) == cycle.get('brief_sha256'), 'Cycle brief changed')
    require(compile_editorial(_load(root / 'brief.json')) == editorial, 'Brief no longer compiles to this editorial')
    require(('thumbnail_copy' in package) == ('thumbnail_copy' in editorial)
            and package.get('thumbnail_copy') == editorial.get('thumbnail_copy'),
            'Thumbnail copy differs from compiled editorial')
    candidate = digest(delivery / 'video.mp4')
    require(candidate == cycle.get('candidate_sha256') == package.get('candidate_sha256'), 'Candidate mismatch')
    render = _load(delivery / 'render.json')
    declared_speaker_label(editorial, render)
    declared_speaker_label(editorial, package)
    _unapproved(render)
    require(render.get('technical_status') == 'PASS' and render.get('candidate_sha256') == candidate,
            'Render verification mismatch')
    require(render.get('editorial_sha256') == package.get('editorial_sha256'), 'Render editorial mismatch')
    require(digest(delivery / 'captions.vtt') == render.get('caption_sha256') == package.get('caption_sha256'),
            'Caption identity mismatch')
    require(digest(delivery / 'render.json') == package.get('render_receipt_sha256'), 'Render receipt identity mismatch')
    for name in ('video.mp4', 'captions.vtt', 'render.json'):
        _regular(root / 'render' / name, 256 * 1024 * 1024)
        require(digest(root / 'render' / name) == digest(delivery / name), 'Original render artifact changed: ' + name)
    voice_identity = _verified_voice(root, editorial, render)
    identities = {name: digest(root / name) for name in ('cycle.json', 'brief.json', 'editorial.json',
                   'render/render.json', 'delivery/package.json', 'delivery/review-package.zip')}
    if voice_identity is not None:
        identities['render/voice.json'] = voice_identity['voice_receipt_sha256']
    identities.update({'delivery/' + name: expected for name, expected in files.items()})
    return {'cycle': cycle, 'editorial': editorial, 'candidate_sha256': candidate, 'files_sha256': identities}


def _new_output(path, root, source):
    path = Path(os.path.abspath(path))
    no_symlinks(path)
    require(not path.exists(), 'Output already exists')
    require(not path.is_relative_to(root) and path != source, 'Output must be separate from existing cycle and input')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def lint_package(cycle_dir, output):
    """Run pinned offline title/thumbnail copy lint on an exact review package."""
    from integrations.run import source
    from integrations.youtube_skill.adapter import dispatch

    require(all(os.environ.get(k, 'false').lower() == 'false' for k in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')), 'Publishing and paid generation must remain disabled')
    root = Path(os.path.abspath(cycle_dir))
    snapshot = inspect_cycle(root)
    output = _new_output(output, root, root / 'delivery/package.json')
    editorial = snapshot['editorial']
    title = editorial['title']
    payload = {'title': title, 'thumb': editorial.get('thumbnail_copy', ' '.join(title.split()))}
    # The pinned CLI scans all argv for switches, even in value positions.
    require(title not in ('--json', '--thumb') and payload['thumb'] != '--json',
            'Title or thumbnail copy conflicts with the pinned lint CLI')
    with tempfile.TemporaryDirectory(prefix='cyzor-package-lint-') as temp:
        input_path = Path(temp) / 'copy.json'
        input_path.write_text(json.dumps(payload, sort_keys=True, allow_nan=False) + '\n')
        input_sha = digest(input_path)
        execution = dispatch({'operation': 'package-lint', 'input': str(input_path),
                              'publication_enabled': False, 'paid_generation_enabled': False},
                             source('youtube-agent-skill'))
    require(execution.get('tool') == 'youtube-agent-skill' and execution.get('operation') == 'package-lint'
            and execution.get('input_sha256') == input_sha and execution.get('status') in ('PASS', 'BLOCKED')
            and execution.get('execution_status') == execution['status']
            and all(execution.get(key) is False for key in ('publication_enabled', 'paid_generation_enabled',
                    'production_ready')), 'Invalid package lint evidence')
    if execution['status'] == 'PASS':
        findings = execution.get('findings')
        require(execution.get('exit_code') == 0 and isinstance(findings, list) and len(findings) == 1 and isinstance(findings[0], dict)
                and findings[0].get('title') == title.strip(), 'Lint did not check the submitted title')
    files = snapshot['files_sha256']
    require(inspect_cycle(root)['files_sha256'] == files, 'Package changed during lint')
    result = {'schema_version': 1,
              'status': 'DIAGNOSTIC_COMPLETE' if execution['status'] == 'PASS' else 'BLOCKED',
              'recorded_at': datetime.now(timezone.utc).isoformat(),
              'candidate_sha256': snapshot['candidate_sha256'],
              'package_sha256': files['delivery/package.json'],
              'source_files_sha256': files, 'input_copy': payload, 'execution': execution,
              'thumbnail_selection_verified': False, 'thumbnail_performance_verified': False,
              'production_ready': False, **dict.fromkeys(FLAGS, False),
              'scope': 'Offline title and thumbnail copy lint. All three thumbnails use the same authored copy; '
                       'picture quality, selection, performance and audiovisual approval are unverified.'}
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    return result


def _rea_diagnostic_findings(evidence):
    """Turn exact detector misses into bounded human-review actions, not verdicts."""
    require(isinstance(evidence, dict), 'Invalid REA diagnostic evidence')
    coverage = evidence.get('authored_cut_coverage')
    samples = evidence.get('authored_scene_samples')
    require(isinstance(coverage, dict) and isinstance(samples, dict),
            'Incomplete REA diagnostic evidence')
    if coverage.get('status') != 'MISSING_AUTHORED_CUTS':
        return []
    missing = coverage.get('missing_cuts')
    tolerance = coverage.get('tolerance_seconds')
    require(isinstance(missing, list) and missing and type(tolerance) in (int, float)
            and 0 < tolerance <= 1 and samples.get('status') in ('SCENE_SAMPLES_READY', 'BLOCKED'),
            'Invalid missing-cut evidence')
    findings = []
    for item in missing:
        require(isinstance(item, dict) and set(item) == {'scene_id', 'authored_seconds'}
                and isinstance(item['scene_id'], str) and 0 < len(item['scene_id']) <= 200
                and type(item['authored_seconds']) in (int, float) and item['authored_seconds'] >= 0,
                'Invalid missing-cut identity')
        findings.append({
            'source': 'rea_video_diagnostic',
            'check': 'visual_readability',
            'scene_id': item['scene_id'],
            'authored_seconds': item['authored_seconds'],
            'tolerance_seconds': tolerance,
            'sample_navigation_status': samples['status'],
            'action': ('Inspect the exact transition into scene ' + item['scene_id']
                       + ' at authored second ' + str(item['authored_seconds'])
                       + '; the bound detector found no boundary within ±' + str(tolerance)
                       + ' seconds. Record a human audiovisual judgment and rerender only if that review confirms a defect.'),
        })
    return findings


def _comparison_feedback(comparison):
    """Route exact retained comparator actions without promoting their truth."""
    feedback = []
    for reference in comparison['references']:
        for action in reference['actionable_findings']:
            item = {'check': 'reference_comparison', 'action': action}
            if item not in feedback:
                feedback.append(item)
    return feedback


def _private_review_feedback(record):
    """Route only explicit open blockers from a replayed private review."""
    feedback = []
    for finding in record['findings']:
        if finding['severity'] != 'blocker' or finding['resolution_state'] != 'open':
            continue
        category = finding['category']
        observation = _text(finding['observation'],
                            'private_review.finding.observation', 1600)
        repair = _text(finding['requested_repair'],
                       'private_review.finding.requested_repair', 1600)
        start = format(finding['start_seconds'], '.3f').rstrip('0').rstrip('.')
        end = format(finding['end_seconds'], '.3f').rstrip('0').rstrip('.')
        feedback.append({
            'check': 'private_review.' + category,
            'action': f'{start}-{end}s: {repair} Observation: {observation}',
        })
    return feedback


def _private_review_receipt(root, snapshot, path):
    """Replay and retain a private-player record as repair evidence only."""
    from integrations.content_control.offline_review_record import validate_record

    path = Path(os.path.abspath(path))
    raw = _regular(path).read_bytes()
    try:
        raw_json = raw.decode('utf-8')
        record = json.loads(raw_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('Valid UTF-8 JSON private review record required') from error
    require(isinstance(record, dict), 'Private review record must be an object')
    caption_sha256 = snapshot['files_sha256']['delivery/captions.vtt']
    replay = validate_record(record, video_sha256=snapshot['candidate_sha256'],
                             caption_sha256=caption_sha256)
    recorded_at = _timestamp(record.get('recorded_at'), 'private_review.recorded_at')
    require(datetime.fromisoformat(recorded_at) >=
            datetime.fromisoformat(snapshot['cycle']['finished_at']),
            'Private review predates completed cycle')
    feedback = _private_review_feedback(record)
    receipt = {
        'schema_version': 1,
        'status': ('PRIVATE_REVIEW_REPAIR_REQUIRED' if feedback
                   else 'PRIVATE_REVIEW_RECORDED'),
        'candidate_sha256': snapshot['candidate_sha256'],
        'caption_sha256': caption_sha256,
        'record_sha256': replay['record_sha256'],
        'submitted_record_file_sha256': hashlib.sha256(raw).hexdigest(),
        'submitted_record_json': raw_json,
        'recorded_at': recorded_at,
        'reviewer': record['reviewer_attestation']['reviewer'],
        'review_round': record['reviewer_attestation']['review_round'],
        'review_coverage_complete': replay['review_coverage_complete'],
        'feedback': feedback,
        'independent_acceptance': False,
        'full_av_acceptance': False,
        'production_approved': False,
        'publication_enabled': False,
        'paid_generation_enabled': False,
        'scope': ('Replayed exact private-player watch/listen record. Only explicit open '
                  'blockers are routed; coverage and attestations do not grant independent '
                  'audiovisual or creative acceptance.'),
    }
    return receipt, feedback, path


def _validate_recorded_private_review(root, snapshot, receipt):
    """Replay an embedded private record and reject altered repair routing."""
    from integrations.content_control.offline_review_record import validate_record

    fields = {
        'schema_version', 'status', 'candidate_sha256', 'caption_sha256',
        'record_sha256', 'submitted_record_file_sha256', 'recorded_at', 'reviewer',
        'submitted_record_json', 'review_round', 'review_coverage_complete',
        'feedback',
        'independent_acceptance', 'full_av_acceptance', 'production_approved',
        'publication_enabled', 'paid_generation_enabled', 'scope',
    }
    require(isinstance(receipt, dict) and set(receipt) == fields,
            'Invalid recorded private review fields')
    raw_json = receipt.get('submitted_record_json')
    require(isinstance(raw_json, str) and len(raw_json.encode('utf-8')) <= 1024 * 1024,
            'Recorded private review source JSON is invalid or oversized')
    try:
        record = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise ValueError('Recorded private review source JSON is invalid') from error
    require(isinstance(record, dict), 'Recorded private review source must be an object')
    caption_sha256 = snapshot['files_sha256']['delivery/captions.vtt']
    replay = validate_record(record, video_sha256=snapshot['candidate_sha256'],
                             caption_sha256=caption_sha256)
    feedback = _private_review_feedback(record)
    expected_status = ('PRIVATE_REVIEW_REPAIR_REQUIRED' if feedback
                       else 'PRIVATE_REVIEW_RECORDED')
    require(receipt.get('schema_version') == 1
            and receipt.get('status') == expected_status
            and receipt.get('candidate_sha256') == snapshot['candidate_sha256']
            and receipt.get('caption_sha256') == caption_sha256
            and receipt.get('record_sha256') == replay['record_sha256']
            and receipt.get('submitted_record_file_sha256') ==
                hashlib.sha256(raw_json.encode('utf-8')).hexdigest()
            and receipt.get('recorded_at') == _timestamp(
                record.get('recorded_at'), 'private_review.recorded_at')
            and receipt.get('reviewer') == record['reviewer_attestation']['reviewer']
            and receipt.get('review_round') == record['reviewer_attestation']['review_round']
            and receipt.get('review_coverage_complete') is replay['review_coverage_complete']
            and receipt.get('feedback') == feedback
            and all(receipt.get(key) is False for key in
                    ('independent_acceptance', 'full_av_acceptance',
                     'production_approved', 'publication_enabled',
                     'paid_generation_enabled'))
            and receipt.get('scope') ==
                ('Replayed exact private-player watch/listen record. Only explicit open '
                 'blockers are routed; coverage and attestations do not grant independent '
                 'audiovisual or creative acceptance.'),
            'Recorded private review identity, evidence or scope changed')
    require(datetime.fromisoformat(receipt['recorded_at']) >=
            datetime.fromisoformat(snapshot['cycle']['finished_at']),
            'Recorded private review predates completed cycle')
    return feedback


def record_review(cycle_dir, review_path, output, *, rea_analysis=None,
                  live_comparison_source=None, live_comparison_receipt=None,
                  private_review_record=None):
    root, review_path = Path(os.path.abspath(cycle_dir)), Path(os.path.abspath(review_path))
    snapshot = inspect_cycle(root)
    review = _load(review_path)
    review_hash = digest(review_path)
    require(review.get('candidate_sha256') == snapshot['candidate_sha256'], 'Review targets a different candidate')
    reviewer = _text(review.get('reviewer'), 'reviewer', 200)
    reviewed_at = _timestamp(review.get('reviewed_at'), 'reviewed_at')
    require(datetime.fromisoformat(reviewed_at) >= datetime.fromisoformat(snapshot['cycle']['finished_at']),
            'Review predates completed cycle')
    checks = review.get('checks', {})
    require(isinstance(checks, dict) and set(checks) <= set(CHECKS), 'Unknown or invalid review checks')
    normalized, feedback = {}, []
    for name in CHECKS:
        item = checks.get(name)
        if item is None:
            feedback.append({'check': name, 'action': 'Complete and document the ' + name.replace('_', ' ') + ' review.'})
            continue
        require(isinstance(item, dict) and type(item.get('passed')) is bool, 'Review passed values must be booleans')
        evidence = _text(item.get('evidence'), name + '.evidence', 4000, minimum=12)
        normalized[name] = {'passed': item['passed'], 'evidence': evidence}
        if not item['passed']:
            action = _text(item.get('feedback', evidence), name + '.feedback', 4000, minimum=12)
            normalized[name]['feedback'] = action
            feedback.append({'check': name, 'action': action})
    listener = None
    watcher = None
    comparison = None
    comparison_findings = []
    private_review = None
    private_feedback = []
    if 'full_audiovisual' in checks:
        watcher, watcher_feedback, all_watcher_checks_passed = _watcher_attestation(
            root, snapshot, review.get('watcher_review'))
        require(checks['full_audiovisual']['passed'] is all_watcher_checks_passed,
                'Full audiovisual summary disagrees with granular watcher checks')
        feedback.extend(watcher_feedback)
    if 'voice_naturalness' in checks:
        listener, listener_feedback, all_listener_checks_passed = _listener_attestation(
            root, snapshot, review.get('listener_review'))
        require(checks['voice_naturalness']['passed'] is all_listener_checks_passed,
                'Voice naturalness summary disagrees with granular listener checks')
        feedback.extend(listener_feedback)
    if 'reference_comparison' in checks:
        from integrations.content_control.cycle_live_comparison import verify_live_comparison

        require(live_comparison_source is not None and live_comparison_receipt is not None,
                'Retained live comparison source and receipt required')
        comparison, comparison_receipt_sha = verify_live_comparison(
            root, live_comparison_source, live_comparison_receipt)
        require(datetime.fromisoformat(reviewed_at) >=
                datetime.fromisoformat(comparison['reviewed_at']),
                'Editorial review predates the live comparison')
        if checks['reference_comparison']['passed'] is False:
            comparison_findings = _comparison_feedback(comparison)
            feedback = [item for item in feedback if item not in comparison_findings]
            feedback.extend(comparison_findings)
    else:
        require(live_comparison_source is None and live_comparison_receipt is None,
                'Live comparison inputs require a reference comparison check')
    private_path = None
    if private_review_record is not None:
        private_review, private_feedback, private_path = _private_review_receipt(
            root, snapshot, private_review_record)
        require(datetime.fromisoformat(reviewed_at) >=
                datetime.fromisoformat(private_review['recorded_at']),
                'Editorial review predates the private review record')
        feedback.extend(private_feedback)
    result_schema = (4 if comparison_findings and private_review is not None else
                     3 if private_review is not None else
                     2 if comparison_findings else 1)
    result = {'schema_version': result_schema,
              'status': 'REVISION_REQUIRED' if feedback else 'EDITORIAL_REVIEW_RECORDED',
              'candidate_sha256': snapshot['candidate_sha256'], 'reviewer': reviewer,
              'reviewed_at': reviewed_at, 'recorded_at': datetime.now(timezone.utc).isoformat(),
              'checks': normalized, 'feedback': feedback, 'source_files_sha256': snapshot['files_sha256'],
              'submitted_review_sha256': review_hash, 'independent_verification': False,
              'scope': 'Candidate-bound reviewer attestation only; supplied judgments are not independently verified.',
              'publication_enabled': False, 'paid_generation_enabled': False, 'production_approved': False,
              'full_av_review': False, 'production_ready': False}
    if listener is not None:
        result['listener_review'] = listener
    if watcher is not None:
        result['watcher_review'] = watcher
    if comparison is not None:
        result['live_comparison_receipt'] = comparison
        result['live_comparison_receipt_file_sha256'] = comparison_receipt_sha
    if comparison_findings:
        result['comparison_findings'] = comparison_findings
    if private_review is not None:
        result['private_review_receipt'] = private_review
        result['private_review_findings'] = private_feedback
    recheck_rea = None
    if rea_analysis is not None:
        from integrations.rea_video.analyze_cycle import review_evidence

        require(not Path(os.path.abspath(output)).is_relative_to(Path(os.path.abspath(rea_analysis)).parent),
                'Review output must be separate from the REA analysis directory')
        result['rea_diagnostics'], recheck_rea = review_evidence(rea_analysis, root, snapshot, reviewed_at)
        findings = _rea_diagnostic_findings(result['rea_diagnostics'])
        if findings:
            feedback.extend(findings)
            result['diagnostic_findings'] = findings
            result['status'] = 'REVISION_REQUIRED'
    require(len(feedback) <= 100,
            'Recorded review feedback exceeds the revision lineage limit')
    require(inspect_cycle(root)['files_sha256'] == snapshot['files_sha256'] and digest(review_path) == review_hash
            and (private_path is None or digest(private_path) ==
                 private_review['submitted_record_file_sha256']),
            'Review inputs changed while recording')
    output = _new_output(output, root, review_path)
    if recheck_rea is not None:
        recheck_rea()
    require(inspect_cycle(root)['files_sha256'] == snapshot['files_sha256'] and digest(review_path) == review_hash
            and (private_path is None or digest(private_path) ==
                 private_review['submitted_record_file_sha256']),
            'Review inputs changed before final recording')
    if listener is not None:
        rechecked = _listener_attestation(root, snapshot, review.get('listener_review'))
        require(rechecked == (listener, listener_feedback, all_listener_checks_passed),
                'Listener evidence changed before final recording')
    if watcher is not None:
        rechecked = _watcher_attestation(root, snapshot, review.get('watcher_review'))
        require(rechecked == (watcher, watcher_feedback, all_watcher_checks_passed),
                'Watcher evidence changed before final recording')
    if comparison is not None:
        from integrations.content_control.cycle_live_comparison import verify_live_comparison

        require(verify_live_comparison(
            root, live_comparison_source, live_comparison_receipt) ==
            (comparison, comparison_receipt_sha),
                'Live comparison evidence changed before final recording')
    if private_review is not None:
        rechecked, rechecked_feedback, _ = _private_review_receipt(
            root, snapshot, private_path)
        require(rechecked == private_review and rechecked_feedback == private_feedback,
                'Private review evidence changed before final recording')
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    return result


def revision_brief(cycle_dir, recorded_review_path, new_brief, output):
    """Write brief.json plus revision.json to a new directory for a fresh run.

    Prior sources/references are retained. Corrections use additional source IDs,
    preserving the evidence history instead of silently rewriting provenance.
    """
    root, review_path = Path(os.path.abspath(cycle_dir)), Path(os.path.abspath(recorded_review_path))
    snapshot = inspect_cycle(root)
    review = _load(review_path, 3 * 1024 * 1024)
    _unapproved(review)
    review_schema = review.get('schema_version')
    require(type(review_schema) is int and review_schema in (1, 2, 3, 4),
            'Recorded review schema version 1, 2, 3 or 4 required')
    strict_comparison = review_schema in (2, 4)
    strict_private = review_schema in (3, 4)
    require(review.get('status') in ('REVISION_REQUIRED', 'EDITORIAL_REVIEW_RECORDED'), 'Recorded review required')
    require(review.get('candidate_sha256') == snapshot['candidate_sha256'] and
            review.get('source_files_sha256') == snapshot['files_sha256'], 'Review does not bind current cycle')
    require(review.get('independent_verification') is False, 'Review scope mismatch')
    recorded_checks = review.get('checks')
    require(isinstance(recorded_checks, dict) and set(recorded_checks) <= set(CHECKS),
            'Recorded review checks are invalid')
    if 'full_audiovisual' in recorded_checks:
        require(isinstance(recorded_checks['full_audiovisual'], dict)
                and type(recorded_checks['full_audiovisual'].get('passed')) is bool
                and recorded_checks['full_audiovisual']['passed'] is
                    _validate_recorded_watcher(root, snapshot, review.get('watcher_review')),
                'Recorded watcher result disagrees with full audiovisual summary')
    if 'voice_naturalness' in recorded_checks:
        require(isinstance(recorded_checks['voice_naturalness'], dict)
                and type(recorded_checks['voice_naturalness'].get('passed')) is bool
                and recorded_checks['voice_naturalness']['passed'] is
                    _validate_recorded_listener(root, snapshot, review.get('listener_review')),
                'Recorded listener result disagrees with voice naturalness summary')
    comparison = None
    if 'reference_comparison' in recorded_checks:
        from integrations.content_control.cycle_live_comparison import validate_recorded_comparison

        comparison = validate_recorded_comparison(
            root, review.get('live_comparison_receipt'))
        comparison_receipt_sha = review.get('live_comparison_receipt_file_sha256')
        require(isinstance(comparison_receipt_sha, str)
                and SHA.fullmatch(comparison_receipt_sha),
                'Recorded live comparison receipt file identity required')
        require(datetime.fromisoformat(_timestamp(review.get('reviewed_at'), 'reviewed_at')) >=
                datetime.fromisoformat(comparison['reviewed_at']),
                'Recorded editorial review predates the live comparison')
    else:
        require('live_comparison_receipt' not in review
                and 'live_comparison_receipt_file_sha256' not in review,
                'Live comparison receipt requires a reference comparison check')
    recorded_feedback = review.get('feedback')
    require(isinstance(recorded_feedback, list), 'Recorded feedback must be a list')
    expected_comparison_findings = (_comparison_feedback(comparison)
                                    if comparison is not None
                                    and recorded_checks['reference_comparison']['passed'] is False
                                    else [])
    if strict_comparison:
        require(comparison is not None
                and recorded_checks['reference_comparison']['passed'] is False
                and bool(expected_comparison_findings),
                'Schema-2 review requires failed routed comparison findings')
        require(review.get('comparison_findings') == expected_comparison_findings,
                'Recorded comparison findings are missing or changed')
        manual_comparison_feedback = []
        if (comparison is not None
                and recorded_checks['reference_comparison']['passed'] is False):
            manual = {'check': 'reference_comparison',
                      'action': recorded_checks['reference_comparison']['feedback']}
            if manual not in expected_comparison_findings:
                manual_comparison_feedback.append(manual)
        retained_comparison_feedback = [
            item for item in recorded_feedback
            if isinstance(item, dict) and item.get('check') == 'reference_comparison']
        require(retained_comparison_feedback ==
                manual_comparison_feedback + expected_comparison_findings,
                'Recorded comparison feedback order or identity changed')
    else:
        require('comparison_findings' not in review,
                'Legacy review cannot claim routed comparison findings')
    private_feedback = []
    if strict_private:
        private_feedback = _validate_recorded_private_review(
            root, snapshot, review.get('private_review_receipt'))
        require(datetime.fromisoformat(_timestamp(review.get('reviewed_at'), 'reviewed_at')) >=
                datetime.fromisoformat(review['private_review_receipt']['recorded_at']),
                'Recorded editorial review predates the private review record')
        require(review.get('private_review_findings') == private_feedback,
                'Recorded private review findings are missing or changed')
        retained_private_feedback = [
            item for item in recorded_feedback
            if isinstance(item, dict)
            and isinstance(item.get('check'), str)
            and item['check'].startswith('private_review.')]
        require(retained_private_feedback == private_feedback,
                'Recorded private review feedback order or identity changed')
    else:
        require('private_review_receipt' not in review
                and 'private_review_findings' not in review,
                'Legacy review cannot claim routed private-review findings')
    diagnostic_findings = (_rea_diagnostic_findings(review['rea_diagnostics'])
                           if 'rea_diagnostics' in review else [])
    require(('diagnostic_findings' in review) == bool(diagnostic_findings)
            and review.get('diagnostic_findings', []) == diagnostic_findings
            and all(item in recorded_feedback for item in diagnostic_findings),
            'Recorded diagnostic findings are missing or changed')
    revised = compile_editorial(new_brief)
    old = snapshot['editorial']
    require(revised.get('idea_learning') == old.get('idea_learning'),
            'Prior idea learning provenance must be preserved')
    if old.get('topic_discovery') is not None:
        require(revised.get('topic') == old.get('topic')
                and revised.get('topic_discovery') == old.get('topic_discovery'),
                'Prior topic discovery provenance must be preserved')
    require(revised != old, 'Revision must change the editorial brief')
    sources = {source['id']: source for source in revised['sources']}
    require(all(sources.get(source['id']) == source for source in old['sources']), 'Prior source provenance must be preserved')
    require(all(reference in revised['reference_observations'] for reference in old['reference_observations']),
            'Prior reference provenance must be preserved')
    output = _new_output(output, root, review_path)
    review_hash = digest(review_path)
    discovery = old.get('topic_discovery')
    result = {'schema_version': 2 if discovery is not None else 1,
              'status': 'REVISION_BRIEF_READY',
              'supersedes_candidate_sha256': snapshot['candidate_sha256'],
              'recorded_review_sha256': review_hash, 'prior_cycle_sha256': snapshot['files_sha256']['cycle.json'],
              'feedback': review.get('feedback', []), 'feedback_resolution_verified': False,
              'publication_enabled': False, 'paid_generation_enabled': False, 'production_approved': False,
              'full_av_review': False, 'production_ready': False,
              'scope': 'Revised supplied brief; previous approval statements cannot certify a new render.'}
    if diagnostic_findings:
        result['review_diagnostic_findings'] = diagnostic_findings
        result['rea_diagnostics_receipt_sha256'] = review['rea_diagnostics']['receipt_sha256']
    if comparison is not None:
        result['live_comparison_receipt_sha256'] = hashlib.sha256(json.dumps(
            comparison, sort_keys=True, separators=(',', ':'),
            allow_nan=False).encode()).hexdigest()
        result['live_comparison_observations_sha256'] = comparison[
            'submitted_observations_sha256']
        result['live_comparison_receipt_file_sha256'] = comparison_receipt_sha
    if strict_comparison:
        result['schema_version'] = 3
        result['recorded_review_schema_version'] = review_schema
        result['comparison_findings_routing_verified'] = True
    if strict_private:
        result['schema_version'] = 5 if strict_comparison else 4
        result['recorded_review_schema_version'] = review_schema
        result['private_review_record_sha256'] = review[
            'private_review_receipt']['record_sha256']
        result['private_review_source_file_sha256'] = review[
            'private_review_receipt']['submitted_record_file_sha256']
        result['private_review_findings_routing_verified'] = True
    if discovery is not None:
        result['topic_discovery_sha256'] = hashlib.sha256(
            json.dumps(discovery, sort_keys=True, separators=(',', ':'),
                       allow_nan=False).encode()).hexdigest()
    feedback_limit = (100 if result['schema_version'] in (3, 4, 5)
                      or diagnostic_findings else 6)
    require(len(result['feedback']) <= feedback_limit,
            'Revision feedback exceeds the retained lineage limit')
    require(inspect_cycle(root)['files_sha256'] == snapshot['files_sha256'] and digest(review_path) == review_hash,
            'Revision inputs changed')
    if 'voice_naturalness' in recorded_checks:
        require(recorded_checks['voice_naturalness']['passed'] is
                _validate_recorded_listener(root, snapshot, review.get('listener_review')),
                'Recorded listener evidence changed before revision')
    if 'full_audiovisual' in recorded_checks:
        require(recorded_checks['full_audiovisual']['passed'] is
                _validate_recorded_watcher(root, snapshot, review.get('watcher_review')),
                'Recorded watcher evidence changed before revision')
    if comparison is not None:
        from integrations.content_control.cycle_live_comparison import validate_recorded_comparison

        require(validate_recorded_comparison(root, review.get('live_comparison_receipt')) == comparison,
                'Recorded live comparison evidence changed before revision')
    if strict_private:
        require(_validate_recorded_private_review(
            root, snapshot, review.get('private_review_receipt')) == private_feedback,
            'Recorded private review evidence changed before revision')
    output.mkdir()
    try:
        with (output / 'brief.json').open('x') as stream:
            json.dump(new_brief, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
        result['brief_sha256'] = digest(output / 'brief.json')
        with (output / 'revision.json').open('x') as stream:
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
        from integrations.content_control.cycle_lineage import read_revision
        replayed = read_revision(output / 'revision.json', result['brief_sha256'])
        require(json.loads(replayed['revision_json']) == result,
                'Written revision handoff changed during replay')
    except BaseException:
        shutil.rmtree(output)
        raise
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-dir', required=True)
    parser.add_argument('--review')
    parser.add_argument('--output', required=True)
    parser.add_argument('--revision-brief', help='Optional new full brief JSON; --review must then be a recorded review.')
    diagnostics = parser.add_mutually_exclusive_group()
    diagnostics.add_argument('--analyze', action='store_true', help='Collect offline REA Video diagnostics before recording a review.')
    diagnostics.add_argument('--package-lint', action='store_true', help='Collect pinned YouTube title and thumbnail copy diagnostics.')
    parser.add_argument('--rea-runtime', help='Absolute Python interpreter from the installed REA Video environment.')
    parser.add_argument('--rea-analysis', help='Link a retained REA analysis.json to a submitted review.')
    parser.add_argument('--live-comparison-source',
                        help='Retained raw live-comparison observations; required with its receipt.')
    parser.add_argument('--live-comparison-receipt',
                        help='Retained live-comparison receipt; required with its source observations.')
    parser.add_argument('--private-review-record',
                        help='Exported schema-2 private-player review record to replay and route.')
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    if args.package_lint:
        if (args.review or args.revision_brief or args.rea_runtime or args.rea_analysis
                or args.live_comparison_source or args.live_comparison_receipt
                or args.private_review_record):
            parser.error('--package-lint cannot be combined with review, revision, or REA runtime options')
        result = lint_package(args.cycle_dir, args.output)
        print(json.dumps(result, indent=2))
        return 0 if result.get('status') == 'DIAGNOSTIC_COMPLETE' else 2
    if args.analyze:
        if (not args.rea_runtime or args.review or args.revision_brief or args.rea_analysis
                or args.live_comparison_source or args.live_comparison_receipt
                or args.private_review_record):
            parser.error('--analyze requires --rea-runtime and cannot be combined with --review or --revision-brief')
        from integrations.rea_video.analyze_cycle import analyze_cycle
        result = analyze_cycle(args.cycle_dir, args.output, runtime=args.rea_runtime, timeout=args.timeout)
        print(json.dumps(result, indent=2))
        return 0 if result.get('status') == 'DIAGNOSTIC_COMPLETE' else 2
    if not args.review or args.rea_runtime or (args.revision_brief and (
            args.rea_analysis or args.live_comparison_source or args.live_comparison_receipt
            or args.private_review_record)):
        parser.error('Review/revision requires --review; --rea-analysis is only for recording a review')
    if args.revision_brief:
        result = revision_brief(args.cycle_dir, args.review, _load(Path(args.revision_brief)), args.output)
    else:
        options = {'rea_analysis': args.rea_analysis} if args.rea_analysis is not None else {}
        if args.live_comparison_source is not None or args.live_comparison_receipt is not None:
            options.update(live_comparison_source=args.live_comparison_source,
                           live_comparison_receipt=args.live_comparison_receipt)
        if args.private_review_record is not None:
            options['private_review_record'] = args.private_review_record
        result = record_review(args.cycle_dir, args.review, args.output, **options)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
