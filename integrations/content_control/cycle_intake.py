"""Join retained research and a separate script draft into a bound cycle brief."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

from integrations.content_control.cycle_editorial import FALSE_FLAGS, _text, _timestamp, compile_editorial
from integrations.content_control.cycle_job import brief_digest, canonical
from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.cycle_review import _regular
from integrations.content_control.cycle_selection import verify_selection
from integrations.content_control.review_package import no_symlinks, require

RESEARCH_FIELDS = {'schema_version', 'topic', 'sources', 'reference_observations'}
DRAFT_FIELDS = {'schema_version', 'research_sha256', 'title', 'scenes'}
DRAFT_OPTIONS = {'thumbnail_copy', 'layout', 'idea_learning', 'speaker_label_position'}
MAX_INPUT = 128 * 1024
MAX_BRIEF = 256 * 1024


def _input(path, limit=MAX_INPUT):
    with _regular(path, limit).open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'Intake file exceeds its byte limit')
    return raw


def _object(raw, required, options):
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    require(isinstance(value, dict) and required <= value.keys() <= required | options
            and type(value['schema_version']) is int and value['schema_version'] == 1,
            'Unexpected intake fields or schema version')
    return value


def _idea_learning(choice, prior_cycle, selection_path, selection_receipt, output):
    paths = (prior_cycle, selection_path, selection_receipt)
    if choice is None and all(path is None for path in paths):
        return None
    require(isinstance(choice, dict) and set(choice) == {'selection_receipt_sha256', 'hypothesis_index', 'application'}
            and all(path is not None for path in paths),
            'Draft idea learning requires the prior cycle, original selection and receipt')
    require(not output.is_relative_to(Path(os.path.abspath(prior_cycle))),
            'Intake output must be separate from the prior cycle')
    selection, receipt_sha = verify_selection(*paths)
    require(choice['selection_receipt_sha256'] == receipt_sha, 'Draft does not bind this selection receipt')
    index = choice['hypothesis_index']
    hypotheses = selection['next_idea_hypotheses']
    require(type(index) is int and 1 <= index <= len(hypotheses), 'Draft must select a recorded hypothesis')
    return {'selection_receipt_sha256': receipt_sha,
            'prior_candidate_sha256': selection['candidate_sha256'],
            'prior_package_sha256': selection['package_sha256'],
            'prior_thumbnail_sha256': selection['thumbnail_sha256'],
            'hypothesis_index': index, 'hypothesis': hypotheses[index - 1],
            'application': _text(choice['application'], 'idea_learning.application', 2000, minimum=12),
            'prior_performance_status': selection['performance']['status'],
            'audience_performance_verified': False}


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def _compile_intake(research_raw, draft_raw, output, recorded_at, prior_cycle, selection_path, selection_receipt):
    research_data = _object(research_raw, RESEARCH_FIELDS, set())
    draft_data = _object(draft_raw, DRAFT_FIELDS, DRAFT_OPTIONS)
    research_sha = hashlib.sha256(research_raw).hexdigest()
    draft_sha = hashlib.sha256(draft_raw).hexdigest()
    require(draft_data['research_sha256'] == research_sha, 'Draft does not bind these exact research bytes')
    require('idea_learning' not in draft_data or draft_data['idea_learning'] is not None,
            'Draft idea_learning must be an object when supplied')
    learning = _idea_learning(draft_data.get('idea_learning'), prior_cycle, selection_path, selection_receipt, output)
    flags = dict.fromkeys(FALSE_FLAGS, False)
    brief = {**research_data, **{k: v for k, v in draft_data.items()
                               if k not in ('schema_version', 'research_sha256', 'idea_learning')},
             **flags, 'research_handoff': {'research_sha256': research_sha, 'draft_sha256': draft_sha}}
    if learning is not None:
        brief['idea_learning'] = learning
    require(len(canonical(brief).encode()) <= 120000, 'Compiled brief exceeds queue input limit')
    compile_editorial(brief, validate_visual_shapes=True)
    brief_raw = _json_bytes(brief)
    require(len(brief_raw) <= MAX_BRIEF, 'Formatted brief exceeds renderer input limit')
    receipt = {'schema_version': 1, 'status': 'BRIEF_READY_FOR_PRODUCTION', **flags,
               'recorded_at': recorded_at if recorded_at is not None else datetime.now(timezone.utc).isoformat(),
               'research_sha256': research_sha, 'draft_sha256': draft_sha,
               'brief_sha256': hashlib.sha256(brief_raw).hexdigest(), 'queue_brief_sha256': brief_digest(brief),
               'source_ids': [source['id'] for source in brief['sources']],
               'scope': 'Supplied-source and draft handoff. Source retrieval, factual review and authorship are separate evidence.'}
    if learning is not None:
        receipt['idea_learning'] = learning
    return brief_raw, receipt


def prepare_brief(research_path, draft_path, output, *, prior_cycle=None, selection_path=None, selection_receipt=None):
    """Bind exact source bytes; the draft cannot add or replace research records."""
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')), 'Publishing and paid generation must remain disabled')
    research, draft, output = (Path(os.path.abspath(path)) for path in (research_path, draft_path, output))
    no_symlinks(output)
    require(not output.exists(), 'Fresh intake output directory required')
    research_raw, draft_raw = _input(research), _input(draft)
    brief_raw, receipt = _compile_intake(research_raw, draft_raw, output, None,
                                         prior_cycle, selection_path, selection_receipt)
    require(_input(research) == research_raw and _input(draft) == draft_raw, 'Intake inputs changed')
    output.mkdir(parents=True, exist_ok=False)
    try:
        with (output / 'brief.json').open('xb') as stream:
            stream.write(brief_raw)
        with (output / 'intake.json').open('xb') as stream:
            stream.write(_json_bytes(receipt))
    except BaseException:
        shutil.rmtree(output)
        raise
    return receipt


def verify_intake(research_path, draft_path, intake_dir, *, prior_cycle=None, selection_path=None,
                  selection_receipt=None):
    """Rebuild the brief and receipt from retained inputs without writing files."""
    research, draft, root = (Path(os.path.abspath(path)) for path in (research_path, draft_path, intake_dir))
    brief, receipt = root / 'brief.json', root / 'intake.json'
    research_raw, draft_raw = _input(research), _input(draft)
    brief_raw, receipt_raw = _input(brief, MAX_BRIEF), _input(receipt)
    recorded = json.loads(receipt_raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    require(isinstance(recorded, dict), 'Invalid intake receipt')
    recorded_at = _timestamp(recorded.get('recorded_at'), 'intake.recorded_at')
    expected_brief, expected_receipt = _compile_intake(research_raw, draft_raw, root, recorded_at,
                                                      prior_cycle, selection_path, selection_receipt)
    require(brief_raw == expected_brief, 'Intake brief does not match the original research and draft')
    expected_receipt_raw = _json_bytes(expected_receipt)
    # Prior Windows intakes wrote the receipt in text mode, translating line endings.
    require(receipt_raw in (expected_receipt_raw, expected_receipt_raw.replace(b'\n', b'\r\n')),
            'Intake receipt does not match the original research and draft')
    require(_input(research) == research_raw and _input(draft) == draft_raw
            and _input(brief, MAX_BRIEF) == brief_raw and _input(receipt) == receipt_raw,
            'Intake files changed while verifying')
    return {'schema_version': 1, 'status': 'INTAKE_VERIFIED', **dict.fromkeys(FALSE_FLAGS, False),
            'intake_receipt_sha256': hashlib.sha256(receipt_raw).hexdigest(),
            **{key: expected_receipt[key] for key in ('research_sha256', 'draft_sha256', 'brief_sha256',
                                                     'queue_brief_sha256')},
            'scope': 'Retained source and draft byte verification. Retrieval, factual accuracy and authorship are separate evidence.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research', required=True)
    parser.add_argument('--draft', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output', help='Create a new intake directory')
    mode.add_argument('--verify', help='Verify an existing intake directory without changing it')
    parser.add_argument('--prior-cycle')
    parser.add_argument('--selection')
    parser.add_argument('--selection-receipt')
    args = parser.parse_args()
    operation = verify_intake if args.verify is not None else prepare_brief
    print(json.dumps(operation(args.research, args.draft, args.verify if args.verify is not None else args.output,
                               prior_cycle=args.prior_cycle, selection_path=args.selection,
                               selection_receipt=args.selection_receipt), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
