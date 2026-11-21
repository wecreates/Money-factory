"""Verified Obscura stdio connection for a trusted local agent client.

No listener, imported login session, stealth, search provider or autonomous job.
Browser actions remain subject to the calling agent's user authorization;
environment flags are policy declarations, not a browser publication sandbox.
"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from integrations.obscura.runtime import verify_runtime


def launch(runtime):
    binary = verify_runtime(Path(runtime))
    keep = ('PATH', 'LANG', 'TMPDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
            'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY')
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env.update(PUBLICATION_ENABLED='false', PAID_GENERATION_ENABLED='false')
    os.execve(str(binary), [str(binary), 'mcp'], env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    launch(args.runtime)


if __name__ == '__main__':
    main()
