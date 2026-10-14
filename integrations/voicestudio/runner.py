"""Bounded English narration through the pinned official VoiceStudio backend."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from setup_runtime import REVISION, MODEL, MODEL_REVISION

VOICES={f'expr-voice-{n}-{sex}' for n in range(2,6) for sex in ('m','f')}


def validate_request(request):
    if set(request)-{'text','voice','speed','language','publication_enabled','paid_generation_enabled'}:
        raise ValueError('Unsupported narration option')
    if request.get('publication_enabled') is not False or request.get('paid_generation_enabled') is not False:
        raise ValueError('Explicit free, publication-disabled request required')
    text=request.get('text')
    if not isinstance(text,str) or not 1<=len(text.strip())<=1200 or not any(c.isalpha() for c in text):
        raise ValueError('Provide 1..1200 characters of speakable English text')
    voice=request.get('voice','expr-voice-2-f')
    speed=request.get('speed',1.0)
    if voice not in VOICES: raise ValueError('Unsupported preset voice')
    if isinstance(speed,bool) or not isinstance(speed,(float,int)) or not math.isfinite(speed) or not .75<=speed<=1.5:
        raise ValueError('Speed must be between .75 and 1.5')
    if request.get('language','en')!='en': raise ValueError('This engine supports English only')
    return text,voice,float(speed)


def run(upstream,runtime,input_path,output):
    upstream=Path(upstream).resolve();runtime=Path(runtime).resolve();output=Path(output)
    text,voice,speed=validate_request(json.loads(Path(input_path).read_text()))
    metadata=Path(str(output)+'.generation.json')
    if output.exists() or output.is_symlink() or metadata.exists() or metadata.is_symlink(): raise FileExistsError('Output already exists')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=upstream,text=True).strip()
    if revision!=REVISION:raise ValueError('Unreviewed VoiceStudio revision')
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=upstream,text=True).strip(): raise ValueError('Modified upstream source')
    manifest=json.loads((runtime/'model-manifest.json').read_text())
    if manifest['model']!=MODEL or manifest['revision']!=MODEL_REVISION:raise ValueError('Unexpected model manifest')
    cache=runtime/'hf-cache';snapshot=cache/'models--KittenML--kitten-tts-mini-0.8'/'snapshots'/MODEL_REVISION
    if (cache/'models--KittenML--kitten-tts-mini-0.8'/'refs/main').read_text().strip()!=MODEL_REVISION:raise ValueError('Mutable model ref differs')
    for name,digest in manifest['files'].items():
        if Path(name).name!=name or hashlib.sha256((snapshot/name).read_bytes()).hexdigest()!=digest:raise ValueError('Model bytes differ')
    with tempfile.TemporaryDirectory(prefix='money-factory-voice-') as home:
        # Clear inherited model/provider credentials before loading SDKs.
        path=os.environ.get('PATH','');os.environ.clear()
        os.environ.update({'PATH':path,'HOME':home,'OMNIVOICE_DATA_DIR':home,'HF_HUB_CACHE':str(cache),
          'HF_HUB_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','HF_HUB_DISABLE_IMPLICIT_TOKEN':'1',
          'OMNIVOICE_TTS_BACKEND':'kittentts','OMNIVOICE_KITTENTTS_MODEL':MODEL,'OMP_NUM_THREADS':'2'})
        sys.path.insert(0,str(upstream/'backend'))
        import numpy as np
        import soundfile as sf
        import torch
        from services.tts_backend import KittenTTSBackend,ensure_engine_licence
        from services.watermark import mark_synthetic
        ensure_engine_licence(KittenTTSBackend)
        engine=KittenTTSBackend();start=time.monotonic()
        waveform=engine.generate(text,voice=voice,speed=speed,language='en')
        marked=mark_synthetic(waveform,engine.sample_rate,context='money_factory.narration')
        applied=marked is not waveform
        samples=marked.detach().cpu().numpy().reshape(-1)
        if not np.isfinite(samples).all() or not np.any(samples):raise ValueError('Invalid generated waveform')
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('xb') as handle: sf.write(handle,samples,engine.sample_rate,format='WAV',subtype='PCM_16')
        from validation import validate_audio
        audio=validate_audio(output)
        record={'schema_version':1,'status':'PASS','tool':'voicestudio','operation':'synthesize','engine':'kittentts',
          'upstream_revision':revision,'model':MODEL,'model_revision':MODEL_REVISION,'model_files_sha256':manifest['files'],
          'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'voice':voice,'speed':speed,'language':'en',
          'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'audio':audio,
          'generation_seconds':round(time.monotonic()-start,3),'synthetic':True,'watermark_applied':applied,
          'watermark_status':'applied_not_independently_detected' if applied else 'not_applied_upstream_optional_audioseal_unavailable_or_failed',
          'publication_enabled':False,'paid_generation_enabled':False,'production_ready':False,
          'scope':'Actual CPU English preset speech; no cloning, perceptual approval, or commercial-rights clearance'}
        with metadata.open('x') as handle:json.dump(record,handle,indent=2);handle.write('\n')
        return record


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--upstream',required=True);p.add_argument('--runtime',required=True);p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(json.dumps(run(a.upstream,a.runtime,a.input,a.output),indent=2))
