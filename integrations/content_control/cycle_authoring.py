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
from urllib.parse import urlsplit

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
LONG_FORM_ALGORITHM_V1 = 'source-claim-longform-scenes-v1'
LONG_FORM_ALGORITHM = 'source-claim-longform-scenes-v2'
LONG_FORM_FORMAT = 'long-form'
LONG_FORM_MIN_SECONDS = 120
SPEAKERS = ['narrator', 'dave', 'points_monk', 'narrator']

UTILIZATION_SOURCE_RULES = (
    ('fico_utilization',
     'www.myfico.com', '/credit-education/credit-scores/fico-scores-credit-limit',
     ('fico describes revolving utilization as the outstanding balance divided by the '
      'credit limit and says lower utilization generally indicates lower repayment risk'),
     ('credit utilization rate is calculated by dividing an account s outstanding '
      'balance by its credit limit')),
    ('experian_reporting',
     'www.experian.com',
     '/blogs/ask-experian/credit-education/score-basics/credit-utilization-rate/',
     ('experian says issuers generally report balances around the end of a statement '
      'period so an earlier payment can reduce the reported balance used in utilization '
      'calculations'),
     ('credit card issuers generally report your account s balance to the credit '
      'bureaus at the end of each statement period')),
    ('cfpb_grace_period',
     'www.consumerfinance.gov',
     '/ask-cfpb/what-is-a-grace-period-for-a-credit-card-en-47/',
     ('cfpb distinguishes the billing cycle end from the payment due date and explains '
      'that paying the full balance by the due date can preserve a purchase grace period '
      'when one applies'),
     ('a grace period is the period between the end of a billing cycle and the date '
      'your payment is due')),
)


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


def _complete_title(value, limit=120):
    """Return bounded title copy without an ellipsis or dangling connector."""
    value = ' '.join(value.split()).strip(' ,;:-')
    require(value, 'Authoring requires a nonempty title')
    if len(value) <= limit:
        return value
    clipped = value[:limit].rsplit(' ', 1)[0].rstrip(' ,;:-')
    dangling = {'a', 'an', 'and', 'as', 'at', 'because', 'but', 'by', 'even',
                'for', 'from', 'if', 'in', 'of', 'on', 'or', 'the', 'to',
                'when', 'while', 'with', 'without'}
    while clipped and clipped.rsplit(' ', 1)[-1].lower() in dangling:
        clipped = clipped.rsplit(' ', 1)[0].rstrip(' ,;:-')
    require(clipped and len(clipped) <= limit,
            'Authoring could not create complete bounded title copy')
    return clipped


def _semantic_text(value, minimum, maximum):
    """Return bounded punctuation-insensitive source prose, or None."""
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        return None
    normalized = ' '.join(re.sub(r'[^a-z0-9]+', ' ', value.casefold()).split())
    return normalized or None


def _canonical_https_location(value, host, path):
    """Match one credential-free canonical HTTPS host/path, without URL extras."""
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (parsed.scheme == 'https' and parsed.netloc == host
            and parsed.hostname == host and port is None
            and parsed.username is None and parsed.password is None
            and parsed.path == path and not parsed.query and not parsed.fragment)


def _verified_utilization_source_set(sources):
    """Require exact source order, canonical URLs, and bounded supporting prose.

    The specialized script contains concrete facts that must never be selected by
    caller-controlled source IDs alone.  Any mismatch falls back to generic
    source-bound authoring instead of activating those facts.
    """
    if not isinstance(sources, list) or len(sources) != len(UTILIZATION_SOURCE_RULES):
        return False
    if [source.get('id') for source in sources if isinstance(source, dict)] \
            != [rule[0] for rule in UTILIZATION_SOURCE_RULES]:
        return False
    for source, (identifier, host, path, canonical_claim, canonical_excerpt) in zip(
            sources, UTILIZATION_SOURCE_RULES):
        if (not isinstance(source, dict) or source.get('id') != identifier
                or not _canonical_https_location(source.get('url'), host, path)):
            return False
        claim = _semantic_text(source.get('claim'), 80, 500)
        excerpt = _semantic_text(source.get('excerpt'), 50, 300)
        if claim is None or excerpt is None:
            return False
        # Punctuation and whitespace may normalize, but additional or missing
        # prose cannot activate hard-coded facts. This binds the specialization
        # to the retained evidence text rather than caller-supplied keywords.
        if claim != canonical_claim or excerpt != canonical_excerpt:
            return False
    return True


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


def _long_form_scenes_v1(topic, first, second):
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


def _utilization_long_form(sources):
    """Author a source-bound utilization story with visible math and chronology."""
    by_id = {source['id']: source for source in sources}
    fico = by_id['fico_utilization']
    reporting = by_id['experian_reporting']
    grace = by_id['cfpb_grace_period']
    shared = [fico['id'], reporting['id'], grace['id']]
    return 'Paid in Full. Why Did 50% Report?', [
        {'id': 'paid_but_reported',
         'narration': ('You paid in full by the due date. So why could the earlier '
                       'statement snapshot still show fifty percent utilization? '
                       'Because the closing date and due date answer different questions.'),
         'visual': 'Narrator separates the reporting snapshot from the later payment deadline.',
         'visual_spec': {'kind': 'comparison', 'headline': 'TWO DATES. TWO JOBS.',
                         'labels': ['STATEMENT CLOSE', 'PAYMENT DUE'],
                         'values': ['REPORTING SNAPSHOT', 'PAYMENT DEADLINE'],
                         'gesture': 'open_hands'},
         'source_ids': shared, 'factual': True, 'speaker': 'narrator',
         'duration_seconds': 16},
        {'id': 'utilization_formula',
         'narration': ('Dave starts with the formula from the scoring source: '
                       'reported balance divided by credit limit. Five hundred dollars '
                       'divided by one thousand dollars is fifty percent.'),
         'visual': 'Dave writes the utilization formula and a complete numerical example.',
         'visual_spec': {'kind': 'receipt', 'headline': 'FICO UTILIZATION MATH',
                         'labels': ['REPORTED BALANCE', 'CREDIT LIMIT', 'UTILIZATION'],
                         'values': ['$500', '$1,000', '50%'],
                         'gesture': 'point_left'},
         'source_ids': [fico['id']], 'factual': True, 'speaker': 'dave',
         'duration_seconds': 18},
        {'id': 'reporting_timeline',
         'narration': ('Points Monk follows the issuer reporting timeline. A purchase posts, '
                       'the statement period ends, and the balance around that close can be '
                       'the balance sent to the credit bureaus.'),
         'visual': 'Points Monk advances a three-step reporting timeline labeled with the source.',
         'visual_spec': {'kind': 'card', 'headline': 'EXPERIAN: REPORTING TIMELINE',
                         'labels': ['PURCHASE POSTS', 'STATEMENT CLOSE', 'BALANCE REPORTED'],
                         'values': [], 'gesture': 'point_right'},
         'source_ids': [reporting['id']], 'factual': True, 'speaker': 'points_monk',
         'duration_seconds': 18},
        {'id': 'date_difference',
         'narration': ('The consumer protection source defines the grace period between '
                       'the end of a billing cycle and the payment due date. That confirms '
                       'the close and the due date are separate moments.'),
         'visual': 'Narrator labels the billing-cycle end and later due date without blending them.',
         'visual_spec': {'kind': 'comparison', 'headline': 'CFPB: THE DATES DIFFER',
                         'labels': ['BILLING CYCLE ENDS', 'PAYMENT IS DUE'],
                         'values': ['STATEMENT CLOSE', 'LATER DEADLINE'],
                         'gesture': 'open_hands'},
         'source_ids': [grace['id']], 'factual': True, 'speaker': 'narrator',
         'duration_seconds': 17},
        {'id': 'wrong_assumption',
         'narration': ('Dave catches the common mix-up. Paying in full by the due date can '
                       'protect a grace period when one applies, but it does not rewrite a '
                       'balance snapshot that was already taken at statement close.'),
         'visual': 'Dave contrasts a due-date payment with the earlier statement balance.',
         'visual_spec': {'kind': 'comparison', 'headline': 'PAYMENT DOES NOT REWIND TIME',
                         'labels': ['PAID BY DUE DATE', 'BALANCE AT CLOSE'],
                         'values': ['GRACE-PERIOD QUESTION', 'REPORTING QUESTION'],
                         'gesture': 'point_left'},
         'source_ids': [reporting['id'], grace['id']], 'factual': True,
         'speaker': 'dave', 'duration_seconds': 18},
        {'id': 'earlier_payment',
         'narration': ('Points Monk uses the reporting source carefully. An earlier payment '
                       'can reduce the balance present when the issuer reports, which can '
                       'reduce the utilization produced by the same formula.'),
         'visual': 'Points Monk moves an earlier payment ahead of the statement close.',
         'visual_spec': {'kind': 'card', 'headline': 'PAY BEFORE THE SNAPSHOT',
                         'labels': ['BEFORE PAYMENT', 'EARLIER PAYMENT', 'AT STATEMENT CLOSE'],
                         'values': ['$500', '-$400', '$100'],
                         'gesture': 'point_right'},
         'source_ids': [fico['id'], reporting['id']], 'factual': True,
         'speaker': 'points_monk', 'duration_seconds': 18},
        {'id': 'worked_example',
         'narration': ('Now run the same arithmetic. Five hundred divided by one thousand is '
                       'fifty percent. One hundred divided by one thousand is ten percent. '
                       'The credit limit never changed; the reported balance did.'),
         'visual': 'Narrator compares both complete utilization calculations side by side.',
         'visual_spec': {'kind': 'comparison', 'headline': 'SAME LIMIT. NEW SNAPSHOT.',
                         'labels': ['$500 / $1,000', '$100 / $1,000'],
                         'values': ['50%', '10%'], 'gesture': 'open_hands'},
         'source_ids': [fico['id'], reporting['id']], 'factual': True,
         'speaker': 'narrator', 'duration_seconds': 18},
        {'id': 'no_score_promise',
         'narration': ('Dave draws the boundary. These sources explain utilization and '
                       'reporting timing. They do not promise a particular score change, '
                       'and different account reporting details still need verification.'),
         'visual': 'Dave marks the factual boundary and rejects a score-points promise.',
         'visual_spec': {'kind': 'checklist', 'headline': 'WHAT THIS DOES NOT PROMISE',
                         'labels': ['NO SCORE-POINT GUARANTEE', 'VERIFY YOUR ACCOUNT'],
                         'values': [], 'gesture': 'point_left'},
         'source_ids': [fico['id'], reporting['id']], 'factual': True,
         'speaker': 'dave', 'duration_seconds': 16},
        {'id': 'source_map',
         'narration': ('Points Monk keeps every claim attached to its source: the utilization '
                       'formula from FICO, reporting timing from the issuer education source, '
                       'and the grace-period definition from the consumer bureau.'),
         'visual': 'Points Monk reveals the three source identities and their distinct roles.',
         'visual_spec': {'kind': 'receipt', 'headline': 'THREE SOURCES. THREE CLAIMS.',
                         'labels': ['FICO', 'EXPERIAN', 'CFPB'],
                         'values': ['FORMULA', 'REPORTING', 'GRACE PERIOD'],
                         'gesture': 'point_right'},
         'source_ids': shared, 'factual': True, 'speaker': 'points_monk',
         'duration_seconds': 18},
        {'id': 'closing_actions',
         'narration': ('The practical check is simple. Find the statement closing date, '
                       'inspect the balance likely to report, and choose payment timing '
                       'deliberately. Then review the actual statement instead of guessing.'),
         'visual': 'Narrator closes with Dave and Points Monk beside a dated action checklist.',
         'visual_spec': {'kind': 'checklist', 'headline': 'CHECK BEFORE THE CLOSE',
                         'labels': ['FIND THE CLOSE DATE', 'CHECK THE BALANCE',
                                    'VERIFY THE STATEMENT'],
                         'values': [], 'gesture': 'open_hands'},
         'source_ids': shared, 'factual': True, 'speaker': 'narrator',
         'duration_seconds': 18},
    ]


def _long_form_scenes(topic, sources):
    if _verified_utilization_source_set(sources):
        return _utilization_long_form(sources)
    first, second = sources[:2]
    return _complete_title(f'{topic}: two source checks'), _long_form_scenes_v1(
        topic, first, second)


def _build(research_raw, discovery, content_format='standard', *, algorithm=None):
    research = json.loads(research_raw.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=_constant)
    require(isinstance(research, dict)
            and set(research) == {'schema_version', 'topic', 'sources', 'reference_observations'}
            and type(research.get('schema_version')) is int and research['schema_version'] == 1,
            'Authoring requires exact discovery research fields')
    require(len(research['sources']) >= 2, 'Authoring requires at least two verified sources')
    first, second = research['sources'][:2]
    if content_format == 'standard':
        require(algorithm in (None, ALGORITHM), 'Standard authoring algorithm mismatch')
        topic = _short(research['topic'], 88)
        title = _short(f'{topic}: what two sources show', 120)
        thumbnail_copy = _short(topic, 48)
        scenes = _standard_scenes(topic, first, second)
        algorithm, status = ALGORITHM, 'OFFLINE_DRAFT_AUTHORED'
    elif content_format == LONG_FORM_FORMAT:
        if algorithm == LONG_FORM_ALGORITHM_V1:
            topic = _short(research['topic'], 88)
            title = _short(f'{topic}: what two sources show', 120)
            thumbnail_copy = _short(topic, 48)
            scenes = _long_form_scenes_v1(topic, first, second)
        else:
            require(algorithm in (None, LONG_FORM_ALGORITHM),
                    'Long-form authoring algorithm mismatch')
            topic = _complete_title(research['topic'], 88)
            title, scenes = _long_form_scenes(topic, research['sources'])
            thumbnail_copy = _complete_title(title, 48)
            algorithm = LONG_FORM_ALGORITHM
        status = 'OFFLINE_LONGFORM_DRAFT_AUTHORED'
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
             'title': title, 'thumbnail_copy': thumbnail_copy, 'layout': 'landscape',
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
    elif algorithm in (LONG_FORM_ALGORITHM_V1, LONG_FORM_ALGORITHM):
        content_format = LONG_FORM_FORMAT
    else:
        raise ValueError('Authored draft requires a recognized replay algorithm')
    expected_raw, proof = _build(research_raw, discovery, content_format,
                                 algorithm=algorithm)
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
