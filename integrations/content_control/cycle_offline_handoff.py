"""Build one replayable offline discovery-to-queue handoff.

The input remains an externally observed candidate pool.  This command does
not fetch sources, establish originality, run production, or enqueue work.  It
only joins the existing deterministic discovery, authoring, intake and queue
validation boundaries without requiring a manually supplied script.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from integrations.content_control.cycle_authoring import LONG_FORM_FORMAT, author_draft
from integrations.content_control.cycle_discovery import MAX_POOL, _read, select_topic
from integrations.content_control.cycle_editorial import FALSE_FLAGS
from integrations.content_control.cycle_intake import MAX_BRIEF, MAX_INPUT, prepare_brief, verify_intake
from integrations.content_control.cycle_job import brief_digest, production_handoff
from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.cycle_review import _regular
from integrations.content_control.review_package import no_symlinks, require
from integrations.local_agent_queue import validate as validate_queue


STATUS = 'VERIFIED_OFFLINE_QUEUE_HANDOFF'
ARTIFACTS = {
    'discovery-pool.json': MAX_POOL,
    'discovery/research.json': MAX_INPUT,
    'discovery/discovery.json': MAX_INPUT,
    'draft.json': MAX_INPUT,
    'intake/brief.json': MAX_BRIEF,
    'intake/intake.json': MAX_INPUT,
    'queue-job.json': 150000,
}
MANIFEST_LIMIT = 128 * 1024


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def _load(raw, label):
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Invalid {label} JSON') from error
    require(isinstance(value, dict), f'{label} must be a JSON object')
    return value


def _artifact(root, name, limit):
    path = root / name
    with _regular(path, limit).open('rb') as stream:
        raw = stream.read(limit + 1)
    require(0 < len(raw) <= limit, f'{name} exceeds its byte limit')
    return raw


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def verify_handoff(output):
    """Replay a retained handoff without editing or enqueueing it."""
    root = Path(os.path.abspath(output))
    no_symlinks(root)
    require(root.is_dir() and not root.is_symlink(), 'Regular handoff directory required')
    require({item.name for item in root.iterdir()} == {
        'discovery-pool.json', 'discovery', 'draft.json', 'intake',
        'queue-job.json', 'handoff.json',
    }, 'Unexpected offline handoff files')
    require((root / 'discovery').is_dir() and not (root / 'discovery').is_symlink()
            and {item.name for item in (root / 'discovery').iterdir()}
            == {'research.json', 'discovery.json'}, 'Unexpected discovery files')
    require((root / 'intake').is_dir() and not (root / 'intake').is_symlink()
            and {item.name for item in (root / 'intake').iterdir()}
            == {'brief.json', 'intake.json'}, 'Unexpected intake files')

    raw = {name: _artifact(root, name, limit) for name, limit in ARTIFACTS.items()}
    manifest_raw = _artifact(root, 'handoff.json', MANIFEST_LIMIT)
    manifest = _load(manifest_raw, 'handoff manifest')
    manifest_fields = {
        'schema_version', 'status', 'content_format', 'job_id',
        'artifacts_sha256', 'brief_sha256', 'selected_candidate_id',
        'original_authoring', 'scope', *FALSE_FLAGS,
    }
    require(set(manifest) == manifest_fields and manifest['schema_version'] == 1
            and manifest['status'] == STATUS,
            'Unexpected offline handoff manifest')
    require(manifest['content_format'] in ('standard', LONG_FORM_FORMAT),
            'Unexpected handoff content format')
    require(all(manifest[key] is False for key in FALSE_FLAGS),
            'Offline handoff cannot grant approval, publishing or paid generation')
    expected_hashes = {name: _digest(value) for name, value in raw.items()}
    require(manifest['artifacts_sha256'] == expected_hashes,
            'Offline handoff artifact identity mismatch')

    job = _load(raw['queue-job.json'], 'queue job')
    validate_queue(job)
    require(job['id'] == manifest['job_id'] and job['publication_enabled'] is False
            and job['paid_generation_enabled'] is False,
            'Queue job differs from the disabled handoff')
    request = job['request']
    brief = _load(raw['intake/brief.json'], 'production brief')
    require(request['brief'] == brief and request['brief_sha256'] == brief_digest(brief)
            and manifest['brief_sha256'] == request['brief_sha256'],
            'Queue request differs from the retained brief')
    supplied = request['intake_input']
    require(supplied == {
        'research_json': raw['discovery/research.json'].decode('utf-8'),
        'draft_json': raw['draft.json'].decode('utf-8'),
        'receipt_json': raw['intake/intake.json'].decode('utf-8'),
        'discovery_pool_json': raw['discovery-pool.json'].decode('utf-8'),
        'discovery_receipt_json': raw['discovery/discovery.json'].decode('utf-8'),
    }, 'Queue request does not retain the exact offline inputs')

    encoded, lineage, retained, proof = production_handoff(request)
    require(lineage is None and encoded == raw['intake/brief.json'],
            'Queue handoff does not reproduce the retained brief')
    require(retained == {
        'research.json': raw['discovery/research.json'],
        'draft.json': raw['draft.json'],
        'intake.json': raw['intake/intake.json'],
        'discovery-pool.json': raw['discovery-pool.json'],
        'discovery.json': raw['discovery/discovery.json'],
    }, 'Queue handoff does not reproduce the retained evidence')
    verified = verify_intake(
        root / 'discovery/research.json', root / 'draft.json', root / 'intake',
        discovery_pool=root / 'discovery-pool.json',
        discovery_receipt=root / 'discovery/discovery.json')
    require(proof == verified and manifest['original_authoring'] == proof['original_authoring'],
            'Offline authoring or intake proof differs from the queued handoff')
    require(manifest['selected_candidate_id']
            == proof['topic_discovery']['selected_candidate_id'],
            'Selected candidate identity mismatch')
    authoring = proof['original_authoring']
    observed_format = authoring.get('content_format', 'standard')
    require(observed_format == manifest['content_format'], 'Authored format identity mismatch')
    return manifest


def build_handoff(pool_path, output, *, job_id, content_format=LONG_FORM_FORMAT,
                  timeout_seconds=300, max_attempts=1):
    """Create an atomic self-contained request, but do not enqueue or run it."""
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    require(isinstance(job_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', job_id),
            'Require a safe immutable queue job ID')
    require(content_format in ('standard', LONG_FORM_FORMAT),
            'Authoring format must be standard or long-form')
    output = Path(os.path.abspath(output))
    pool_path = Path(os.path.abspath(pool_path))
    no_symlinks(output)
    require(not output.exists(), 'Fresh offline handoff directory required')
    output.parent.mkdir(parents=True, exist_ok=True)
    no_symlinks(output.parent)
    pool_raw = _read(pool_path, MAX_POOL)
    temporary = Path(tempfile.mkdtemp(prefix='.offline-handoff-', dir=output.parent))
    owns_output = False
    try:
        retained_pool = temporary / 'discovery-pool.json'
        with retained_pool.open('xb') as stream:
            stream.write(pool_raw)
        discovery = temporary / 'discovery'
        select_topic(retained_pool, discovery)
        author_draft(retained_pool, discovery / 'research.json',
                     discovery / 'discovery.json', temporary / 'draft.json',
                     content_format=content_format)
        intake = temporary / 'intake'
        prepare_brief(discovery / 'research.json', temporary / 'draft.json', intake,
                      discovery_pool=retained_pool,
                      discovery_receipt=discovery / 'discovery.json')

        brief = _load(_artifact(temporary, 'intake/brief.json', MAX_BRIEF),
                      'production brief')
        request = {
            'operation': 'produce-content-cycle', 'brief': brief,
            'brief_sha256': brief_digest(brief), 'timeout_seconds': timeout_seconds,
            'publication_enabled': False, 'paid_generation_enabled': False,
            'intake_input': {
                'research_json': _artifact(temporary, 'discovery/research.json', MAX_INPUT).decode('utf-8'),
                'draft_json': _artifact(temporary, 'draft.json', MAX_INPUT).decode('utf-8'),
                'receipt_json': _artifact(temporary, 'intake/intake.json', MAX_INPUT).decode('utf-8'),
                'discovery_pool_json': pool_raw.decode('utf-8'),
                'discovery_receipt_json': _artifact(
                    temporary, 'discovery/discovery.json', MAX_INPUT).decode('utf-8'),
            },
        }
        job = {'id': job_id, 'adapter': 'content-control-cycle', 'request': request,
               'max_attempts': max_attempts, 'publication_enabled': False,
               'paid_generation_enabled': False}
        validate_queue(job)
        with (temporary / 'queue-job.json').open('xb') as stream:
            stream.write(_json_bytes(job))
        _, _, _, proof = production_handoff(request)
        artifacts = {name: _digest(_artifact(temporary, name, limit))
                     for name, limit in ARTIFACTS.items()}
        flags = dict.fromkeys(FALSE_FLAGS, False)
        manifest = {
            'schema_version': 1, 'status': STATUS, 'content_format': content_format,
            'job_id': job_id, 'artifacts_sha256': artifacts,
            'brief_sha256': request['brief_sha256'],
            'selected_candidate_id': proof['topic_discovery']['selected_candidate_id'],
            'original_authoring': proof['original_authoring'], **flags,
            'scope': ('Atomic deterministic offline discovery, script/storyboard, intake and '
                      'queue-request assembly from an externally observed candidate pool. No '
                      'source retrieval, trend, originality, factual, creative, audiovisual, '
                      'production, audience, deployment, publishing or paid-generation claim.'),
        }
        with (temporary / 'handoff.json').open('xb') as stream:
            stream.write(_json_bytes(manifest))
        verify_handoff(temporary)
        require(_read(pool_path, MAX_POOL) == pool_raw,
                'Discovery pool changed while building the offline handoff')
        temporary.rename(output)
        owns_output = True
        verify_handoff(output)
        return manifest
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        if owns_output and output.exists():
            shutil.rmtree(output)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output')
    mode.add_argument('--verify', help='Verify a handoff without creating or enqueueing anything')
    parser.add_argument('--job-id')
    parser.add_argument('--format', dest='content_format', choices=('standard', LONG_FORM_FORMAT),
                        default=LONG_FORM_FORMAT)
    parser.add_argument('--timeout-seconds', type=int, default=300)
    parser.add_argument('--max-attempts', type=int, default=1)
    args = parser.parse_args()
    if args.verify is not None:
        result = verify_handoff(args.verify)
    else:
        require(args.pool is not None and args.job_id is not None,
                '--pool and --job-id are required when creating a handoff')
        result = build_handoff(args.pool, args.output, job_id=args.job_id,
                               content_format=args.content_format,
                               timeout_seconds=args.timeout_seconds,
                               max_attempts=args.max_attempts)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
