"""Verify pinned repository sources without executing upstream code."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify():
    registry = json.loads((ROOT / 'integrations/repositories.json').read_text())
    entries = registry['repositories']
    if [entry['order'] for entry in entries] != list(range(1, 8)):
        raise ValueError('Expected seven repositories in requested order')
    for entry in entries:
        path = ROOT / entry['path']
        if not (path / '.git').is_file():
            raise ValueError(f"Submodule not initialized: {entry['id']}")
        revision = subprocess.check_output(
            ['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
        origin = subprocess.check_output(
            ['git', '-C', str(path), 'remote', 'get-url', 'origin'], text=True).strip()
        if revision != entry['revision']:
            raise ValueError(f"Revision mismatch: {entry['id']}")
        if origin.removesuffix('.git') != entry['repository']:
            raise ValueError(f"Origin mismatch: {entry['id']}")
        if '?' in origin or '#' in origin:
            raise ValueError('Repository URLs must not contain query parameters')
        print(f"PASS {entry['order']}: {entry['id']} source pin; runtime={entry['runtime_status']}")


if __name__ == '__main__':
    verify()
