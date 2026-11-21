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
    require(isinstance(shots, list) and 0 < len(shots) <= 2000, 'Invalid detected shots')
    return {'detected_segments': len(shots), 'ocr_requested': True, 'external_vlm_used': False,
            'asr_enabled': False, 'stem_separation_enabled': False,
            'detected_boundaries_seconds': [shot.get('start') for shot in shots],
            'duration_seconds': value.get('source', {}).get('duration'),
            'scope': 'Heuristic scene/OCR/pixel/audio-signal observations; boundaries can merge editorial cuts. No full audiovisual, voice-quality or creative approval.'}


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
        require(inspect_cycle(root)['files_sha256'] == before['files_sha256'], 'Cycle changed during diagnostics')
        require(digest(copied) == before['candidate_sha256'], 'Analyzed candidate changed')
        require(digest(cache/MODEL) == MODEL_SHA, 'Local model changed')
        require(digest(__file__) == receipt['adapter_sha256'], 'Adapter changed during diagnostics')
        require(time.monotonic() <= deadline, 'Analyzer deadline exhausted')
        receipt.update(status='DIAGNOSTIC_COMPLETE', analyzer=identity, diagnostics_files_sha256=manifest,
                       summary=summary, model_sha256={MODEL:MODEL_SHA},
                       analysis_entrypoint='diagnostics/VIDEO.md', execution_flags=list(FLAGS),
                       no_provider_environment=True, network_policy='Python sockets denied; no model downloads or provider calls requested')
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,subprocess.TimeoutExpired) as error:
        receipt.update(status='BLOCKED',reason=str(error),partial_outputs_retained=True)
    finally:
        receipt['finished_at']=datetime.now(timezone.utc).isoformat();_write(output/'analysis.json',receipt)
    return receipt
