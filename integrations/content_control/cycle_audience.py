"""Record and replay audience counts against an exact package selection.

The supplied counts remain unverified attestations.  This module never fetches
analytics, infers a winner, approves media, or enables publication.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from integrations.content_control.cycle_editorial import _flags, _text, _timestamp, _url
from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.cycle_review import _new_output, _regular
from integrations.content_control.cycle_selection import verify_selection
from integrations.content_control.review_package import require


OBSERVATION_FIELDS = {
    'schema_version', 'selection_receipt_sha256', 'candidate_sha256',
    'package_sha256', 'thumbnail_sha256', 'title', 'impressions', 'clicks',
    'window_start', 'window_end', 'observed_at', 'source_url', 'evidence',
}


def _read(path):
    limit = 1024 * 1024
    with _regular(path, limit).open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'Audience observation JSON exceeds 1 MiB')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    require(isinstance(value, dict), 'Audience observation JSON object required')
    return value, hashlib.sha256(raw).hexdigest()


def _result(selection, selection_receipt_sha256, observation, source_sha256, recorded_at):
    _flags(observation)
    require(set(observation) == OBSERVATION_FIELDS and observation.get('schema_version') == 1,
            'Exact audience observation fields and schema version 1 required')
    require(observation['selection_receipt_sha256'] == selection_receipt_sha256,
            'Observation does not bind this selection receipt')
    for field in ('candidate_sha256', 'package_sha256', 'thumbnail_sha256', 'title'):
        require(observation[field] == selection[field], 'Observation differs from selected ' + field)
    counts = [observation.get(name) for name in ('impressions', 'clicks')]
    require(all(type(value) is int and 0 <= value <= 10**12 for value in counts)
            and counts[1] <= counts[0],
            'Nonnegative integer counts with clicks <= impressions required')
    start = _timestamp(observation.get('window_start'), 'window_start')
    end = _timestamp(observation.get('window_end'), 'window_end')
    observed = _timestamp(observation.get('observed_at'), 'observed_at')
    require(datetime.fromisoformat(start) >= datetime.fromisoformat(selection['reviewed_at']),
            'Audience window predates the selection')
    require(datetime.fromisoformat(start) <= datetime.fromisoformat(end) <= datetime.fromisoformat(observed),
            'Invalid audience observation window')
    require(datetime.fromisoformat(recorded_at) >= datetime.fromisoformat(observed),
            'Receipt predates audience observation')
    return {
        'schema_version': 1,
        'status': 'AUDIENCE_OBSERVATION_RECORDED',
        'selection_receipt_sha256': selection_receipt_sha256,
        'candidate_sha256': selection['candidate_sha256'],
        'package_sha256': selection['package_sha256'],
        'thumbnail': selection['thumbnail'],
        'thumbnail_sha256': selection['thumbnail_sha256'],
        'title': selection['title'],
        'impressions': counts[0],
        'clicks': counts[1],
        'ctr': counts[1] / counts[0] if counts[0] else None,
        'window_start': start,
        'window_end': end,
        'observed_at': observed,
        'source_url': _url(observation.get('source_url'), 'source_url'),
        'evidence': _text(observation.get('evidence'), 'evidence', 4000, minimum=12),
        'submitted_observation_sha256': source_sha256,
        'recorded_at': recorded_at,
        'performance_status': 'SUPPLIED_UNVERIFIED',
        'audience_performance_verified': False,
        'independent_verification': False,
        'scope': ('Submitted counts bound to one exact selection; analytics were not independently fetched, '
                  'and no causal winner or audience preference is inferred.'),
        'publication_enabled': False,
        'paid_generation_enabled': False,
        'production_approved': False,
        'full_av_review': False,
        'production_ready': False,
    }


def verify_audience_observation(cycle_dir, selection_path, selection_receipt, observation_path, receipt_path):
    """Reconstruct a retained observation receipt without writing files."""
    paths = [Path(os.path.abspath(path)) for path in
             (cycle_dir, selection_path, selection_receipt, observation_path, receipt_path)]
    root, selection_source, selection_record, observation_source, receipt = paths
    require(len(set(paths)) == len(paths), 'Audience replay inputs and receipt must be separate')
    selection, selection_sha = verify_selection(root, selection_source, selection_record)
    observation, source_sha = _read(observation_source)
    recorded, receipt_sha = _read(receipt)
    recorded_at = _timestamp(recorded.get('recorded_at'), 'recorded_at')
    expected = _result(selection, selection_sha, observation, source_sha, recorded_at)
    require(json.dumps(recorded, sort_keys=True) == json.dumps(expected, sort_keys=True),
            'Audience receipt does not match the original selection and observation')
    require(verify_selection(root, selection_source, selection_record)[1] == selection_sha
            and _read(observation_source)[1] == source_sha and _read(receipt)[1] == receipt_sha,
            'Audience replay inputs changed while verifying')
    return expected, receipt_sha


def record_audience_observation(cycle_dir, selection_path, selection_receipt, observation_path, output):
    """Create a fail-closed receipt for supplied, explicitly unverified counts."""
    require(all(os.environ.get(key, 'false').lower() == 'false' for key in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')),
            'Publishing and paid generation must remain disabled')
    root, selection_source, selection_record, observation_source = (
        Path(os.path.abspath(path)) for path in
        (cycle_dir, selection_path, selection_receipt, observation_path))
    selection, selection_sha = verify_selection(root, selection_source, selection_record)
    observation, source_sha = _read(observation_source)
    result = _result(selection, selection_sha, observation, source_sha,
                     datetime.now(timezone.utc).isoformat())
    require(verify_selection(root, selection_source, selection_record)[1] == selection_sha
            and _read(observation_source)[1] == source_sha,
            'Audience observation inputs changed while recording')
    destination = _new_output(output, root, observation_source)
    with destination.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-dir', required=True)
    parser.add_argument('--selection', required=True)
    parser.add_argument('--selection-receipt', required=True)
    parser.add_argument('--observation', required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--output')
    target.add_argument('--verify-receipt')
    args = parser.parse_args()
    if args.verify_receipt:
        result = verify_audience_observation(args.cycle_dir, args.selection, args.selection_receipt,
                                             args.observation, args.verify_receipt)[0]
    else:
        result = record_audience_observation(args.cycle_dir, args.selection, args.selection_receipt,
                                             args.observation, args.output)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
