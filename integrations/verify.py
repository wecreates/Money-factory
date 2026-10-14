"""Verify pinned repository sources without executing upstream code."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUESTED_IDS = ('wan21', 'youtube-clipper-skill', 'openshorts', 'claude-seo',
                 'toonflow-app', 'ruflo', 'youtube-automation-agent')


def verify(root=ROOT):
    registry = json.loads((root / 'integrations/repositories.json').read_text())
    entries = registry['repositories']
    if ([entry['order'] for entry in entries] != list(range(1, 8)) or
            tuple(entry['id'] for entry in entries) != REQUESTED_IDS):
        raise ValueError('Expected seven repositories in requested order')
    from run import source
    for entry in registry.get('engineering_tools', []):
        if entry.get('source_type') != 'npm':
            raise ValueError('Unsupported engineering source type')
        source(entry['id'])
        print(f"PASS engineering: {entry['id']} npm pin; runtime={entry['runtime_status']}")
    for entry in entries + registry.get('media_tools', []):
        path = root / entry['path']
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
        dirty = subprocess.check_output(
            ['git', '-C', str(path), 'status', '--porcelain', '--untracked-files=no'], text=True)
        if dirty:
            raise ValueError(f"Tracked source modifications: {entry['id']}")
        print(f"PASS {entry.get('order', 'media')}: {entry['id']} source pin; runtime={entry['runtime_status']}")


if __name__ == '__main__':
    verify()
