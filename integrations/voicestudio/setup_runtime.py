"""Install the focused official VoiceStudio/Kitten CPU runtime and pinned model."""
import json
from pathlib import Path
import subprocess
import sys

REVISION = '4df5033e5a1a92e22936fb4d7d2d39e03cf10a91'
MODEL = 'KittenML/kitten-tts-mini-0.8'
MODEL_REVISION = 'c02725660cea441db4c383af69f1f26f5cd00947'


def setup(upstream, runtime):
    upstream=Path(upstream).resolve(); runtime=Path(runtime).resolve()
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=upstream,text=True).strip()
    if revision!=REVISION: raise ValueError('Unexpected VoiceStudio revision')
    subprocess.run([sys.executable,'-m','venv',str(runtime)],check=True)
    python=runtime/'bin/python'
    subprocess.run([str(python),'-m','pip','install','torch==2.8.0+cpu','--index-url','https://download.pytorch.org/whl/cpu'],check=True)
    subprocess.run([str(python),'-m','pip','install','-r',str(Path(__file__).with_name('requirements.txt'))],check=True)
    subprocess.run([str(python),str(Path(__file__).with_name('setup_runtime.py')),'--download-model',str(runtime)],check=True)


def download(runtime):
    import hashlib
    from huggingface_hub import snapshot_download
    runtime=Path(runtime); cache=runtime/'hf-cache'
    snapshot=Path(snapshot_download(MODEL,revision=MODEL_REVISION,cache_dir=cache,token=False))
    config=json.loads((snapshot/'config.json').read_text())
    files=['config.json',config['model_file'],config['voices']]
    manifest={name:hashlib.sha256((snapshot/name).read_bytes()).hexdigest() for name in files}
    # SDK 0.8.1 exposes no revision parameter; bind its offline main lookup to
    # the reviewed snapshot in this dedicated cache. No upstream code patched.
    refs=cache/'models--KittenML--kitten-tts-mini-0.8'/'refs'; refs.mkdir(exist_ok=True,parents=True)
    (refs/'main').write_text(MODEL_REVISION)
    (runtime/'model-manifest.json').write_text(json.dumps({'model':MODEL,'revision':MODEL_REVISION,'files':manifest},indent=2)+'\n')


if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--download-model': raise SystemExit('Use setup(upstream, runtime)')
    download(sys.argv[2])
