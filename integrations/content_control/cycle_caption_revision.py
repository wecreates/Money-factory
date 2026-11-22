"""Explicit caption text edits in a new cycle; no audio/listening verification."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time

from integrations.content_control.cycle_package import package_cycle, copy_file
from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control.cycle_lineage import _pairs, _constant
from integrations.content_control.review_package import digest, no_symlinks, require

FLAGS = {k: False for k in ('publication_enabled', 'paid_generation_enabled', 'production_approved',
                           'full_av_review', 'production_ready', 'factual_review', 'competitor_comparison')}
TIMING = re.compile(r'\d{2,}:[0-5]\d:[0-5]\d\.\d{3} --> \d{2,}:[0-5]\d:[0-5]\d\.\d{3}')


def _text(value, maximum):
    require(isinstance(value, str) and 0 < len(value.strip()) <= maximum and
            not any(ord(c) < 32 or ord(c) == 127 for c in value) and
            not any(c in value for c in '<>&'), 'Bounded plain single-line text required')
    return value


def correct_vtt(raw, edits):
    """Edit only selected text lines; every timing and separator byte is retained."""
    require(len(raw) <= 1024 * 1024, 'Caption file oversized')
    text = raw.decode('utf-8')
    require(text.startswith('WEBVTT\n\n'), 'Plain LF WebVTT required')
    lines = text.splitlines(keepends=True)
    positions = []
    index = 2
    while index < len(lines):
        if lines[index] == '\n':
            index += 1; continue
        require(TIMING.fullmatch(lines[index].rstrip('\n')) is not None, 'Unsupported caption timing or block')
        index += 1
        require(index < len(lines), 'Missing caption text')
        _text(lines[index].rstrip('\n'), 2000)
        positions.append(index)
        index += 1
        require(index == len(lines) or lines[index] == '\n', 'Only plain single-line cues supported')
    require(isinstance(edits, list) and 1 <= len(edits) <= 100, 'One to 100 explicit edits required')
    seen = set()
    for edit in edits:
        require(isinstance(edit, dict) and set(edit) == {'cue','before','after'}, 'Exact cue/before/after fields required')
        cue = edit['cue']
        require(type(cue) is int and 1 <= cue <= len(positions) and cue not in seen, 'Invalid or duplicate cue')
        seen.add(cue)
        before, after = _text(edit['before'], 2000), _text(edit['after'], 2000)
        require(before != after, 'Caption edit must change text')
        pos = positions[cue-1]
        require(lines[pos].rstrip('\n') == before, 'Caption before text does not match')
        lines[pos] = after + ('\n' if lines[pos].endswith('\n') else '')
    return ''.join(lines).encode('utf-8')


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def revise_captions(cycle_dir, edits_path, output, timeout=180):
    require(type(timeout) is int and 10 <= timeout <= 600, 'Timeout must be 10..600 seconds')
    require(all(os.environ.get(k,'false').lower() == 'false' for k in
                ('PUBLICATION_ENABLED','PAID_GENERATION_ENABLED')), 'Publishing and paid generation must remain disabled')
    root, source, output = (Path(os.path.abspath(p)) for p in (cycle_dir, edits_path, output))
    for p in (root, source, output): no_symlinks(p)
    require(not output.exists() and not output.is_relative_to(root) and
            output != source and not source.is_relative_to(output), 'Fresh output separate from source inputs required')
    require(source.is_file() and source.stat().st_size <= 64*1024, 'Missing or oversized edits input')
    raw = source.read_bytes()
    submitted = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    require(isinstance(submitted, dict) and set(submitted) ==
            {'candidate_sha256','caption_sha256','reviewer','rationale','edits'}, 'Exact caption-edit fields required')
    reviewer, rationale = _text(submitted['reviewer'],200), _text(submitted['rationale'],4000)
    deadline = time.monotonic()+timeout
    snapshot = inspect_cycle(root)
    require(submitted['candidate_sha256'] == snapshot['candidate_sha256'] and
            submitted['caption_sha256'] == snapshot['files_sha256']['delivery/captions.vtt'], 'Caption edit identity mismatch')
    old_captions = (root/'delivery/captions.vtt').read_bytes()
    corrected = correct_vtt(old_captions, submitted['edits'])
    proof = {'source_cycle_sha256':snapshot['files_sha256']['cycle.json'],
             'source_package_sha256':snapshot['files_sha256']['delivery/package.json'],
             'source_render_receipt_sha256':snapshot['files_sha256']['render/render.json'],
             'source_caption_sha256':submitted['caption_sha256'],
             'edits_sha256':hashlib.sha256(raw).hexdigest(), 'submitted_edits_json':raw.decode('utf-8'),
             'reviewer':reviewer, 'rationale':rationale, 'listening_verified':False,
             'scope':'Supplied text correction only; source audio and cue timings unchanged; no listening or new ASR verification.'}
    output.mkdir(parents=True,exist_ok=False)
    result = {'schema_version':1,'status':'BLOCKED','technical_status':'PENDING',**FLAGS,
              'operation':'caption_text_revision','started_at':datetime.now(timezone.utc).isoformat(),
              'caption_revision':proof,'candidate_sha256':snapshot['candidate_sha256'],
              'brief_sha256':snapshot['cycle']['brief_sha256'],
              'editorial_sha256':snapshot['cycle']['editorial_sha256'],
              'scope':'New review package for unchanged media with explicit caption correction; no fresh synthesis or creative approval.',
              'steps':[], 'tool_sha256':{'cycle_caption_revision.py':digest(Path(__file__))}}
    if 'revision_lineage' in snapshot['cycle']: result['revision_lineage']=snapshot['cycle']['revision_lineage']
    try:
        for name in ('brief.json','editorial.json'): copy_file(root/name,output/name,deadline)
        render = output/'render'; render.mkdir()
        copy_file(root/'render/video.mp4',render/'video.mp4',deadline)
        (render/'captions.vtt').write_bytes(corrected)
        rendered = json.loads((root/'render/render.json').read_text())
        # Keep the origin renderer's geometry/scope for identical thumbnail framing.
        # Caption-specific claims are superseded; the prior ASR hash is provenance only.
        prior_asr = rendered.pop('transcription_receipt_sha256',None)
        rendered.update(caption_sha256=digest(render/'captions.vtt'), caption_timing='editorial_text_correction',
                        independent_transcription_verified=False, caption_revision=dict(proof, prior_asr_receipt_sha256=prior_asr),
                        operation='caption_text_revision', **FLAGS)
        _write(render/'render.json',rendered)
        result['steps'].append({'name':'caption_text_revision','status':'PASS'})
        packaged = package_cycle(snapshot['editorial'],render,output/'delivery',deadline=deadline)
        result.update(package_sha256=digest(output/'delivery/package.json'), archive_sha256=packaged['archive_sha256'])
        require(inspect_cycle(root)==snapshot and source.read_bytes()==raw,'Caption revision inputs changed')
        require(time.monotonic()<deadline,'Caption revision deadline exhausted')
        result['steps'].append({'name':'package','status':'PASS'})
        result.update(status='AWAITING_REVIEW',technical_status='PASS')
        result['finished_at']=datetime.now(timezone.utc).isoformat();_write(output/'cycle.json',result)
        inspect_cycle(output)
    except (OSError, ValueError, RuntimeError, TimeoutError, KeyError, TypeError) as error:
        result.update(status='BLOCKED',technical_status='FAIL',reason=str(error))
    finally:
        result['finished_at']=datetime.now(timezone.utc).isoformat();_write(output/'cycle.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cycle-dir',required=True);p.add_argument('--edits',required=True);p.add_argument('--output',required=True)
    p.add_argument('--timeout',type=int,default=180);a=p.parse_args()
    result=revise_captions(a.cycle_dir,a.edits,a.output,a.timeout)
    print(json.dumps(result,indent=2));return 0 if result['status']=='AWAITING_REVIEW' else 2


if __name__=='__main__':raise SystemExit(main())
