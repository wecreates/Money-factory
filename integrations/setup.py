#!/usr/bin/env python3
"""Install one isolated integration. Does not configure paid providers or publish."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from run import ROOT, TOOLS, source


def setup(tool, runtime, browser=False):
    upstream = source(tool)
    runtime.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PUBLICATION_ENABLED='false', PIP_NO_CACHE_DIR='1',
               CLAUDE_SEO_DATA_DIR=str(runtime / 'seo'))

    def cmd(args, cwd=upstream):
        subprocess.run([str(x) for x in args], cwd=cwd, env=env, check=True)

    def venv(name):
        path = runtime / name
        if not (path / 'bin/python').exists():
            cmd([sys.executable, '-m', 'venv', path])
        return path / 'bin/python'

    def pip(python, *args):
        cmd([python, '-m', 'pip', 'install', '--disable-pip-version-check', *args])

    if tool == 'rea':
        destination = runtime / 'rea'
        destination.mkdir(parents=True, exist_ok=True)
        for name in ('package.json', 'package-lock.json'):
            shutil.copy2(upstream / name, destination / name)
        cmd(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=destination)
        cmd(['node', destination / 'node_modules/playwright/cli.js', 'install', 'chromium'], cwd=destination)
    elif tool == 'wan21':
        if not shutil.which('nvidia-smi'):
            raise RuntimeError('Wan2.1 requires a provisioned CUDA worker; none detected')
        if shutil.disk_usage(runtime).free < 20 * 1024**3:
            raise RuntimeError('Reserve at least 20 GiB free before Wan dependencies and weights')
        python = venv('wan21')
        pip(python, '-r', upstream / 'requirements.txt')
        print('Dependencies installed; model weights and a verified generation are still required.')
    elif tool == 'youtube-clipper-skill':
        python = venv('clipper')
        pip(python, 'yt-dlp==2026.8.19', 'pysrt==1.1.2', 'python-dotenv==1.2.4')
        cmd(['ffmpeg', '-version'])
    elif tool == 'openshorts':
        python = venv('openshorts')
        # Install CPU wheels first so pip does not pull multi-gigabyte CUDA libraries.
        pip(python, '--index-url', 'https://download.pytorch.org/whl/cpu',
            'torch==2.11.0', 'torchvision==0.26.0')
        pip(python, '-r', upstream / 'requirements.txt')
    elif tool == 'claude-seo':
        cmd(['bash', upstream / 'scripts/claude-seo', 'setup', *([] if browser else ['--skip-browser'])])
        cmd(['bash', upstream / 'scripts/claude-seo', 'doctor', '--json'])
    elif tool == 'toonflow-app':
        cmd(['npm', 'install', '--prefix', runtime / 'bun', 'bun@1.3.14', '--no-audit', '--no-fund'])
        bun = runtime / 'bun/node_modules/.bin/bun'
        env['PATH'] = str(bun.parent) + os.pathsep + env['PATH']
        env['NODE_ENV'] = 'production'
        # Bun links the workspace's CLI and chmods its tracked bin source.
        # Restore only its original permission bits; content changes still fail.
        cli_source = upstream / 'packages/mcp/src/stdio.ts'
        cli_mode = cli_source.stat().st_mode & 0o777
        try:
            cmd([bun, 'install', '--frozen-lockfile', '--ignore-scripts'])
        finally:
            cli_source.chmod(cli_mode)
        # Direct package builds avoid Bun's workspace-filter ENOENT on this host.
        for category in ('tools', 'ext'):
            for script in sorted((upstream / 'packages' / category).glob('*/build.ts')):
                cmd([bun, script], cwd=script.parent)
        cmd([bun, 'scripts/build.ts'], cwd=upstream / 'packages/mcp')
        cmd([bun, 'scripts/build.ts'], cwd=upstream / 'apps/server')
        # Vite's component resolver regenerates this tracked type declaration.
        # Preserve the reviewed source while retaining the compiled web assets.
        generated_types = upstream / 'apps/web/src/types/components.d.ts'
        original_types = generated_types.read_bytes()
        try:
            cmd([bun, 'node_modules/vite/bin/vite.js', 'build'], cwd=upstream / 'apps/web')
        finally:
            generated_types.write_bytes(original_types)
        source(tool)  # Any other tracked change remains a hard failure.
    elif tool == 'ruflo':
        cmd(['npm', 'install', '--prefix', runtime / 'ruflo', 'ruflo@3.56.7',
             '--ignore-scripts', '--no-audit', '--no-fund'])
        cmd(['npm', 'rebuild', 'better-sqlite3'], cwd=runtime / 'ruflo')
    elif tool == 'youtube-automation-agent':
        cmd(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'])
        cmd(['npm', 'rebuild', 'sqlite3', 'sharp'])
        env['FFMPEG_PATH'] = shutil.which('ffmpeg') or 'ffmpeg'
        env['FFPROBE_PATH'] = shutil.which('ffprobe') or 'ffprobe'
        cmd(['npm', 'test'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool', choices=list(TOOLS))
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--browser', action='store_true', help='Install managed Chromium for Claude SEO')
    args = parser.parse_args()
    setup(args.tool, args.runtime.resolve(), browser=args.browser)
