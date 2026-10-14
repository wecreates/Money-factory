#!/usr/bin/env python3
"""Money Factory's isolated REA stdio entrypoint for trusted local MCP clients."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    package = args.runtime.resolve() / 'node_modules/rea-agents'
    if json.loads((package / 'package.json').read_text())['version'] != '6.4.0':
        raise ValueError('Unreviewed REA version')
    with tempfile.TemporaryDirectory(prefix='money-factory-rea-mcp-') as home:
        env = {'PATH': os.environ.get('PATH', ''), 'HOME': home,
               'PUBLICATION_ENABLED': 'false', 'PAID_GENERATION_ENABLED': 'false'}
        child = subprocess.Popen(['node', str(package / 'scripts/rea.mjs'), 'mcp'], env=env)
        prior = {}

        def stop(signum, frame):
            # Forward only to our direct child, then let finally await cleanup.
            if child.poll() is None:
                child.send_signal(signum)
            raise SystemExit(128 + signum)

        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                prior[signum] = signal.signal(signum, stop)
            return child.wait()
        finally:
            for signum, handler in prior.items():
                signal.signal(signum, handler)
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)


if __name__ == '__main__':
    raise SystemExit(main())
