"""Original offline OpenHiggsfield handoff and candidate-export intake.

No upstream code is copied or imported. No submit, credentials, public upload,
external download, or polling implementation exists in this boundary.
"""
import math
from pathlib import Path
import re

from reel_media import digest, json_digest, read_bytes, read_json, require_disabled, result

REVISION = 'b16a0efe4d7e2707b56f8ccb02387fd2a9d2eddf'
MODELS = {'soul-2': 'image', 'soul-cinema': 'image', 'kling-3-turbo': 'video'}


def prepare_generation(data):
    require_disabled(data)
    if set(data) - {'project_id', 'scene_id', 'model', 'prompt', 'settings',
                    'publication_enabled', 'paid_generation_enabled'}:
        raise ValueError('Unsupported option; uploads, credentials and remote media are not accepted')
    for field in ('project_id', 'scene_id'):
        if not isinstance(data.get(field), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', data[field]):
            raise ValueError('Safe explicit project_id and scene_id required')
    model, prompt, settings = data.get('model'), data.get('prompt'), data.get('settings', {})
    if not isinstance(model, str) or model not in MODELS:
        raise ValueError('Model is outside the reviewed handoff subset')
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise ValueError('A bounded nonempty prompt is required')
    if not isinstance(settings, dict):
        raise ValueError('Settings must be an object')
    allowed = {'aspectRatio', 'resolution', 'duration'} if MODELS[model] == 'video' else {
        'aspectRatio', 'resolution', 'batchSize', 'enhancePrompt'}
    if set(settings) - allowed:
        raise ValueError('Unsupported settings for selected model')
    aspect, resolution = settings.get('aspectRatio', '9:16'), settings.get('resolution', '720p')
    if aspect not in ('16:9', '9:16', '1:1') or resolution not in ('720p', '1080p'):
        raise ValueError('Unsupported aspect ratio or resolution')
    normalized = {'aspectRatio': aspect, 'resolution': resolution}
    if MODELS[model] == 'video':
        duration = settings.get('duration', 5)
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 3 <= duration <= 15:
            raise ValueError('Video duration must be finite and between 3 and 15 seconds')
        normalized['duration'] = duration
    else:
        if settings.get('batchSize', '1') != '1' or settings.get('enhancePrompt', False) is not False:
            raise ValueError('Review handoffs use one image and unmodified prompts')
        normalized.update(batchSize='1', enhancePrompt=False)
    plane = {'model': model, 'prompt': {'text': prompt}, 'media': {}, 'settings': normalized}
    binding = {'project_id': data['project_id'], 'scene_id': data['scene_id'], 'plane': plane,
               'upstream_revision': REVISION}
    return result('open-higgsfield', 'prepare-generation',
        handoff=binding, request_sha256=json_digest(binding), media_kind=MODELS[model],
        runtime_status='GENERATION_DISABLED', upstream_source_license='NO_LICENSE_FOUND',
        scope='Validated text-only handoff for manual review; no request submitted, key saved, or asset generated')


def validate_export(data):
    require_disabled(data)
    if set(data) - {'preparation', 'export', 'publication_enabled', 'paid_generation_enabled'}:
        raise ValueError('Unsupported export intake option')
    prepared = prepare_generation(data.get('preparation'))
    exported = data.get('export')
    if not isinstance(exported, dict) or set(exported) != {'path', 'sha256', 'request_sha256', 'media_type'}:
        raise ValueError('Explicit local path, digest, request binding and media_type required')
    if exported['request_sha256'] != prepared['request_sha256']:
        raise ValueError('Export is bound to another request')
    if not isinstance(exported['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', exported['sha256']):
        raise ValueError('Expected lowercase SHA-256 digest')
    allowed = ('video/mp4',) if prepared['media_kind'] == 'video' else ('image/png', 'image/jpeg', 'image/webp')
    if exported['media_type'] not in allowed:
        raise ValueError('Media type does not match requested generation kind')
    raw = read_bytes(exported['path'], 64 * 1024 * 1024)
    if digest(raw) != exported['sha256']:
        raise ValueError('Export digest does not match local bytes')
    mime = exported['media_type']
    signatures = {
        'image/png': raw.startswith(b'\x89PNG\r\n\x1a\n'),
        'image/jpeg': raw.startswith(b'\xff\xd8\xff'),
        'image/webp': raw.startswith(b'RIFF') and raw[8:12] == b'WEBP',
        'video/mp4': len(raw) >= 16 and raw[4:8] == b'ftyp',
    }
    if not signatures[mime]:
        raise ValueError('Export container signature does not match declared media type')
    # Header recognition and a matching digest are deliberately not decode or
    # generation evidence. Existing Content Control decode/creative QA owns that.
    return result('open-higgsfield', 'validate-export', candidate={
        'project_id': prepared['handoff']['project_id'], 'scene_id': prepared['handoff']['scene_id'],
        'kind': prepared['media_kind'], 'media_type': mime, 'size_bytes': len(raw),
        'local_path': str(Path(exported['path']).absolute()), 'revalidate_before_use': True,
        'sha256': digest(raw), 'request_sha256': prepared['request_sha256'],
        'state': 'PENDING_MEDIA_DECODE_AND_REVIEW', 'full_decode_verified': False,
        'source_generation_verified': False, 'source_attestation': 'caller_supplied',
        'upstream_revision': REVISION},
        required_reviews=['full_media_decode', 'visual_and_audio_quality', 'prompt_fidelity',
                          'source_and_output_rights', 'creative'],
        scope='Local file identity, container signature and caller request binding only; no source or quality certification')


def dispatch(job, upstream=None):
    require_disabled(job)
    if job.get('tool') != 'open-higgsfield':
        raise ValueError('Expected open-higgsfield tool')
    operation = job.get('operation')
    if operation == 'status':
        return result('open-higgsfield', operation,
            upstream_revision=REVISION, runtime_status='GENERATION_NOT_CONFIGURED',
            source_status='STATICALLY_REVIEWED_NOT_EXECUTED_OR_VENDORED',
            supported_operations=['status', 'prepare-generation', 'validate-export'],
            supported_handoff_models=list(MODELS),
            blockers=['No upstream LICENSE found', 'Generation requires a platform key and may incur provider charges',
                      'Public media uploads require separate approval and an authenticated upload boundary'],
            scope='Only offline preparation/export intake available; generation and publication disabled')
    if operation not in ('prepare-generation', 'validate-export'):
        raise ValueError('Unsupported OpenHiggsfield operation')
    data = read_json(job.get('input'))
    return prepare_generation(data) if operation == 'prepare-generation' else validate_export(data)
