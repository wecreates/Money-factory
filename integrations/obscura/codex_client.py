"""Launch local Codex with the verified project browser connection.

Uses Codex's documented per-invocation configuration, preserving managed global
configuration and all existing sandbox/approval settings. Does not register tools
into an already running ChatGPT session. Use `-- mcp get cyzor-obscura --json`
for a read-only connection configuration check without starting model inference.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from integrations.obscura.runtime import verify_runtime


def command(runtime, client_args):
    runtime = Path(runtime).absolute()
    verify_runtime(runtime)
    codex = shutil.which('codex')
    if not codex:
        raise RuntimeError('Codex CLI is not installed on this host')
    launcher = Path(__file__).with_name('mcp_launcher.py').resolve()
    settings = {
        'mcp_servers.cyzor-obscura.command': sys.executable,
        'mcp_servers.cyzor-obscura.args': [str(launcher), '--runtime', str(runtime)],
        'mcp_servers.cyzor-obscura.enabled': True,
    }
    argv = [codex]
    for key, value in settings.items():
        argv.extend(['-c', key+'='+json.dumps(value)])
    return argv + list(client_args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('client_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    remaining = args.client_args[1:] if args.client_args[:1]==['--'] else args.client_args
    argv = command(args.runtime, remaining)
    os.execv(argv[0], argv)


if __name__ == '__main__':
    main()
