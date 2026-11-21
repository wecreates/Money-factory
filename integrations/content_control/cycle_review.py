"""Immutable, candidate-bound reviewer attestations and revision handoffs.

Recording a statement is not independent verification of that statement. Nothing
in this module grants production approval or enables publication.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

from integrations.content_control.cycle_editorial import compile_editorial, _timestamp, _text
from integrations.content_control.cycle_package import editorial_digest
from integrations.content_control.review_package import digest, no_symlinks, require, SHA


CHECKS = ('factual_accuracy', 'full_audiovisual', 'voice_naturalness',
          'visual_readability', 'originality', 'reference_comparison')
FLAGS = ('publication_enabled', 'paid_generation_enabled', 'production_approved', 'full_av_review')


def _regular(path, limit=1024 * 1024):
    no_symlinks(path)
    require(path.is_file() and path.stat().st_size <= limit, 'Missing or oversized file: ' + path.name)
    return path


def _load(path):
    value = json.loads(_regular(path).read_text())
    require(isinstance(value, dict), 'JSON object required: ' + path.name)
    return value


def _unapproved(value):
    require(all(value.get(flag) is False for flag in FLAGS), 'Publication and approval flags must remain false')


def inspect_cycle(cycle_dir):
    """Validate existing artifact identities, without pretending to watch media."""
    root = Path(os.path.abspath(cycle_dir))
    no_symlinks(root)
    require(root.is_dir(), 'Cycle directory required')
    cycle = _load(root / 'cycle.json')
    require(cycle.get('status') == 'AWAITING_REVIEW' and cycle.get('technical_status') == 'PASS',
            'Completed unpublished cycle required')
    _unapproved(cycle)
    delivery = root / 'delivery'
    no_symlinks(delivery)
    package = _load(delivery / 'package.json')
    require(digest(delivery / 'package.json') == cycle.get('package_sha256'), 'Package receipt changed')
    _unapproved(package)
    require(package.get('status') == 'AWAITING_REVIEW' and package.get('technical_status') == 'PASS',
            'Completed package required')
    files = package.get('files_sha256')
    required = {'video.mp4', 'captions.vtt', 'render.json', 'editorial.json', 'index.html',
                'thumbnail-1.png', 'thumbnail-2.png', 'thumbnail-3.png'}
    require(isinstance(files, dict) and required <= set(files), 'Incomplete package manifest')
    for name, expected in files.items():
        require(isinstance(name, str) and Path(name).name == name and name not in ('.', '..'),
                'Invalid package path')
        require(isinstance(expected, str) and SHA.fullmatch(expected), 'Invalid package hash')
        _regular(delivery / name, 256 * 1024 * 1024)
        require(digest(delivery / name) == expected, 'Package artifact changed: ' + name)
    require({path.name for path in delivery.iterdir()} == set(files) | {'package.json', 'review-package.zip'},
            'Unexpected package files')
    archive = _regular(delivery / 'review-package.zip', 256 * 1024 * 1024)
    # The archive's receipt is byte-identical to the bound standalone receipt.
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        expected_names = set(files) | {'package.json'}
        require(len(members) == len(expected_names) and {member.filename for member in members} == expected_names,
                'Archive members changed')
        for member in members:
            require(member.file_size == (delivery / member.filename).stat().st_size, 'Archive file size changed')
            with bundle.open(member) as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            require(actual == digest(delivery / member.filename), 'Archive artifact changed: ' + member.filename)
    editorial = _load(root / 'editorial.json')
    require(digest(root / 'editorial.json') == cycle.get('editorial_sha256'), 'Cycle editorial changed')
    require(_load(delivery / 'editorial.json') == editorial, 'Package editorial differs from cycle')
    require(editorial_digest(editorial) == package.get('editorial_sha256'), 'Editorial canonical binding mismatch')
    require(digest(_regular(root / 'brief.json')) == cycle.get('brief_sha256'), 'Cycle brief changed')
    require(compile_editorial(_load(root / 'brief.json')) == editorial, 'Brief no longer compiles to this editorial')
    candidate = digest(delivery / 'video.mp4')
    require(candidate == cycle.get('candidate_sha256') == package.get('candidate_sha256'), 'Candidate mismatch')
    render = _load(delivery / 'render.json')
    _unapproved(render)
    require(render.get('technical_status') == 'PASS' and render.get('candidate_sha256') == candidate,
            'Render verification mismatch')
    require(render.get('editorial_sha256') == package.get('editorial_sha256'), 'Render editorial mismatch')
    require(digest(delivery / 'captions.vtt') == render.get('caption_sha256') == package.get('caption_sha256'),
            'Caption identity mismatch')
    require(digest(delivery / 'render.json') == package.get('render_receipt_sha256'), 'Render receipt identity mismatch')
    for name in ('video.mp4', 'captions.vtt', 'render.json'):
        _regular(root / 'render' / name, 256 * 1024 * 1024)
        require(digest(root / 'render' / name) == digest(delivery / name), 'Original render artifact changed: ' + name)
    identities = {name: digest(root / name) for name in ('cycle.json', 'brief.json', 'editorial.json',
                   'render/render.json', 'delivery/package.json', 'delivery/review-package.zip')}
    identities.update({'delivery/' + name: expected for name, expected in files.items()})
    return {'cycle': cycle, 'editorial': editorial, 'candidate_sha256': candidate, 'files_sha256': identities}


def _new_output(path, root, source):
    path = Path(os.path.abspath(path))
    no_symlinks(path)
    require(not path.exists(), 'Output already exists')
    require(not path.is_relative_to(root) and path != source, 'Output must be separate from existing cycle and input')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record_review(cycle_dir, review_path, output):
    root, review_path = Path(os.path.abspath(cycle_dir)), Path(os.path.abspath(review_path))
    snapshot = inspect_cycle(root)
    review = _load(review_path)
    review_hash = digest(review_path)
    require(review.get('candidate_sha256') == snapshot['candidate_sha256'], 'Review targets a different candidate')
    reviewer = _text(review.get('reviewer'), 'reviewer', 200)
    reviewed_at = _timestamp(review.get('reviewed_at'), 'reviewed_at')
    require(datetime.fromisoformat(reviewed_at) >= datetime.fromisoformat(snapshot['cycle']['finished_at']),
            'Review predates completed cycle')
    checks = review.get('checks', {})
    require(isinstance(checks, dict) and set(checks) <= set(CHECKS), 'Unknown or invalid review checks')
    normalized, feedback = {}, []
    for name in CHECKS:
        item = checks.get(name)
        if item is None:
            feedback.append({'check': name, 'action': 'Complete and document the ' + name.replace('_', ' ') + ' review.'})
            continue
        require(isinstance(item, dict) and type(item.get('passed')) is bool, 'Review passed values must be booleans')
        evidence = _text(item.get('evidence'), name + '.evidence', 4000, minimum=12)
        normalized[name] = {'passed': item['passed'], 'evidence': evidence}
        if not item['passed']:
            action = _text(item.get('feedback', evidence), name + '.feedback', 4000, minimum=12)
            normalized[name]['feedback'] = action
            feedback.append({'check': name, 'action': action})
    result = {'schema_version': 1, 'status': 'REVISION_REQUIRED' if feedback else 'EDITORIAL_REVIEW_RECORDED',
              'candidate_sha256': snapshot['candidate_sha256'], 'reviewer': reviewer,
              'reviewed_at': reviewed_at, 'recorded_at': datetime.now(timezone.utc).isoformat(),
              'checks': normalized, 'feedback': feedback, 'source_files_sha256': snapshot['files_sha256'],
              'submitted_review_sha256': review_hash, 'independent_verification': False,
              'scope': 'Candidate-bound reviewer attestation only; supplied judgments are not independently verified.',
              'publication_enabled': False, 'paid_generation_enabled': False, 'production_approved': False,
              'full_av_review': False, 'production_ready': False}
    require(inspect_cycle(root)['files_sha256'] == snapshot['files_sha256'] and digest(review_path) == review_hash,
            'Review inputs changed while recording')
    output = _new_output(output, root, review_path)
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    return result


def revision_brief(cycle_dir, recorded_review_path, new_brief, output):
    """Write brief.json plus revision.json to a new directory for a fresh run.

    Prior sources/references are retained. Corrections use additional source IDs,
    preserving the evidence history instead of silently rewriting provenance.
    """
    root, review_path = Path(os.path.abspath(cycle_dir)), Path(os.path.abspath(recorded_review_path))
    snapshot = inspect_cycle(root)
    review = _load(review_path)
    _unapproved(review)
    require(review.get('status') in ('REVISION_REQUIRED', 'EDITORIAL_REVIEW_RECORDED'), 'Recorded review required')
    require(review.get('candidate_sha256') == snapshot['candidate_sha256'] and
            review.get('source_files_sha256') == snapshot['files_sha256'], 'Review does not bind current cycle')
    require(review.get('independent_verification') is False, 'Review scope mismatch')
    revised = compile_editorial(new_brief)
    old = snapshot['editorial']
    require(revised != old, 'Revision must change the editorial brief')
    sources = {source['id']: source for source in revised['sources']}
    require(all(sources.get(source['id']) == source for source in old['sources']), 'Prior source provenance must be preserved')
    require(all(reference in revised['reference_observations'] for reference in old['reference_observations']),
            'Prior reference provenance must be preserved')
    output = _new_output(output, root, review_path)
    review_hash = digest(review_path)
    result = {'schema_version': 1, 'status': 'REVISION_BRIEF_READY',
              'supersedes_candidate_sha256': snapshot['candidate_sha256'],
              'recorded_review_sha256': review_hash, 'prior_cycle_sha256': snapshot['files_sha256']['cycle.json'],
              'feedback': review.get('feedback', []), 'feedback_resolution_verified': False,
              'publication_enabled': False, 'paid_generation_enabled': False, 'production_approved': False,
              'full_av_review': False, 'production_ready': False,
              'scope': 'Revised supplied brief; previous approval statements cannot certify a new render.'}
    require(inspect_cycle(root)['files_sha256'] == snapshot['files_sha256'] and digest(review_path) == review_hash,
            'Revision inputs changed')
    output.mkdir()
    try:
        with (output / 'brief.json').open('x') as stream:
            json.dump(new_brief, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
        result['brief_sha256'] = digest(output / 'brief.json')
        with (output / 'revision.json').open('x') as stream:
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    except BaseException:
        shutil.rmtree(output)
        raise
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-dir', required=True)
    parser.add_argument('--review', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--revision-brief', help='Optional new full brief JSON; --review must then be a recorded review.')
    args = parser.parse_args()
    if args.revision_brief:
        result = revision_brief(args.cycle_dir, args.review, _load(Path(args.revision_brief)), args.output)
    else:
        result = record_review(args.cycle_dir, args.review, args.output)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
