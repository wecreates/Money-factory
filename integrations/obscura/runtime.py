"""Pinned normal-render Obscura release; no upstream changes or global installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import tarfile
import tempfile
from urllib.request import build_opener

PIN = {
    'repository': 'https://github.com/h4ckf0r0day/obscura',
    'version': '0.2.7', 'revision': '0ecc41770da5c5300227dd83a15bfa1e5100d5d4',
    'platform': 'x86_64-linux', 'features': 'render,non-stealth',
    'url': 'https://github.com/h4ckf0r0day/obscura/releases/download/v0.2.7/obscura-x86_64-linux.tar.gz',
    'archive_size': 72018118,
    'archive_sha256': '11b53d27cd743e00e196e216920e7f3f794cf378e3f1792b8d25d3beabaf9cad',
    'files': {
        'obscura': {'size': 80903256, 'sha256': '547f9d8a60048983f0e45c310f160d1239575af062af28e4f6755e361f8abcbf'},
        'obscura-worker': {'size': 75983952, 'sha256': '6956274a7e517666386493962866f95a39ace2f71d864ad2e3bac7640145c311'},
    },
}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def no_links(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Runtime paths must not contain symlinks')
    return path


def verify_source_manifest(source):
    path = no_links(Path(source) / 'release-pin.json')
    if json.loads(path.read_text()) != PIN:
        raise ValueError('Obscura release manifest does not match the reviewed pin')
    return Path(source)


def verify_runtime(runtime_dir):
    runtime = no_links(runtime_dir)
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        raise ValueError('Pinned Obscura runtime requires Linux x86_64 (WSL2 is supported)')
    for name, expected in PIN['files'].items():
        path = no_links(runtime / name)
        if (not path.is_file() or path.stat().st_size != expected['size']
                or digest(path) != expected['sha256'] or not os.access(path, os.X_OK)):
            raise ValueError('Pinned Obscura executable mismatch: ' + name)
    return runtime / 'obscura'


def install(runtime_dir, archive=None):
    """Explicit public download or hash-verified cached archive; never overwrite."""
    runtime = no_links(runtime_dir)
    if runtime.exists():
        return verify_runtime(runtime)
    runtime.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='obscura-install-', dir=runtime.parent) as temporary:
        staging = Path(temporary)
        cached = Path(archive) if archive is not None else staging / 'release.tar.gz'
        if archive is None:
            opener = build_opener()  # Honor the host network route for this explicit public download.
            with opener.open(PIN['url'], timeout=60) as incoming, cached.open('xb') as outgoing:
                total = 0
                while chunk := incoming.read(1024 * 1024):
                    total += len(chunk)
                    if total > PIN['archive_size']:
                        raise ValueError('Oversized release archive')
                    outgoing.write(chunk)
        if (cached.is_symlink() or not cached.is_file() or cached.stat().st_size != PIN['archive_size']
                or digest(cached) != PIN['archive_sha256']):
            raise ValueError('Release archive hash or size mismatch')
        unpacked = staging / 'runtime'; unpacked.mkdir()
        with tarfile.open(cached, 'r:gz') as bundle:
            members = bundle.getmembers()
            if len(members) != 2 or {item.name for item in members} != set(PIN['files']):
                raise ValueError('Unexpected release archive members')
            for item in members:
                expected = PIN['files'][item.name]
                if not item.isfile() or item.size != expected['size']:
                    raise ValueError('Nonregular or oversized release member')
                with bundle.extractfile(item) as incoming, (unpacked / item.name).open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                (unpacked / item.name).chmod(0o755)
        verify_runtime(unpacked)
        (unpacked / 'release-pin.json').write_text(json.dumps(PIN, indent=2) + '\n')
        # Reserve the final name exclusively, then install only our verified files.
        runtime.mkdir(mode=0o700)
        try:
            for path in unpacked.iterdir():
                os.replace(path, runtime / path.name)
        except BaseException:
            shutil.rmtree(runtime)
            raise
    return verify_runtime(runtime)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    print(install(args.runtime, args.archive))
