"""Compile supplied evidence and an original scene brief into production inputs.

This module never fetches URLs, invents research, or grants factual/creative
approval. Evidence provenance remains distinguishable from audiovisual review.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from urllib.parse import urlsplit


FALSE_FLAGS = ('publication_enabled', 'paid_generation_enabled',
               'production_approved', 'full_av_review', 'factual_review',
               'production_ready', 'competitor_comparison')
OBSERVATION_TYPES = {'transcript', 'audiovisual', 'metadata'}
VISUAL_KINDS = {'card', 'receipt', 'balance', 'checklist', 'comparison'}
SPEAKERS = {'narrator', 'dave', 'points_monk'}


def _text(value, name, maximum, *, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError(f'{name}: nonempty text up to {maximum} characters required')
    if any(ord(char) < 32 and char not in '\n\t' for char in value):
        raise ValueError(f'{name}: control characters forbidden')
    return value.strip()


def _identifier(value, name):
    value = _text(value, name, 80)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value):
        raise ValueError(f'{name}: safe identifier required')
    return value


def normalize_thumbnail_copy(value):
    """Validate literal display text and retain one canonical space between words."""
    if not isinstance(value, str) or not value.isprintable():
        raise ValueError('thumbnail_copy: printable single-line text required')
    return _text(' '.join(value.split()), 'thumbnail_copy', 48)


def _url(value, name):
    value = _text(value, name, 2048)
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'https' and parsed.hostname and
                 not parsed.username and not parsed.password and
                 not any(char.isspace() for char in value))
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f'{name}: credential-free HTTPS URL required')
    return value


def _timestamp(value, name):
    value = _text(value, name, 64)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError(f'{name}: ISO timestamp required') from error
    if parsed.tzinfo is None:
        raise ValueError(f'{name}: explicit timezone required')
    if parsed > datetime.now(timezone.utc):
        raise ValueError(f'{name}: future evidence forbidden')
    return parsed.astimezone(timezone.utc).isoformat()


def _list(value, name, minimum, maximum):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f'{name}: {minimum}–{maximum} entries required')
    return value


def _flags(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FALSE_FLAGS and item is not False:
                raise ValueError(f'{key}: must remain false')
            _flags(item)
    elif isinstance(value, list):
        for item in value:
            _flags(item)


def compile_editorial(brief, *, validate_visual_shapes=False):
    """Return deterministic normalized editorial inputs; fail closed on gaps.

    Default normalization preserves historical immutable cycle identities. New
    production opts into renderer shape checks before any voice work.

    Factual scenes require source IDs. Explicit ``factual: false`` is available
    for fictional character dialogue; this declaration is not independently
    fact checked. Scene duration is a planning target, not a measured TTS length.
    """
    if not isinstance(brief, dict) or type(brief.get('schema_version')) is not int or brief['schema_version'] != 1:
        raise ValueError('schema_version: integer 1 required')
    _flags(brief)
    if 'layout' in brief and brief['layout'] != 'landscape':
        raise ValueError('layout: omit for portrait or set landscape')
    title = _text(brief.get('title'), 'title', 120)
    topic = _text(brief.get('topic'), 'topic', 500)
    sources, source_ids = [], set()
    for item in _list(brief.get('sources'), 'sources', 1, 40):
        if not isinstance(item, dict):
            raise ValueError('sources: objects required')
        identifier = _identifier(item.get('id'), 'source.id')
        if identifier in source_ids:
            raise ValueError('source.id: duplicate')
        source_ids.add(identifier)
        sources.append({'id': identifier, 'url': _url(item.get('url'), 'source.url'),
                        'retrieved_at': _timestamp(item.get('retrieved_at'), 'source.retrieved_at'),
                        'claim': _text(item.get('claim'), 'source.claim', 2000),
                        'excerpt': _text(item.get('excerpt'), 'source.excerpt', 4000)})
    references = []
    for item in _list(brief.get('reference_observations'), 'reference_observations', 1, 20):
        if not isinstance(item, dict):
            raise ValueError('reference_observations: objects required')
        kind = item.get('observation_type')
        if kind not in OBSERVATION_TYPES:
            raise ValueError('observation_type: transcript, audiovisual, or metadata required')
        references.append({'url': _url(item.get('url'), 'reference.url'),
                           'observed_at': _timestamp(item.get('observed_at'), 'reference.observed_at'),
                           'observation_type': kind,
                           'patterns': [_text(pattern, 'reference.pattern', 500)
                                        for pattern in _list(item.get('patterns'), 'reference.patterns', 1, 12)]})
    scenes, scene_ids, cursor = [], set(), 0.0
    for item in _list(brief.get('scenes'), 'scenes', 1, 30):
        if not isinstance(item, dict):
            raise ValueError('scenes: objects required')
        identifier = _identifier(item.get('id'), 'scene.id')
        if identifier in scene_ids:
            raise ValueError('scene.id: duplicate')
        scene_ids.add(identifier)
        factual = item.get('factual', True)
        if type(factual) is not bool:
            raise ValueError('scene.factual: boolean required')
        citations = _list(item.get('source_ids'), 'scene.source_ids', int(factual), 40)
        if any(not isinstance(citation, str) or citation not in source_ids for citation in citations):
            raise ValueError('scene.source_ids: unknown source')
        if len(citations) != len(set(citations)):
            raise ValueError('scene.source_ids: duplicate source')
        duration = item.get('duration_seconds')
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 1 <= duration <= 60:
            raise ValueError('scene.duration_seconds: finite number between 1 and 60 required')
        duration = float(duration)
        speaker = _identifier(item.get('speaker', 'narrator'), 'scene.speaker')
        if speaker not in SPEAKERS:
            raise ValueError('scene.speaker: narrator, dave, or points_monk required')
        scene = {'id': identifier, 'narration': _text(item.get('narration'), 'scene.narration', 1000),
                 'visual': _text(item.get('visual'), 'scene.visual', 1000),
                 'source_ids': list(citations), 'factual': factual,
                 'speaker': speaker,
                 'duration_seconds': duration, 'start_seconds': round(cursor, 6),
                 'end_seconds': round(cursor + duration, 6)}
        if 'visual_spec' in item:
            spec = item['visual_spec']
            if not isinstance(spec, dict) or spec.get('kind') not in VISUAL_KINDS:
                raise ValueError('scene.visual_spec.kind: supported visual kind required')
            scene['visual_spec'] = {
                'kind': spec['kind'],
                'headline': _text(spec.get('headline'), 'scene.visual_spec.headline', 60),
                'labels': [_text(label, 'scene.visual_spec.label', 50)
                           for label in _list(spec.get('labels', []), 'scene.visual_spec.labels', 0, 4)],
                'values': [_text(value, 'scene.visual_spec.value', 30)
                           for value in _list(spec.get('values', []), 'scene.visual_spec.values', 0, 4)]}
            if 'reveal_after_seconds' in spec:
                scene['visual_spec']['reveal_after_seconds'] = spec['reveal_after_seconds']
        if validate_visual_shapes or 'reveal_after_seconds' in scene.get('visual_spec', {}):
            from integrations.content_control.cycle_render import validate_visual_shape
            validate_visual_shape(scene.get('visual_spec', {}))
        cursor += duration
        scenes.append(scene)
    if cursor > 600:
        raise ValueError('scene.duration_seconds: total planning duration exceeds 600 seconds')
    result = {'schema_version': 1, 'status': 'EDITORIAL_INPUTS_VALIDATED',
              'title': title, 'topic': topic, 'sources': sources,
              'reference_observations': references, 'scenes': scenes,
              'script_text': '\n\n'.join(scene['narration'] for scene in scenes),
              'storyboard': [{'scene_id': scene['id'], 'visual': scene['visual'],
                             'start_seconds': scene['start_seconds'], 'end_seconds': scene['end_seconds']}
                            for scene in scenes],
              'planned_duration_seconds': round(cursor, 6),
              'reference_scope': sorted({reference['observation_type'] for reference in references}),
              'reference_audiovisual_comparison_complete': False,
              'independent_fact_check_complete': False, 'originality_review_complete': False,
              'factual_review': False,
              'research_scope': 'Supplied source excerpts and URLs; not fetched or independently fact checked by this compiler.',
              'script_scope': 'Supplied original scene brief; this compiler does not autonomously research or write a new script.',
              'publication_enabled': False, 'paid_generation_enabled': False,
              'production_approved': False, 'full_av_review': False}
    if 'thumbnail_copy' in brief:
        result['thumbnail_copy'] = normalize_thumbnail_copy(brief['thumbnail_copy'])
    if 'layout' in brief:
        result['layout'] = 'landscape'
    result['editorial_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':'),
                                                         allow_nan=False).encode()).hexdigest()
    return result
