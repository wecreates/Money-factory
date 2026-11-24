"""Create a deterministic offline script/storyboard draft from verified discovery.

The author does not fetch sources, call a model, or claim factual, originality,
creative, audiovisual, or audience approval.  It turns the exact selected
research into a replayable first draft while retaining the existing narrator,
Dave, and Points Monk voice assignments.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from integrations.content_control.cycle_discovery import (
    MAX_POOL, MAX_RECEIPT, verify_inline_selection,
)
from integrations.content_control.cycle_editorial import (
    FALSE_FLAGS, authored_content_sha, compile_editorial,
)
from integrations.content_control.cycle_intake import MAX_INPUT
from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.cycle_review import _regular
from integrations.content_control.review_package import no_symlinks, require


ALGORITHM = 'source-claim-scenes-v1'
LONG_FORM_ALGORITHM = 'source-claim-longform-scenes-v1'
LONG_FORM_FORMAT = 'long-form'
LONG_FORM_MIN_SECONDS = 120
SPEAKERS = ['narrator', 'dave', 'points_monk', 'narrator']


def _read(path, limit):
    path = Path(os.path.abspath(path))
    with _regular(path, limit).open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'Authoring input exceeds its byte limit')
    return raw


def _json(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def _short(value, limit):
    value = ' '.join(value.split())
    require(value, 'Authoring requires nonempty source text')
    if len(value) <= limit:
        return value
    clipped = value[:limit].rsplit(' ', 1)[0].rstrip(' ,;:-')
    if not clipped or len(clipped) >= limit:
        clipped = value[:limit - 1].rstrip(' ,;:-')
    return clipped + '…'


def _standard_scenes(topic, first, second):
    first_claim, second_claim = _short(first['claim'], 260), _short(second['claim'], 260)
    return [
        {'id': 'hook', 'narration': f'Start with the decision, not the hype: {topic}.',
         'visual': 'Narrator opens beside a black-and-white decision board; the topic appears as kinetic type.',
         'visual_spec': {'kind': 'card', 'headline': 'The decision', 'labels': ['Evidence first'],
                         'values': [], 'gesture': 'point_right'},
         'source_ids': [first['id']], 'factual': True, 'speaker': 'narrator', 'duration_seconds': 7},
        {'id': 'dave_check', 'narration': f'Dave checks the first constraint. {first_claim}',
         'visual': 'Debit Card Dave points at the first source card and highlights its practical constraint.',
         'visual_spec': {'kind': 'receipt', 'headline': 'First constraint', 'labels': ['Source one'],
                         'values': [], 'gesture': 'point_right'},
         'source_ids': [first['id']], 'factual': True, 'speaker': 'dave', 'duration_seconds': 8},
        {'id': 'monk_check', 'narration': f'Points Monk checks the counterweight. {second_claim}',
         'visual': 'Points Monk enters on the opposite side and reveals the second source card for comparison.',
         'visual_spec': {'kind': 'comparison', 'headline': 'Counterweight',
                         'labels': ['Source one', 'Source two'], 'values': ['Check', 'Compare'],
                         'reveal_on_phrase': second_claim, 'gesture': 'point_right'},
         'source_ids': [second['id']], 'factual': True, 'speaker': 'points_monk', 'duration_seconds': 8},
        {'id': 'takeaway',
         'narration': f'Now compare both before you act. First: {first_claim} Second: {second_claim}',
         'visual': 'The narrator closes with Dave and Points Monk beside a two-column evidence checklist.',
         'visual_spec': {'kind': 'checklist', 'headline': 'Compare before acting',
                         'labels': ['First source', 'Second source'], 'values': [],
                         'gesture': 'point_right'},
         'source_ids': [first['id'], second['id']], 'factual': True,
         'speaker': 'narrator', 'duration_seconds': 9},
    ]


def _long_form_scenes(topic, first, second):
    """Build a replayable >60-second source-bound manuscript/storyboard draft."""
    first_claim, second_claim = _short(first['claim'], 360), _short(second['claim'], 360)
    shared = [first['id'], second['id']]
    return [
        {'id': 'opening_decision',
         'narration': f'Before the numbers blur together, name the decision: {topic}. This walkthrough separates the two constraints the sources actually support.',
         'visual': 'Narrator opens on a landscape evidence board with two covered source columns.',
         'visual_spec': {'kind': 'card', 'headline': 'Name the decision', 'labels': ['Two constraints'],
                         'values': [], 'gesture': 'point_right'},
         'source_ids': shared, 'factual': True, 'speaker': 'narrator', 'duration_seconds': 15},
        {'id': 'first_source', 'narration': f'Dave opens the first source. {first_claim}',
         'visual': 'Debit Card Dave reveals the first evidence card and underlines its stated constraint.',
         'visual_spec': {'kind': 'receipt', 'headline': 'Source one', 'labels': ['Stated constraint'],
                         'values': [], 'gesture': 'point_right'},
         'source_ids': [first['id']], 'factual': True, 'speaker': 'dave', 'duration_seconds': 18},
        {'id': 'second_source', 'narration': f'Points Monk opens the second source. {second_claim}',
         'visual': 'Points Monk reveals the second evidence card on the opposite side of the board.',
         'visual_spec': {'kind': 'receipt', 'headline': 'Source two', 'labels': ['Counterweight'],
                         'values': [], 'gesture': 'point_right'},
         'source_ids': [second['id']], 'factual': True, 'speaker': 'points_monk', 'duration_seconds': 18},
        {'id': 'evidence_map',
         'narration': 'Put the claims side by side. One source defines the first boundary; the other supplies a separate boundary. Neither substitutes for the other.',
         'visual': 'Narrator places both source cards into a two-column evidence map.',
         'visual_spec': {'kind': 'comparison', 'headline': 'Two boundaries',
                         'labels': ['Source one', 'Source two'], 'values': ['First', 'Second'],
                         'gesture': 'point_right'},
         'source_ids': shared, 'factual': True, 'speaker': 'narrator', 'duration_seconds': 15},
        {'id': 'dave_example',
         'narration': f'Dave tests a practical reading of the first constraint without adding a new fact: {first_claim}',
         'visual': 'Dave moves the first source card into a simple decision checklist.',
         'visual_spec': {'kind': 'checklist', 'headline': 'Test source one',
                         'labels': ['Read', 'Check', 'Retain'], 'values': [], 'gesture': 'point_right'},
         'source_ids': [first['id']], 'factual': True, 'speaker': 'dave', 'duration_seconds': 18},
        {'id': 'monk_example',
         'narration': f'Points Monk tests the second constraint on its own terms: {second_claim}',
         'visual': 'Points Monk moves the second source card into a matching decision checklist.',
         'visual_spec': {'kind': 'checklist', 'headline': 'Test source two',
                         'labels': ['Read', 'Check', 'Retain'], 'values': [], 'gesture': 'point_right'},
         'source_ids': [second['id']], 'factual': True, 'speaker': 'points_monk', 'duration_seconds': 18},
        {'id': 'comparison',
         'narration': 'The comparison is the point: keep each claim attached to its own source, then decide only after both constraints are visible.',
         'visual': 'Narrator aligns the two checklists and highlights their distinct source labels.',
         'visual_spec': {'kind': 'comparison', 'headline': 'Compare, do not blend',
                         'labels': ['Constraint one', 'Constraint two'], 'values': ['Keep', 'Separate'],
                         'gesture': 'point_right'},
         'source_ids': shared, 'factual': True, 'speaker': 'narrator', 'duration_seconds': 15},
        {'id': 'dave_action',
         'narration': 'Dave records the first source, its retrieval date, and the exact claim before acting. That keeps the decision auditable instead of relying on memory.',
         'visual': 'Dave checks source identity, retrieval date, and claim on a receipt-style evidence log.',
         'visual_spec': {'kind': 'receipt', 'headline': 'Retain the evidence',
                         'labels': ['Source', 'Date', 'Claim'], 'values': [], 'gesture': 'point_right'},
         'source_ids': [first['id']], 'factual': True, 'speaker': 'dave', 'duration_seconds': 15},
        {'id': 'monk_action',
         'narration': 'Points Monk repeats the same process for the second source and refuses to turn a separate constraint into a universal promise.',
         'visual': 'Points Monk completes the second evidence log and marks the claims as separate.',
         'visual_spec': {'kind': 'receipt', 'headline': 'Keep claims separate',
                         'labels': ['Source', 'Date', 'Boundary'], 'values': [], 'gesture': 'point_right'},
         'source_ids': [second['id']], 'factual': True, 'speaker': 'points_monk', 'duration_seconds': 15},
        {'id': 'closing_checklist',
         'narration': f'Close with the evidence, not the hype. For {topic}, retain both sources, compare their separate constraints, and send the finished script through factual and creative review.',
         'visual': 'Narrator closes with Dave and Points Monk beside the completed two-source checklist.',
         'visual_spec': {'kind': 'checklist', 'headline': 'Evidence before action',
                         'labels': ['Retain', 'Compare', 'Review'], 'values': [], 'gesture': 'point_right'},
         'source_ids': shared, 'factual': True, 'speaker': 'narrator', 'duration_seconds': 18},
    ]


def _build(research_raw, discovery, content_format='standard'):
    research = json.loads(research_raw.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=_constant)
    require(isinstance(research, dict)
            and set(research) == {'schema_version', 'topic', 'sources', 'reference_observations'}
            and type(research.get('schema_version')) is int and research['schema_version'] == 1,
            'Authoring requires exact discovery research fields')
    require(len(research['sources']) >= 2, 'Authoring requires at least two verified sources')
    topic = _short(research['topic'], 88)
    first, second = research['sources'][:2]
    title = _short(f'{topic}: what two sources show', 120)
    if content_format == 'standard':
        scenes = _standard_scenes(topic, first, second)
        algorithm, status = ALGORITHM, 'OFFLINE_DRAFT_AUTHORED'
    elif content_format == LONG_FORM_FORMAT:
        scenes = _long_form_scenes(topic, first, second)
        algorithm, status = LONG_FORM_ALGORITHM, 'OFFLINE_LONGFORM_DRAFT_AUTHORED'
    else:
        raise ValueError('Authoring format must be standard or long-form')
    planned_duration = sum(scene['duration_seconds'] for scene in scenes)
    require(content_format != LONG_FORM_FORMAT or planned_duration >= LONG_FORM_MIN_SECONDS,
            'Long-form authoring must plan at least 120 seconds')
    speaker_sequence = [scene['speaker'] for scene in scenes]
    flags = dict.fromkeys(FALSE_FLAGS, False)
    proof = {'schema_version': 1 if content_format == 'standard' else 2, 'status': status,
             'algorithm': algorithm, 'research_sha256': hashlib.sha256(research_raw).hexdigest(),
             'pool_sha256': discovery['pool_sha256'],
             'discovery_receipt_sha256': discovery['discovery_receipt_sha256'],
             'selected_candidate_id': discovery['selected_candidate_id'],
             'script_storyboard_sha256': authored_content_sha(title, scenes),
             'speaker_sequence': speaker_sequence, 'authorship_verified': False,
             'originality_review_complete': False, **flags,
             'scope': ('Deterministic offline first draft from exact selected source claims. '
                       'No retrieval, model authorship, originality, factual, creative, audiovisual, '
                       'audience, or publication approval claim.')}
    if content_format == LONG_FORM_FORMAT:
        proof.update(content_format=LONG_FORM_FORMAT,
                     planned_duration_seconds=planned_duration,
                     long_form_production_verified=False)
    draft = {'schema_version': 1, 'research_sha256': proof['research_sha256'],
             'title': title, 'thumbnail_copy': _short(topic, 48), 'layout': 'landscape',
             'scenes': scenes, 'original_authoring': proof}
    probe = {**research, **{key: value for key, value in draft.items()
                           if key not in ('schema_version', 'research_sha256')}, **flags,
             'topic_discovery': discovery}
    compile_editorial(probe, validate_visual_shapes=True)
    return _json(draft), proof


def verify_authored_draft(research_raw, draft_raw, discovery):
    """Replay the exact authoring result; edited or substituted drafts fail."""
    require(all(isinstance(value, bytes) for value in (research_raw, draft_raw)),
            'Authoring replay requires exact bytes')
    require(0 < len(research_raw) <= MAX_INPUT and 0 < len(draft_raw) <= MAX_INPUT,
            'Authoring replay exceeds byte limits')
    try:
        supplied = json.loads(draft_raw.decode('utf-8'), object_pairs_hook=_pairs,
                              parse_constant=_constant)
        algorithm = supplied['original_authoring']['algorithm']
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('Authored draft requires a recognized replay algorithm') from error
    if algorithm == ALGORITHM:
        content_format = 'standard'
    elif algorithm == LONG_FORM_ALGORITHM:
        content_format = LONG_FORM_FORMAT
    else:
        raise ValueError('Authored draft requires a recognized replay algorithm')
    expected_raw, proof = _build(research_raw, discovery, content_format)
    require(draft_raw == expected_raw, 'Authored draft does not match the verified research and algorithm')
    return proof


def author_draft(pool_path, research_path, discovery_receipt, output, *, content_format='standard'):
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    output = Path(os.path.abspath(output))
    no_symlinks(output)
    require(not output.exists(), 'Fresh authoring output file required')
    pool_raw = _read(pool_path, MAX_POOL)
    research_raw = _read(research_path, MAX_INPUT)
    receipt_raw = _read(discovery_receipt, MAX_RECEIPT)
    discovery = verify_inline_selection(pool_raw, research_raw, receipt_raw)
    draft_raw, proof = _build(research_raw, discovery, content_format)
    require(_read(pool_path, MAX_POOL) == pool_raw
            and _read(research_path, MAX_INPUT) == research_raw
            and _read(discovery_receipt, MAX_RECEIPT) == receipt_raw,
            'Discovery evidence changed during authoring')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(draft_raw)
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool', required=True)
    parser.add_argument('--research', required=True)
    parser.add_argument('--discovery-receipt', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--format', dest='content_format', choices=('standard', LONG_FORM_FORMAT),
                        default='standard')
    args = parser.parse_args()
    print(json.dumps(author_draft(args.pool, args.research, args.discovery_receipt, args.output,
                                  content_format=args.content_format), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
