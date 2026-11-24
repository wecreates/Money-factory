"""Record an exact-package title/thumbnail choice and honest learning inputs.

Supplied observations are attestations, not independently verified analytics.
Selection never changes the package, approves media, or enables publication.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from integrations.content_control.cycle_editorial import _flags, _text, _timestamp, _url
from integrations.content_control.cycle_lineage import _constant, _pairs
from integrations.content_control.cycle_review import inspect_cycle, _regular, _new_output
from integrations.content_control.review_package import require


PERFORMANCE_FIELDS = {
    'candidate_sha256', 'package_sha256', 'thumbnail', 'thumbnail_sha256', 'title',
    'impressions', 'clicks', 'window_start', 'window_end', 'observed_at',
    'source_url', 'evidence',
}
LEGACY_PERFORMANCE_FIELDS = PERFORMANCE_FIELDS - {'package_sha256', 'thumbnail'}
INTERIM_PERFORMANCE_FIELDS = PERFORMANCE_FIELDS - {'thumbnail'}
SELECTION_FIELDS = {
    'schema_version', 'candidate_sha256', 'package_sha256', 'thumbnail',
    'thumbnail_sha256', 'title', 'reviewer', 'reviewed_at', 'rationale',
}
SELECTION_OPTIONS = {'thumbnail_copy', 'performance', 'next_idea_hypotheses'}


def _read_selection(path):
    limit = 1024 * 1024
    with _regular(path, limit).open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'Selection JSON exceeds 1 MiB')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    require(isinstance(value, dict), 'Selection JSON object required')
    return value, hashlib.sha256(raw).hexdigest()


def _selection_result(snapshot, selection, source_hash, recorded_at, *,
                      schema_version=2, legacy_replay=False):
    _flags(selection)
    if legacy_replay:
        require(schema_version == 1 and selection.get('schema_version') in (None, 1),
                'Legacy selection replay requires schema version 1 evidence')
    else:
        require(set(selection) >= SELECTION_FIELDS
                and set(selection) <= SELECTION_FIELDS | SELECTION_OPTIONS
                and type(selection.get('schema_version')) is int
                and selection['schema_version'] == 2,
                'Exact selection fields and schema version 2 required')
    require(selection.get('candidate_sha256') == snapshot['candidate_sha256'], 'Selection targets a different candidate')
    require(selection.get('package_sha256') == snapshot['files_sha256']['delivery/package.json'], 'Selection targets a different package')
    thumbnail = selection.get('thumbnail')
    require(thumbnail in ('thumbnail-1.png', 'thumbnail-2.png', 'thumbnail-3.png'), 'Select an existing packaged thumbnail')
    thumbnail_hash = snapshot['files_sha256']['delivery/' + thumbnail]
    require(selection.get('thumbnail_sha256') == thumbnail_hash, 'Selected thumbnail identity mismatch')
    title = _text(selection.get('title'), 'title', 120)
    # A different episode title requires a fresh package, even when the image
    # prints independent thumbnail copy.
    require(title == snapshot['editorial']['title'], 'Title must match this package; repackage title changes')
    if 'thumbnail_copy' in selection:
        require(selection['thumbnail_copy'] == snapshot['editorial'].get('thumbnail_copy', ' '.join(title.split())),
                'Thumbnail copy must match this package')
    reviewer = _text(selection.get('reviewer'), 'reviewer', 200)
    reviewed_at = _timestamp(selection.get('reviewed_at'), 'reviewed_at')
    require(datetime.fromisoformat(reviewed_at) >= datetime.fromisoformat(snapshot['cycle']['finished_at']), 'Selection predates completed cycle')
    require(datetime.fromisoformat(recorded_at) >= datetime.fromisoformat(reviewed_at), 'Receipt predates selection')
    rationale = _text(selection.get('rationale'), 'rationale', 4000, minimum=12)
    performance = selection.get('performance')
    metrics = {'status': 'UNAVAILABLE', 'impressions': None, 'clicks': None, 'ctr': None,
               'independently_verified': False, 'scope': 'No audience evidence supplied; no performance winner inferred.'}
    if performance is not None:
        require(isinstance(performance, dict), 'Performance must be an object or null')
        # The submitted packet is an unverified observation, not a place for a
        # caller to assert a CTR, winner, verification state, or audience
        # conclusion.  Keep the schema exact and derive CTR from the two counts.
        fields = set(performance)
        if legacy_replay:
            require(fields in (LEGACY_PERFORMANCE_FIELDS, INTERIM_PERFORMANCE_FIELDS),
                    'Exact legacy supplied performance fields required')
        else:
            require(fields == PERFORMANCE_FIELDS,
                    'Exact supplied performance fields required; CTR and verification claims are derived')
        require(performance.get('candidate_sha256') == snapshot['candidate_sha256'] and
                (legacy_replay and 'package_sha256' not in performance
                 or performance.get('package_sha256') == selection['package_sha256']) and
                (legacy_replay or performance.get('thumbnail') == thumbnail) and
                performance.get('thumbnail_sha256') == thumbnail_hash and
                performance.get('title') == title,
                'Performance must bind this candidate, package, title, and thumbnail')
        counts = [performance.get(k) for k in ('impressions', 'clicks')]
        require(all(type(n) is int and 0 <= n <= 10**12 for n in counts) and counts[1] <= counts[0],
                'Nonnegative integer counts with clicks <= impressions required')
        start = _timestamp(performance.get('window_start'), 'window_start')
        end = _timestamp(performance.get('window_end'), 'window_end')
        observed = _timestamp(performance.get('observed_at'), 'observed_at')
        require(datetime.fromisoformat(start) <= datetime.fromisoformat(end) <= datetime.fromisoformat(observed), 'Invalid performance window')
        minimum_start = snapshot['cycle']['finished_at'] if legacy_replay else reviewed_at
        require(datetime.fromisoformat(start) >= datetime.fromisoformat(minimum_start),
                'Performance predates selection' if not legacy_replay else 'Performance predates candidate')
        require(datetime.fromisoformat(recorded_at) >= datetime.fromisoformat(observed),
                'Receipt predates performance observation')
        metrics = {'status': 'SUPPLIED_UNVERIFIED', 'impressions': counts[0], 'clicks': counts[1],
                   'ctr': counts[1] / counts[0] if counts[0] else None,
                   'window_start': start, 'window_end': end, 'observed_at': observed,
                   'source_url': _url(performance.get('source_url'), 'performance.source_url'),
                   'evidence': _text(performance.get('evidence'), 'performance.evidence', 4000, minimum=12),
                   'independently_verified': False,
                   'scope': 'Submitted counts, not independently fetched analytics; CTR uses this supplied window only. No causal winner inferred.'}
    hypotheses = selection.get('next_idea_hypotheses', [])
    require(isinstance(hypotheses, list) and len(hypotheses) <= 10, 'At most ten next-idea hypotheses allowed')
    hypotheses = [_text(h, 'next_idea_hypothesis', 1000, minimum=12) for h in hypotheses]
    result = {'schema_version': schema_version, 'status': 'PACKAGE_SELECTION_RECORDED',
              'candidate_sha256': snapshot['candidate_sha256'], 'package_sha256': selection['package_sha256'],
              'thumbnail': thumbnail, 'thumbnail_sha256': thumbnail_hash, 'title': title,
              'reviewer': reviewer, 'reviewed_at': reviewed_at, 'rationale': rationale,
              'recorded_at': recorded_at,
              'source_files_sha256': snapshot['files_sha256'], 'submitted_selection_sha256': source_hash,
              'performance': metrics, 'next_idea_hypotheses': hypotheses,
              'learning_scope': 'Reviewer hypotheses for subsequent ideation; not proven audience preferences or autonomous learning.',
              'independent_verification': False, 'publication_enabled': False, 'paid_generation_enabled': False,
              'production_approved': False, 'full_av_review': False, 'production_ready': False}
    if 'thumbnail_copy' in snapshot['editorial']:
        result['thumbnail_copy'] = snapshot['editorial']['thumbnail_copy']
    return result


def verify_selection(cycle_dir, selection_path, receipt_path):
    """Recheck the private selection against its original input and package."""
    root, source, receipt = (Path(os.path.abspath(path)) for path in (cycle_dir, selection_path, receipt_path))
    require(source != receipt, 'Selection input and receipt must be separate')
    snapshot = inspect_cycle(root)
    selection, source_hash = _read_selection(source)
    recorded, receipt_hash = _read_selection(receipt)
    version = recorded.get('schema_version')
    require(type(version) is int and version in (1, 2),
            'Selection receipt schema version 1 or 2 required')
    recorded_at = _timestamp(recorded.get('recorded_at'), 'recorded_at')
    expected = _selection_result(snapshot, selection, source_hash, recorded_at,
                                 schema_version=version, legacy_replay=version == 1)
    require(json.dumps(recorded, sort_keys=True) == json.dumps(expected, sort_keys=True),
            'Selection receipt does not match the original input and package')
    require(inspect_cycle(root)['files_sha256'] == snapshot['files_sha256']
            and _read_selection(source)[1] == source_hash and _read_selection(receipt)[1] == receipt_hash,
            'Selection inputs changed while verifying')
    return expected, receipt_hash


def record_selection(cycle_dir, selection_path, output):
    root = Path(os.path.abspath(cycle_dir))
    source = Path(os.path.abspath(selection_path))
    require(all(os.environ.get(k, 'false').lower() == 'false' for k in
                ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')), 'Publishing and paid generation must remain disabled')
    snapshot = inspect_cycle(root)
    selection, source_hash = _read_selection(source)
    result = _selection_result(snapshot, selection, source_hash,
                               datetime.now(timezone.utc).isoformat())
    require(inspect_cycle(root)['files_sha256'] == snapshot['files_sha256'] and _read_selection(source)[1] == source_hash,
            'Selection inputs changed while recording')
    destination = _new_output(output, root, source)
    with destination.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-dir', required=True)
    parser.add_argument('--selection', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(record_selection(args.cycle_dir, args.selection, args.output), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
