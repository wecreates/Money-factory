"""Assess whether exact package evidence can support performance-informed learning.

This gate is deliberately conservative.  Existing selection and audience
receipts contain either unavailable or supplied-unverified performance data, so
they can preserve a reviewer hypothesis but cannot establish an audience winner
or verified learning.  The command never logs in, fetches analytics, changes a
package, or enables publication.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from integrations.content_control.cycle_audience import verify_audience_observation
from integrations.content_control.cycle_editorial import _timestamp
from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.cycle_review import _new_output, _regular
from integrations.content_control.cycle_selection import verify_selection
from integrations.content_control.review_package import require


MAX_RECEIPT = 1024 * 1024
FALSE_FLAGS = {
    'audience_performance_verified': False,
    'winner_inferred': False,
    'publication_enabled': False,
    'paid_generation_enabled': False,
    'production_approved': False,
    'full_av_review': False,
    'production_ready': False,
}


def _read(path):
    with _regular(path, MAX_RECEIPT).open('rb') as stream:
        raw = stream.read(MAX_RECEIPT + 1)
    require(len(raw) <= MAX_RECEIPT, 'Learning readiness receipt exceeds 1 MiB')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                       parse_constant=_constant)
    require(isinstance(value, dict), 'Learning readiness JSON object required')
    return value, hashlib.sha256(raw).hexdigest()


def _result(selection, selection_sha, hypothesis_index, assessed_at,
            audience=None, audience_sha=None, *, schema_version=2,
            interim_v1=False):
    require(type(schema_version) is int and schema_version in (1, 2),
            'Learning readiness schema version 1 or 2 required')
    require(schema_version != 1 or selection.get('schema_version') == 1,
            'Schema version 1 readiness requires a schema version 1 selection receipt')
    assessed_at = _timestamp(assessed_at, 'assessed_at')
    require(datetime.fromisoformat(assessed_at)
            >= datetime.fromisoformat(selection['recorded_at']),
            'Learning readiness assessment predates the selection receipt')
    hypotheses = selection['next_idea_hypotheses']
    require(type(hypothesis_index) is int
            and 1 <= hypothesis_index <= len(hypotheses),
            'Learning readiness requires one recorded reviewer hypothesis')
    performance_status = selection['performance']['status']
    source = 'selection_receipt'
    result = {
        'schema_version': schema_version,
        'status': 'BLOCKED',
        'reason_code': ('VERIFIED_AUDIENCE_PERFORMANCE_UNAVAILABLE'
                        if performance_status == 'UNAVAILABLE'
                        else 'AUDIENCE_PERFORMANCE_UNVERIFIED'),
        'selection_receipt_sha256': selection_sha,
        'candidate_sha256': selection['candidate_sha256'],
        'package_sha256': selection['package_sha256'],
        'thumbnail_sha256': selection['thumbnail_sha256'],
        'title': selection['title'],
        'hypothesis_index': hypothesis_index,
        'hypothesis': hypotheses[hypothesis_index - 1],
        'performance_source': source,
        'performance_status': performance_status,
        'reviewer_hypothesis_replayable': True,
        'performance_informed_learning_ready': False,
        'assessed_at': assessed_at,
        **FALSE_FLAGS,
        'evidence_needed': (
            'A trusted read-only analytics receipt from the connected owner channel must '
            'bind this exact candidate, package, title, thumbnail and observation window. '
            'Supplied counts, CTR calculations and reviewer hypotheses are insufficient.'),
        'scope': (
            'Exact selection and hypothesis readiness only. No analytics login or fetch, '
            'audience verification, causal winner, creative approval, production approval, '
            'paid inference or publication.'),
    }
    if schema_version == 2 or interim_v1:
        result['thumbnail'] = selection['thumbnail']
        result['performance_values_admitted'] = False
    if audience is not None:
        require(audience_sha is not None
                and audience['selection_receipt_sha256'] == selection_sha,
                'Audience readiness evidence does not bind this selection')
        performance_status = audience['performance_status']
        require(performance_status == 'SUPPLIED_UNVERIFIED'
                and audience['audience_performance_verified'] is False,
                'Audience receipt must remain supplied and unverified')
        require(datetime.fromisoformat(assessed_at)
                >= datetime.fromisoformat(audience['recorded_at']),
                'Learning readiness assessment predates the audience receipt')
        result.update(
            reason_code='AUDIENCE_PERFORMANCE_UNVERIFIED',
            performance_source='audience_receipt',
            performance_status=performance_status,
            audience_observation_sha256=audience['submitted_observation_sha256'],
            audience_receipt_sha256=audience_sha,
        )
    # Counts, CTR, source URLs and evidence notes deliberately do not cross this
    # gate.  Until a trusted authenticated adapter exists they cannot influence
    # an automated performance decision.
    return result


def _assessment(cycle_dir, selection_path, selection_receipt, hypothesis_index,
                assessed_at, audience_observation=None, audience_receipt=None, *,
                schema_version=2, interim_v1=False):
    audience_paths = (audience_observation, audience_receipt)
    require(all(path is None for path in audience_paths)
            or all(path is not None for path in audience_paths),
            'Audience readiness requires both original observation and receipt')
    selection, selection_sha = verify_selection(
        cycle_dir, selection_path, selection_receipt)
    audience = audience_sha = None
    if audience_observation is not None:
        audience, audience_sha = verify_audience_observation(
            cycle_dir, selection_path, selection_receipt,
            audience_observation, audience_receipt)
    return _result(selection, selection_sha, hypothesis_index, audience=audience,
                   audience_sha=audience_sha, assessed_at=assessed_at,
                   schema_version=schema_version, interim_v1=interim_v1)


def assess_learning_readiness(cycle_dir, selection_path, selection_receipt,
                              hypothesis_index, output, *,
                              audience_observation=None, audience_receipt=None):
    """Write a replayable blocked receipt without fetching external analytics."""
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    paths = [Path(os.path.abspath(path)) for path in
             (cycle_dir, selection_path, selection_receipt, output)]
    root, selection_source, selection_record, destination = paths
    optional = [Path(os.path.abspath(path)) if path is not None else None
                for path in (audience_observation, audience_receipt)]
    assessed_at = datetime.now(timezone.utc).isoformat()
    result = _assessment(root, selection_source, selection_record,
                         hypothesis_index, assessed_at, *optional)
    require(_assessment(root, selection_source, selection_record,
                        hypothesis_index, assessed_at, *optional) == result,
            'Learning readiness evidence changed while assessing')
    destination = _new_output(destination, root, selection_source)
    require(destination != selection_record
            and all(destination != path for path in optional if path is not None),
            'Output must be separate from retained learning evidence')
    with destination.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return result


def verify_learning_readiness(cycle_dir, selection_path, selection_receipt,
                              hypothesis_index, receipt_path, *,
                              audience_observation=None, audience_receipt=None):
    """Replay a retained readiness receipt without writing files."""
    receipt, receipt_sha = _read(Path(os.path.abspath(receipt_path)))
    version = receipt.get('schema_version')
    require(type(version) is int and version in (1, 2),
            'Learning readiness receipt schema version 1 or 2 required')
    interim_v1 = version == 1 and (
        'thumbnail' in receipt or 'performance_values_admitted' in receipt)
    assessed_at = _timestamp(receipt.get('assessed_at'), 'assessed_at')
    expected = _assessment(cycle_dir, selection_path, selection_receipt,
                           hypothesis_index, assessed_at,
                           audience_observation, audience_receipt,
                           schema_version=version, interim_v1=interim_v1)
    require(json.dumps(receipt, sort_keys=True) == json.dumps(expected, sort_keys=True),
            'Learning readiness receipt does not match the original evidence')
    return expected, receipt_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-dir', required=True)
    parser.add_argument('--selection', required=True)
    parser.add_argument('--selection-receipt', required=True)
    parser.add_argument('--hypothesis-index', required=True, type=int)
    parser.add_argument('--audience-observation')
    parser.add_argument('--audience-receipt')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output')
    mode.add_argument('--verify-receipt')
    args = parser.parse_args()
    kwargs = dict(audience_observation=args.audience_observation,
                  audience_receipt=args.audience_receipt)
    if args.verify_receipt:
        result = verify_learning_readiness(
            args.cycle_dir, args.selection, args.selection_receipt,
            args.hypothesis_index, args.verify_receipt, **kwargs)[0]
    else:
        result = assess_learning_readiness(
            args.cycle_dir, args.selection, args.selection_receipt,
            args.hypothesis_index, args.output, **kwargs)
    print(json.dumps(result, indent=2))
    return 2 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
