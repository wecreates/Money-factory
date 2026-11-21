"""Read-only, offline prerequisites for the pinned Content Control picture flow.

No source module is imported by the source inspector. Runtime probes use existing
operator-selected executables only; no install, model load, render or service starts.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

SOURCES = (
    'package.json', 'package-lock.json', 'requirements-transcription.txt', 'requirements-picture-render.txt',
    'remotion/V9ArticulatedVisual.jsx', 'remotion/episode1-picture-timeline.mjs',
    'state/episode1-factual-contract.json', 'state/episode1-sync-contract.json',
    'public/audio/episode1-narration.mp3', 'public/audio/episode1-music.mp3',
    'public/audio/episode1-sfx-1.mp3', 'public/audio/episode1-sfx-2.mp3',
    'scripts/produce_episode1_review.py', 'scripts/render_episode1_pictures.mjs',
    'scripts/free_transcription_qa.py', 'scripts/caption_contract.py',
    'scripts/build_verified_captions.py', 'scripts/verify_muxed_narration.py',
    'scripts/review_smoke_inputs.py', 'scripts/free_mobile_compat_qa.py', 'scripts/free_audio_qa.py',
    'scripts/verify_episode1_sync.py',
)
MAX_OUTPUT = 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def safe_environment():
    env = {name: os.environ[name] for name in ('PATH', 'HOME', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'HF_HOME', 'HF_HUB_CACHE') if name in os.environ}
    env.update(PUBLICATION_ENABLED='false', PAID_GENERATION_ENABLED='false',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1',
               LANG='C.UTF-8', LC_ALL='C.UTF-8', GIT_OPTIONAL_LOCKS='0')
    return env


def probe(command, *, cwd=None, timeout=20, lease_fd=None):
    from integrations.owned_process import owned_process
    with tempfile.TemporaryFile() as output:
        with owned_process(list(map(str, command)), timeout=timeout, cwd=cwd, lease_fd=lease_fd,
                           env=safe_environment(), stdout=output, stderr=subprocess.DEVNULL) as process:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if time.monotonic() >= deadline or os.fstat(output.fileno()).st_size > MAX_OUTPUT:
                    raise ValueError('diagnostic_timeout_or_output_limit')
                time.sleep(.02)
            if process.returncode:
                raise ValueError('diagnostic_command_failed')
            output.seek(0)
            raw = output.read(MAX_OUTPUT + 1)
            if len(raw) > MAX_OUTPUT:
                raise ValueError('diagnostic_output_limit')
            return raw.decode('utf-8')


def git(root, *args, lease_fd=None):
    return probe(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null', '-C', root, *args], lease_fd=lease_fd)


def regular_source(root, name):
    path = root / name
    if any(part.is_symlink() for part in (path, *path.parents) if part != root.parent):
        raise ValueError('source_symlink_forbidden')
    if not path.is_file() or path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('source_missing_or_oversized')
    return path


def describe_source(root, expected_commit=None, lease_fd=None):
    root = Path(root).absolute()
    def read_git(*args):
        return git(root, *args, lease_fd=lease_fd)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('source_root_invalid')
    commit = read_git('rev-parse', '--verify', 'HEAD').strip()
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or (expected_commit is not None and commit != expected_commit):
        raise ValueError('source_commit_mismatch')
    # Require a checkout of this repository root, not a nested directory.
    if Path(read_git('rev-parse', '--show-toplevel').strip()).resolve() != root.resolve():
        raise ValueError('source_root_not_repository_root')
    if read_git('status', '--porcelain', '--untracked-files=no').strip():
        raise ValueError('tracked_source_checkout_dirty')
    if read_git('ls-files', '--others', '--exclude-standard', '--', 'scripts', 'remotion').strip():
        raise ValueError('untracked_executable_source')
    script = regular_source(root, 'scripts/produce_episode1_review.py')
    tree = ast.parse(script.read_text())
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'SOURCES' for target in node.targets)]
    if len(assignments) != 1 or ast.literal_eval(assignments[0].value) != SOURCES:
        raise ValueError('unsupported_source_manifest')
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'produce']
    if len(functions) != 1 or 'command_runner' not in [argument.arg for argument in functions[0].args.kwonlyargs]:
        raise ValueError('owned_command_runner_interface_missing')
    source_files = {}
    for name in SOURCES:
        path = regular_source(root, name)
        # Compare bytes to HEAD, independent of index assume-unchanged flags.
        entry = read_git('ls-tree', 'HEAD', '--', name).strip().split()
        if len(entry) != 4 or entry[0] not in ('100644', '100755') or entry[1] != 'blob' or entry[3] != name:
            raise ValueError('source_not_tracked_regular_file')
        actual_git_blob = read_git('hash-object', '--no-filters', '--', name).strip()
        if actual_git_blob != entry[2]:
            raise ValueError('source_bytes_differ_from_commit')
        source_files[name] = sha(path)
    for name in ('state/episode1-factual-contract.json', 'state/episode1-sync-contract.json'):
        if json.loads((root / name).read_text()).get('publication_enabled') is not False:
            raise ValueError('source_publication_contract_not_disabled')
    return {'source_commit': commit, 'source_manifest_sha256': hashlib.sha256(canonical(source_files).encode()).hexdigest(),
            'source_files': source_files, 'source_count': len(source_files)}


def inspect_runtime(root, video_python, picture_python, lease_fd=None):
    root = Path(root).absolute()
    def read_probe(command, **kwargs):
        return probe(command, lease_fd=lease_fd, **kwargs)
    checks, details, blockers = {}, {}, []
    def check(name, operation):
        try:
            value = operation()
            checks[name] = True
            details[name] = value
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, SyntaxError):
            checks[name] = False
            blockers.append(name)
    def python_runtime(executable, package, expected, imports):
        source = ('import sys,json,importlib.metadata as m;' + imports +
                  ';print("CYZOR_RUNTIME="+json.dumps({"python":list(sys.version_info[:3]),"version":m.version(' + repr(package) + ')}))')
        raw = read_probe([executable, '-I', '-B', '-c', source], timeout=30)
        rows = [line.removeprefix('CYZOR_RUNTIME=') for line in raw.splitlines() if line.startswith('CYZOR_RUNTIME=')]
        if len(rows) != 1:
            raise ValueError('runtime_metadata_missing')
        result = json.loads(rows[0])
        if result['python'] < [3, 11] or result['version'] != expected:
            raise ValueError('runtime_version_mismatch')
        return result
    check('transcription_python', lambda: python_runtime(video_python, 'faster-whisper', '1.2.1', 'import faster_whisper,ctranslate2,numpy;import importlib.util;namespace=importlib.util.find_spec("scripts");assert namespace is None or namespace.origin is None'))
    check('picture_python', lambda: python_runtime(picture_python, 'CairoSVG', '2.9.1',
          'import cairosvg;assert cairosvg.svg2png(bytestring=b\'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>\').startswith(b"\\x89PNG")'))
    def node_runtime():
        version = read_probe(['node', '--version']).strip()
        parts = tuple(map(int, version.lstrip('v').split('.')))
        if not ((24, 16, 0) <= parts < (25, 0, 0) or parts >= (26, 1, 0)):
            raise ValueError('shared_agent_node_version_mismatch')
        return {'version': version, 'scope': 'Shared Node version compatible with pinned agent adapters'}
    check('node', node_runtime)
    def npm_versions():
        lock = json.loads((root / 'package-lock.json').read_text())['packages']
        found = {}
        for package in ('react', 'react-dom', 'remotion', 'esbuild'):
            expected = lock['node_modules/' + package]['version']
            installed = json.loads((root / 'node_modules' / package / 'package.json').read_text())['version']
            if installed != expected:
                raise ValueError('npm_version_mismatch')
            found[package] = installed
        return {'versions': found, 'scope': 'Required package versions match lock; installed dependency bytes are not reauthenticated'}
    check('npm_packages', npm_versions)
    def ffmpeg():
        version = read_probe(['ffmpeg', '-version']).splitlines()[0]
        probe_version = read_probe(['ffprobe', '-version']).splitlines()[0]
        filters = read_probe(['ffmpeg', '-hide_banner', '-filters'])
        encoders = read_probe(['ffmpeg', '-hide_banner', '-encoders'])
        needed = ('subtitles', 'amix', 'adelay', 'tpad', 'fps', 'volumedetect', 'ebur128', 'astats', 'silencedetect')
        if any(not re.search(r'\s' + name + r'\s', filters) for name in needed) or any(not re.search(r'\s' + name + r'\s', encoders) for name in ('libx264', 'aac')):
            raise ValueError('ffmpeg_capability_missing')
        return {'ffmpeg': version, 'ffprobe': probe_version, 'filters': list(needed), 'encoders': ['libx264', 'aac']}
    check('ffmpeg', ffmpeg)
    def font():
        found = read_probe(['fc-match', '--format=%{family}', 'DejaVu Sans']).strip()
        if 'DejaVu Sans' not in found:
            raise ValueError('caption_font_unavailable')
        return {'family': found}
    check('caption_font', font)
    def cached_asr():
        hub = Path(os.environ.get('HF_HUB_CACHE', str(Path(os.environ.get('HF_HOME', str(Path.home()/'.cache/huggingface'))) / 'hub')))
        model = hub / 'models--Systran--faster-whisper-base.en'
        revision = (model / 'refs/main').read_text().strip()
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ValueError('cached_model_revision_missing')
        snapshot = model / 'snapshots' / revision
        files = {}
        for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
            path = snapshot / name
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError('cached_model_incomplete')
            files[name] = {'size_bytes': path.stat().st_size, 'sha256': sha(path)}
        return {'model': 'Systran/faster-whisper-base.en', 'revision': revision, 'files': files,
                'scope': 'Cached file identity only; no model load or inference'}
    check('cached_asr', cached_asr)
    return {'status': 'BLOCKED' if blockers else 'PASS', 'checks': checks, 'details': details, 'blockers': blockers,
            'scope': 'Offline runtime prerequisites only; no inference or rendering verified'}


def diagnose(root, *, video_python, picture_python, expected_commit=None):
    report = {'schema_version': 1, 'observed_at': datetime.now(timezone.utc).isoformat(),
              'status': 'BLOCKED', 'publication_enabled': False, 'paid_generation_enabled': False,
              'production_ready': False, 'host_scope': 'Current execution host only',
              'scope': 'Read-only source identity and offline runtime prerequisites; no capacity admission, model inference, rendering, audiovisual approval or persistent worker verified'}
    try:
        report['source'] = describe_source(root, expected_commit)
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError) as error:
        report['blockers'] = ['source_preflight_failed']
        report['source_error'] = str(error) if isinstance(error, ValueError) else type(error).__name__
        return report
    report['runtime'] = inspect_runtime(root, video_python=video_python, picture_python=picture_python)
    report['blockers'] = report['runtime']['blockers']
    if not report['blockers']:
        report['status'] = 'PREREQUISITES_VERIFIED'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--content-control-root', required=True)
    parser.add_argument('--expected-commit')
    parser.add_argument('--describe-only', action='store_true')
    parser.add_argument('--video-python', default=sys.executable)
    parser.add_argument('--picture-python', default=sys.executable)
    args = parser.parse_args(argv)
    if args.describe_only:
        try:
            report = {'status': 'SOURCE_VERIFIED', **describe_source(args.content_control_root, args.expected_commit),
                      'publication_enabled': False, 'production_ready': False}
        except (OSError, ValueError, SyntaxError, subprocess.SubprocessError):
            report = {'status': 'BLOCKED', 'reason': 'source_preflight_failed', 'publication_enabled': False, 'production_ready': False}
    else:
        report = diagnose(args.content_control_root, video_python=args.video_python,
                          picture_python=args.picture_python, expected_commit=args.expected_commit)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
