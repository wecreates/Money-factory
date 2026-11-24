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


def _build(research_raw, discovery):
    research = json.loads(research_raw.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=_constant)
    require(isinstance(research, dict)
            and set(research) == {'schema_version', 'topic', 'sources', 'reference_observations'}
            and type(research.get('schema_version')) is int and research['schema_version'] == 1,
            'Authoring requires exact discovery research fields')
    require(len(research['sources']) >= 2, 'Authoring requires at least two verified sources')
    topic = _short(research['topic'], 88)
    first, second = research['sources'][:2]
    first_claim, second_claim = _short(first['claim'], 260), _short(second['claim'], 260)
    title = _short(f'{topic}: what two sources show', 120)
    scenes = [
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
    flags = dict.fromkeys(FALSE_FLAGS, False)
    proof = {'schema_version': 1, 'status': 'OFFLINE_DRAFT_AUTHORED',
             'algorithm': ALGORITHM, 'research_sha256': hashlib.sha256(research_raw).hexdigest(),
             'pool_sha256': discovery['pool_sha256'],
             'discovery_receipt_sha256': discovery['discovery_receipt_sha256'],
             'selected_candidate_id': discovery['selected_candidate_id'],
             'script_storyboard_sha256': authored_content_sha(title, scenes),
             'speaker_sequence': SPEAKERS, 'authorship_verified': False,
             'originality_review_complete': False, **flags,
             'scope': ('Deterministic offline first draft from exact selected source claims. '
                       'No retrieval, model authorship, originality, factual, creative, audiovisual, '
                       'audience, or publication approval claim.')}
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
    expected_raw, proof = _build(research_raw, discovery)
    require(draft_raw == expected_raw, 'Authored draft does not match the verified research and algorithm')
    return proof


def author_draft(pool_path, research_path, discovery_receipt, output):
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
    draft_raw, proof = _build(research_raw, discovery)
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
    args = parser.parse_args()
    print(json.dumps(author_draft(args.pool, args.research, args.discovery_receipt, args.output), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
