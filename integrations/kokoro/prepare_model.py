"""Explicitly fetch only the pinned 92.4 MB q8 model and three small configs.

Run after npm ci --ignore-scripts in an isolated operator-owned runtime. This is
setup, never part of inference. No credentials, paid services or voice uploads.
"""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path
import tempfile
import urllib.request
from integrations.kokoro.preview import HERE, digest, verify_assets


def prepare(runtime):
    runtime = Path(runtime).absolute()
    if digest(runtime / 'package-lock.json') != digest(HERE / 'package-lock.json'):
        raise ValueError('Install the exact reviewed npm lock first')
    manifest = json.loads((HERE / 'model-manifest.json').read_text())
    deadline = time.monotonic() + 300
    for name, expected in manifest['files'].items():
        if name.startswith('voices/'):
            continue  # The npm package contains these pinned stock voice files.
        destination = runtime / 'model' / name
        if destination.is_symlink():
            raise ValueError('Model destination must not be a symlink')
        if destination.exists():
            if digest(destination) != expected['sha256']:
                raise ValueError('Existing model bytes differ; refusing replacement')
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = f'https://huggingface.co/{manifest["model_repository"]}/resolve/{manifest["model_revision"]}/{name}'
        temporary = None
        try:
            with urllib.request.urlopen(url, timeout=30) as response, tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
                temporary = Path(output.name)
                total = 0
                while chunk := response.read(1024 * 1024):
                    if time.monotonic() > deadline:
                        raise TimeoutError('Pinned setup exceeded five-minute download bound')
                    total += len(chunk)
                    if total > expected['size_bytes']:
                        raise ValueError('Model download exceeded pinned size')
                    output.write(chunk)
            if total != expected['size_bytes'] or digest(temporary) != expected['sha256']:
                raise ValueError('Model download hash mismatch')
            # Atomic exclusive publication of verified bytes on the same filesystem.
            os.link(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    verify_assets(runtime)
    return {'status': 'PINNED_RUNTIME_ASSETS_VERIFIED', 'model_revision': manifest['model_revision'],
            'quantization': 'q8', 'publication_enabled': False, 'inference_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.runtime), indent=2))
