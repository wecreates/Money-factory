"""Source-backed editorial brief to a new, unpublished video review package.

Research and editorial judgments enter as explicit, attributable inputs. This
command never invents live research, audience measurements, or creative approval.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

from integrations.content_control.cycle_editorial import compile_editorial, portrait_duration_limit
from integrations.content_control.cycle_render import render_cycle
from integrations.content_control.cycle_package import package_cycle
from integrations.content_control.cycle_lineage import read_revision


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def safe_path(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symlink paths are not accepted')
    return path


def run_cycle(brief_path, output, *, voice_python, voice_root, timeout=900, transcription_python=None,
              revision_path=None, minimum_duration=None):
    """Create one immutable attempt; a failed attempt is never resumed as PASS."""
    if type(timeout) is not int or not 30 <= timeout <= 1800:
        raise ValueError('Timeout must be 30..1800 seconds')
    if minimum_duration is not None and (type(minimum_duration) is not int or not 1 <= minimum_duration <= 600):
        raise ValueError('Minimum duration must be an integer from 1 to 600 seconds')
    if any(os.environ.get(k, 'false').lower() != 'false'
           for k in ('PUBLICATION_ENABLED', 'PAID_GENERATION_ENABLED')):
        raise ValueError('Publishing and paid generation must remain disabled')
    source = safe_path(brief_path)
    if not source.is_file() or source.stat().st_size > 256 * 1024:
        raise ValueError('Brief must be a regular JSON file no larger than 256 KiB')
    raw = source.read_bytes()
    brief = json.loads(raw)
    editorial = compile_editorial(brief, validate_visual_shapes=True)
    maximum_duration = portrait_duration_limit(brief, editorial)
    if maximum_duration is not None and minimum_duration is not None and minimum_duration > maximum_duration:
        raise ValueError('Requested minimum exceeds the portrait handoff maximum')
    brief_hash = hashlib.sha256(raw).hexdigest()
    revision_source = safe_path(revision_path) if revision_path is not None else None
    lineage = read_revision(revision_source, brief_hash) if revision_source is not None else None
    output = safe_path(output)
    if output == source or output in source.parents:
        raise ValueError('Output cannot contain the input brief')
    if revision_source is not None and (output == revision_source or output in revision_source.parents):
        raise ValueError('Output cannot contain the revision handoff')
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'schema_version': 1, 'status': 'BLOCKED', 'technical_status': 'PENDING',
               'started_at': stamp(), 'publication_enabled': False,
               'paid_generation_enabled': False, 'production_approved': False,
               'full_av_review': False, 'factual_review': False,
               'competitor_comparison': False, 'production_ready': False,
               'brief_sha256': brief_hash, 'steps': [],
               'scope': 'New video from supplied sourced editorial; no autonomous discovery, creative approval or publishing claim.'}
    module_root = Path(__file__).parent
    if lineage is not None:
        receipt['revision_lineage'] = lineage
    if minimum_duration is not None:
        receipt['minimum_duration_seconds'] = minimum_duration
    if maximum_duration is not None:
        receipt['maximum_duration_seconds'] = maximum_duration
    tool_names = ('complete_cycle.py', 'cycle_editorial.py', 'cycle_render.py', 'cycle_package.py', 'cycle_lineage.py',
                  'cycle_av_review.py', 'cycle_av_benchmarks.py')
    receipt['tool_sha256'] = {name: digest(module_root/name) for name in tool_names}
    deadline = time.monotonic() + timeout
    stage = 'editorial'
    try:
        (output / 'brief.json').write_bytes(raw)
        write(output / 'editorial.json', editorial)
        receipt['editorial_sha256'] = digest(output / 'editorial.json')
        receipt['steps'].append({'name': stage, 'status': 'PASS'})
        write(output / 'cycle.json', receipt)
        stage = 'render'
        render_options = {'voice_python': voice_python, 'voice_root': voice_root,
                          'timeout': max(1, int(deadline-time.monotonic()))}
        if transcription_python:
            render_options['transcription_python'] = transcription_python
        if minimum_duration is not None:
            render_options['minimum_duration'] = minimum_duration
        if maximum_duration is not None:
            render_options['maximum_duration'] = maximum_duration
        rendered = render_cycle(editorial, output / 'render', **render_options)
        if (rendered.get('technical_status') != 'PASS'
                or rendered.get('publication_enabled') is not False
                or rendered.get('production_approved') is not False
                or rendered.get('full_av_review') is not False
                or rendered.get('candidate_sha256') != digest(output/'render/video.mp4')):
            raise ValueError('Renderer did not produce a verified unpublished candidate')
        receipt['candidate_sha256'] = rendered['candidate_sha256']
        receipt['steps'].append({'name': stage, 'status': 'PASS'})
        write(output / 'cycle.json', receipt)
        stage = 'package'
        if time.monotonic() >= deadline:
            raise TimeoutError('Cycle budget exhausted before packaging')
        packaged = package_cycle(editorial, output / 'render', output / 'delivery', deadline=deadline)
        if (packaged.get('status') != 'AWAITING_REVIEW'
                or packaged.get('technical_status') != 'PASS'
                or any(packaged.get(key) is not False for key in
                       ('publication_enabled', 'paid_generation_enabled',
                        'production_approved', 'full_av_review'))):
            raise ValueError('Package did not complete an unpublished review')
        if packaged.get('candidate_sha256') != rendered['candidate_sha256']:
            raise ValueError('Package candidate does not match rendered candidate')
        if time.monotonic() >= deadline:
            raise TimeoutError('Cycle budget exhausted during packaging')
        receipt['package_sha256'] = digest(output / 'delivery/package.json')
        receipt['archive_sha256'] = packaged['archive_sha256']
        receipt['steps'].append({'name': stage, 'status': 'PASS'})
        if digest(source) != receipt['brief_sha256']:
            raise ValueError('Input brief changed during the cycle')
        if revision_source is not None and read_revision(revision_source, brief_hash) != lineage:
            raise ValueError('Revision handoff changed during the cycle')
        if receipt['tool_sha256'] != {name: digest(module_root/name) for name in tool_names}:
            raise ValueError('Cycle implementation changed during execution')
        receipt.update(status='AWAITING_REVIEW', technical_status='PASS')
    except (OSError, ValueError, RuntimeError, TimeoutError, KeyError, TypeError) as error:
        receipt.update(status='BLOCKED', failed_step=stage, reason=str(error))
        receipt['steps'].append({'name': stage, 'status': 'BLOCKED'})
    finally:
        receipt['finished_at'] = stamp()
        write(output / 'cycle.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--brief', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--voice-python', required=True)
    parser.add_argument('--voice-root', required=True)
    parser.add_argument('--transcription-python')
    parser.add_argument('--revision', help='Explicit revision.json handoff bound to the supplied brief; no approval transfer.')
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--minimum-duration', type=int,
                        help='Require this many seconds of picture from measured narration and from the encoded video.')
    parser.add_argument('--checkpoint', help='Optional new ZIP outside the cycle for exact-state recovery.')
    args = parser.parse_args()
    result = run_cycle(args.brief, args.output, voice_python=args.voice_python,
                       voice_root=args.voice_root, timeout=args.timeout,
                       transcription_python=args.transcription_python, revision_path=args.revision,
                       minimum_duration=args.minimum_duration)
    if args.checkpoint and result['status'] == 'AWAITING_REVIEW':
        from integrations.content_control.cycle_checkpoint import create_checkpoint
        try:
            result = dict(result, checkpoint=create_checkpoint(args.output, args.checkpoint))
        except (OSError, ValueError, RuntimeError) as error:
            # Preserve the completed immutable cycle even if backup fails.
            result = dict(result, checkpoint={'status': 'BLOCKED', 'reason': str(error)})
            print(json.dumps(result, indent=2))
            return 2
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'AWAITING_REVIEW' else 2


if __name__ == '__main__':
    raise SystemExit(main())
