"""Bind offline REA Video diagnostics to an immutable, completed CYZOR cycle."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

from integrations.content_control.cycle_review import inspect_cycle
from integrations.content_control.review_package import digest, no_symlinks, require
from integrations.owned_process import owned_process

PIN = '86486c6e104b917fb4b6a2d6501134686c05b219'
MODEL = 'face_detection_yunet_2023mar.onnx'
MODEL_SHA = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'
LOG_LIMIT = 65536
CUT_TOLERANCE_SECONDS = .125
FLAGS = ('--no-vlm', '--no-whole', '--no-asr', '--no-speakers', '--no-survey',
         '--no-stems', '--no-moments', '--no-packaging', '--workers', '1', '--lang', 'en', '--ocr-lang', 'zh')

# Isolated Python invocation prevents cwd/PYTHONPATH imports. Network denial is
# an application guard for this pinned analyzer, not an OS network sandbox.
BOOTSTRAP = r'''
import hashlib,importlib.util,json,os,socket,subprocess,sys
from importlib.metadata import version
from pathlib import Path
pin,mode,report,video,out=sys.argv[1:]
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def deny(*a,**k):raise RuntimeError('Network and model downloads disabled for cycle diagnostics')
socket.socket.connect=deny;socket.socket.connect_ex=deny;socket.create_connection=deny;socket.getaddrinfo=deny
spec=importlib.util.find_spec('rea_video')
if spec is None or not spec.origin:raise RuntimeError('Installed rea_video package required')
root=Path(spec.origin).resolve().parent.parent
cmd=['git','-C',str(root)]
if subprocess.check_output(cmd+['rev-parse','HEAD'],text=True).strip()!=pin:raise RuntimeError('REA Video source pin mismatch')
if subprocess.check_output(cmd+['status','--porcelain','--untracked-files=no'],text=True).strip():raise RuntimeError('REA Video tracked source modified')
tracked=subprocess.check_output(cmd+['ls-files','-z'],text=True).split('\0')
files={}
for name in tracked:
    if not name or not (name.startswith('rea_video/') or name=='pyproject.toml'):continue
    p=root/name
    if any(q.is_symlink() for q in (p,*p.parents)):raise RuntimeError('Analyzer source symlink rejected')
    files[name]=sha(p)
if not files:raise RuntimeError('Analyzer source manifest empty')
# Fail on untracked executable/data modules that could change the installed package.
actual={str(p.relative_to(root)) for p in (root/'rea_video').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
if actual-set(files):raise RuntimeError('Untracked analyzer package files rejected')
identity={'source_commit':pin,'source_files_sha256':files,'package_root':str(root),
          'versions':{p:version(p) for p in ('rea-video','numpy','opencv-python-headless','Pillow','rapidocr-onnxruntime','onnxruntime','videomd')}}
if mode=='analyze':
    # Refuse missing OCR instead of trusting the CLI's requested-ocr boolean.
    import cv2
    cv2.setNumThreads(2)
    import rea_video.cli as cli
    cli._env=lambda args:None
    from rea_video.overlay import get_ocr
    if get_ocr() is None:raise RuntimeError('Offline OCR runtime unavailable')
    import rea_video.util as util
    util.fetch=deny
    import rea_video.faces as faces
    faces.fetch=deny
    sys.argv=['rea-video','decompose',video,'-o',out,'--no-vlm','--no-whole','--no-asr','--no-speakers','--no-survey','--no-stems','--no-moments','--no-packaging','--workers','1','--lang','en','--ocr-lang','zh']
    result=cli.main()
    if result not in (None,0):raise RuntimeError('Analyzer CLI failed')
    if files!={name:sha(root/name) for name in files}:raise RuntimeError('Analyzer source changed during analysis')
    identity['ocr_runtime_initialized']=True
Path(report).write_text(json.dumps(identity,indent=2,sort_keys=True)+'\n')
'''


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def _run(command, *, log, deadline, env, cwd):
    """Drain stdout continuously, retain only its bounded tail, own descendants."""
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'Analyzer deadline exhausted')
    tail = bytearray()
    def drain(stream):
        while True:
            block = stream.read(8192)
            if not block: break
            tail.extend(block)
            if len(tail) > LOG_LIMIT: del tail[:-LOG_LIMIT]
    try:
        with owned_process(command, timeout=remaining, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           cwd=cwd, env=env) as process:
            thread = threading.Thread(target=drain, args=(process.stdout,), daemon=True); thread.start()
            try:
                code = process.wait(timeout=remaining + 5)
            finally:
                # owned_process closes descendants on failure/timeout; no open
                # descendant pipe can make the parent wait forever.
                thread.join(timeout=1)
        thread.join(timeout=1)
        process.stdout.close()
        require(not thread.is_alive(), 'Analyzer log pipe did not close')
        require(code == 0, 'Analyzer process failed; see ' + log.name)
    finally:
        log.write_bytes(bytes(tail))


def _manifest(directory):
    files = {}; total = 0
    for path in sorted(directory.rglob('*')):
        no_symlinks(path)
        if path.is_dir(): continue
        require(path.is_file(), 'Nonregular diagnostic artifact')
        size = path.stat().st_size; total += size
        require(size <= 64 * 1024 * 1024 and total <= 256 * 1024 * 1024, 'Diagnostic output size limit exceeded')
        files[str(path.relative_to(directory))] = digest(path)
    require({'breakdown.json', 'VIDEO.md', 'storyboard.jpg'} <= set(files), 'Required diagnostics missing')
    return files


def _summarize(directory):
    path = directory / 'breakdown.json'
    require(path.stat().st_size <= 64 * 1024 * 1024, 'Oversized analysis report')
    value = json.loads(path.read_text())
    require(isinstance(value, dict), 'Analysis object required')
    analysis = value.get('analysis', {})
    require(analysis.get('ocr') is True, 'OCR diagnostics missing')
    vlm = analysis.get('vlm', {})
    require(vlm.get('used') is False and vlm.get('requested') is False, 'Unexpected external VLM analysis')
    require(not value.get('stems') and not value.get('speech') and not value.get('speakers'), 'Unexpected optional audio-model operation')
    shots = value.get('shots')
    require(isinstance(shots, list) and 0 < len(shots) <= 2000
            and all(isinstance(shot, dict) for shot in shots), 'Invalid detected shots')
    source = value.get('source')
    duration = source.get('duration') if isinstance(source, dict) else None
    require(type(duration) in (int, float) and 0 < duration <= 1800, 'Invalid analyzer duration')
    boundaries = [shot.get('start') for shot in shots]
    require(all(type(start) in (int, float) and 0 <= start < duration for start in boundaries)
            and all(first < second for first, second in zip(boundaries, boundaries[1:])),
            'Invalid detected shot starts')
    return {'detected_segments': len(shots), 'ocr_requested': True, 'external_vlm_used': False,
            'asr_enabled': False, 'stem_separation_enabled': False,
            'detected_boundaries_seconds': boundaries, 'duration_seconds': duration,
            'scope': 'Heuristic scene/OCR/pixel/audio-signal observations; boundaries can merge editorial cuts. No full audiovisual, voice-quality or creative approval.'}


def _cut_coverage(render, editorial_scenes, summary):
    """Match detected and authored cut times in order without reusing a detection."""
    if 'scenes' not in render:
        return {'status': 'UNAVAILABLE', 'reason': 'Render receipt does not retain measured scenes'}
    rows = render['scenes']
    require(isinstance(rows, list) and rows and len(rows) == len(editorial_scenes)
            and all(isinstance(row, dict) for row in rows)
            and [row.get('scene_id') for row in rows] == [scene['id'] for scene in editorial_scenes],
            'Measured scene identities must match the editorial')
    starts = [row.get('start') for row in rows]
    duration = summary['duration_seconds']
    require(starts[0] == 0 and all(type(start) in (int, float) and 0 <= start < duration for start in starts)
            and all(first < second for first, second in zip(starts, starts[1:])), 'Invalid measured scene starts')
    detected = [start for start in summary['detected_boundaries_seconds'] if start != 0]
    matched = []
    missing = []
    unmatched = []
    next_detection = 0
    for row, start in zip(rows[1:], starts[1:]):
        while next_detection < len(detected) and detected[next_detection] < start - CUT_TOLERANCE_SECONDS:
            unmatched.append(detected[next_detection])
            next_detection += 1
        cut = {'scene_id': row['scene_id'], 'authored_seconds': start}
        if next_detection < len(detected) and detected[next_detection] <= start + CUT_TOLERANCE_SECONDS:
            matched.append({**cut, 'detected_seconds': detected[next_detection]})
            next_detection += 1
        else:
            missing.append(cut)
    unmatched.extend(detected[next_detection:])
    if missing:
        status = 'MISSING_AUTHORED_CUTS'
    else:
        status = 'ALL_AUTHORED_CUTS_MATCHED' if matched else 'NO_AUTHORED_CUTS'
    return {'status': status, 'tolerance_seconds': CUT_TOLERANCE_SECONDS,
            'matched_cuts': matched, 'missing_cuts': missing, 'unmatched_detected_seconds': unmatched}


def _authored_samples(root, output, before, coverage, deadline):
    """Provide authored navigation when the analyzer misses cuts."""
    if coverage['status'] != 'MISSING_AUTHORED_CUTS':
        return {'status': 'NOT_REQUESTED', 'reason': coverage['status']}
    remaining = min(600, math.floor(deadline - time.monotonic()))
    if remaining < 10:
        return {'status': 'BLOCKED', 'reason': 'Less than ten seconds remain for authored samples'}
    target = output / 'authored-scenes'
    try:
        from integrations.content_control.cycle_scene_review import make_scene_review

        review = make_scene_review(root, target, timeout=remaining)
        receipt_path = target / 'scene-review.json'
        no_symlinks(receipt_path)
        raw = receipt_path.read_bytes()
        require(json.loads(raw) == review, 'Authored sample receipt changed')
        require(review.get('candidate_sha256') == before['candidate_sha256'] and
                review.get('source_files_sha256') == before['files_sha256'],
                'Authored samples do not bind the analyzed cycle')
        identity = {'receipt': 'authored-scenes/scene-review.json', 'receipt_sha256': hashlib.sha256(raw).hexdigest()}
        if review['status'] != 'SCENE_SAMPLES_READY':
            return {'status': 'BLOCKED', 'reason': review.get('reason', 'Authored samples unavailable'),
                    **identity}
        return {'status': 'SCENE_SAMPLES_READY', **identity, 'gallery': 'authored-scenes/index.html',
                'sampled_scene_count': review['sampled_scene_count'],
                'scope': 'Bound authored midpoint stills for navigation. Detector misses remain unchanged.'}
    except (ImportError, OSError, ValueError, RuntimeError, KeyError) as error:
        return {'status': 'BLOCKED', 'reason': str(error)}


def analyze_cycle(cycle_dir, output, *, runtime, timeout=300):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 1800:
        raise ValueError('Analyzer deadline must be 1..1800 seconds')
    for name in ('PUBLICATION_ENABLED','PAID_GENERATION_ENABLED'):
        require(os.environ.get(name,'false').lower() == 'false', name + ' must remain false')
    root = Path(os.path.abspath(cycle_dir)); output = Path(os.path.abspath(output))
    no_symlinks(root); no_symlinks(output)
    require(not output.exists(), 'Output already exists')
    require(not output.is_relative_to(root) and not root.is_relative_to(output), 'Output must not overlap the cycle')
    interpreter = Path(runtime)
    # Standard virtualenv interpreters are symlinks; cycle, output and source
    # artifacts must not be symlinks. Retain venv path for installed dependencies.
    require(interpreter.is_absolute() and interpreter.is_file() and os.access(interpreter, os.X_OK), 'Absolute installed Python runtime required')
    before = inspect_cycle(root)
    render_raw = (root / 'delivery/render.json').read_bytes()
    require(hashlib.sha256(render_raw).hexdigest() == before['files_sha256']['delivery/render.json'],
            'Render receipt changed before diagnostics')
    render = json.loads(render_raw)
    model_dir = Path(os.environ.get('REA_VIDEO_MODELS', str(Path.home() / '.cache/rea-video/models'))).absolute()
    model = model_dir / MODEL; no_symlinks(model)
    require(model.is_file() and digest(model) == MODEL_SHA, 'Verified cached YuNet model required; downloads disabled')
    output.mkdir(parents=True)
    deadline = time.monotonic() + timeout
    receipt = {'schema_version':1,'status':'BLOCKED','started_at':datetime.now(timezone.utc).isoformat(),
               'candidate_sha256':before['candidate_sha256'],'cycle_files_sha256':before['files_sha256'],
               'publication_enabled':False,'paid_generation_enabled':False,'production_approved':False,
               'full_av_review':False,'production_ready':False,'independent_creative_verification':False,
               'source_commit':PIN,'adapter_sha256':digest(__file__),
               'scope':'Pinned offline diagnostic execution bound to this exact completed cycle, not approval.'}
    _write(output / 'analysis.json', receipt)
    try:
        home = output / 'isolated-home'; home.mkdir()
        cache = home / 'models'; cache.mkdir(); shutil.copyfile(model, cache / MODEL)
        env = {'PATH':os.defpath,'HOME':str(home),'REA_VIDEO_HOME':str(home / 'prefs'),
               'REA_VIDEO_MODELS':str(cache),'REA_OCR_LANG':'zh','HF_HUB_OFFLINE':'1',
               'TRANSFORMERS_OFFLINE':'1','OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2',
               'MKL_NUM_THREADS':'2','PUBLICATION_ENABLED':'false','PAID_GENERATION_ENABLED':'false'}
        # Analyze an immutable copied candidate, never pass an input URL.
        copied = output / 'candidate.mp4'; shutil.copyfile(root / 'delivery/video.mp4', copied)
        require(digest(copied) == before['candidate_sha256'], 'Candidate copy identity mismatch')
        diagnostics = output / 'diagnostics'
        cmd = [str(interpreter), '-I', '-c', BOOTSTRAP, PIN]
        _run(cmd + ['probe', str(output/'analyzer-before.json'), str(copied), str(diagnostics)],
             log=output/'probe.log', deadline=deadline, env=env, cwd=output)
        identity = json.loads((output/'analyzer-before.json').read_text())
        _run(cmd + ['analyze', str(output/'analyzer-after.json'), str(copied), str(diagnostics)],
             log=output/'analyze.log', deadline=deadline, env=env, cwd=output)
        after_identity = json.loads((output/'analyzer-after.json').read_text())
        require(after_identity.pop('ocr_runtime_initialized', False) is True and after_identity == identity,
                'Analyzer installation changed or OCR unavailable')
        manifest = _manifest(diagnostics); summary = _summarize(diagnostics)
        coverage = _cut_coverage(render, before['editorial']['scenes'], summary)
        summary['authored_cut_coverage'] = coverage
        samples = _authored_samples(root, output, before, coverage, deadline)
        require(inspect_cycle(root)['files_sha256'] == before['files_sha256'], 'Cycle changed during diagnostics')
        require(digest(copied) == before['candidate_sha256'], 'Analyzed candidate changed')
        require(digest(cache/MODEL) == MODEL_SHA, 'Local model changed')
        require(digest(__file__) == receipt['adapter_sha256'], 'Adapter changed during diagnostics')
        require(time.monotonic() <= deadline, 'Analyzer deadline exhausted')
        receipt.update(status='PARTIAL_DIAGNOSTIC' if samples['status'] == 'BLOCKED' else 'DIAGNOSTIC_COMPLETE',
                       analyzer=identity, diagnostics_files_sha256=manifest,
                       summary=summary, authored_scene_samples=samples, model_sha256={MODEL:MODEL_SHA},
                       analysis_entrypoint='diagnostics/VIDEO.md', execution_flags=list(FLAGS),
                       no_provider_environment=True, network_policy='Python sockets denied; no model downloads or provider calls requested')
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,subprocess.TimeoutExpired) as error:
        receipt.update(status='BLOCKED',reason=str(error),partial_outputs_retained=True)
    finally:
        receipt['finished_at']=datetime.now(timezone.utc).isoformat();_write(output/'analysis.json',receipt)
    return receipt
