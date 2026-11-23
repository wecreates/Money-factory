"""Join retained research and a separate script draft into a bound cycle brief."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

from integrations.content_control.cycle_editorial import FALSE_FLAGS, compile_editorial
from integrations.content_control.cycle_job import brief_digest, canonical
from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.cycle_review import _regular
from integrations.content_control.review_package import no_symlinks, require

RESEARCH_FIELDS = {'schema_version', 'topic', 'sources', 'reference_observations'}
DRAFT_FIELDS = {'schema_version', 'research_sha256', 'title', 'scenes'}
DRAFT_OPTIONS = {'thumbnail_copy', 'layout'}
MAX_INPUT = 128 * 1024


def _input(path):
    with _regular(path, MAX_INPUT).open('rb') as stream:
        raw = stream.read(MAX_INPUT + 1)
    require(len(raw) <= MAX_INPUT, 'Intake input exceeds 128 KiB')
    return raw


def _object(raw, required, options):
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    require(isinstance(value, dict) and required <= value.keys() <= required | options
            and type(value['schema_version']) is int and value['schema_version'] == 1,
            'Unexpected intake fields or schema version')
    return value


def prepare_brief(research_path, draft_path, output):
    """Bind exact source bytes; the draft cannot add or replace research records."""
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')), 'Publishing and paid generation must remain disabled')
    research, draft = (Path(os.path.abspath(path)) for path in (research_path, draft_path))
    output = Path(os.path.abspath(output))
    no_symlinks(output)
    require(not output.exists(), 'Fresh intake output directory required')
    research_raw, draft_raw = _input(research), _input(draft)
    research_data = _object(research_raw, RESEARCH_FIELDS, set())
    draft_data = _object(draft_raw, DRAFT_FIELDS, DRAFT_OPTIONS)
    research_sha = hashlib.sha256(research_raw).hexdigest()
    draft_sha = hashlib.sha256(draft_raw).hexdigest()
    require(draft_data['research_sha256'] == research_sha, 'Draft does not bind these exact research bytes')
    flags = dict.fromkeys(FALSE_FLAGS, False)
    brief = {**research_data, **{k: v for k, v in draft_data.items() if k not in ('schema_version', 'research_sha256')},
             **flags, 'research_handoff': {'research_sha256': research_sha, 'draft_sha256': draft_sha}}
    require(len(canonical(brief).encode()) <= 120000, 'Compiled brief exceeds queue input limit')
    compile_editorial(brief, validate_visual_shapes=True)
    brief_raw = (json.dumps(brief, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    require(len(brief_raw) <= 256 * 1024, 'Formatted brief exceeds renderer input limit')
    receipt = {'schema_version': 1, 'status': 'BRIEF_READY_FOR_PRODUCTION', **flags,
               'recorded_at': datetime.now(timezone.utc).isoformat(),
               'research_sha256': research_sha, 'draft_sha256': draft_sha,
               'brief_sha256': hashlib.sha256(brief_raw).hexdigest(), 'queue_brief_sha256': brief_digest(brief),
               'source_ids': [source['id'] for source in brief['sources']],
               'scope': 'Supplied-source and draft handoff. Source retrieval, factual review and authorship are separate evidence.'}
    require(_input(research) == research_raw and _input(draft) == draft_raw, 'Intake inputs changed')
    output.mkdir(parents=True, exist_ok=False)
    try:
        with (output / 'brief.json').open('xb') as stream:
            stream.write(brief_raw)
        with (output / 'intake.json').open('x') as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    except BaseException:
        shutil.rmtree(output)
        raise
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research', required=True)
    parser.add_argument('--draft', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare_brief(args.research, args.draft, args.output), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
