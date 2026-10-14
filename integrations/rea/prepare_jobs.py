#!/usr/bin/env python3
"""Prepare fixed, repository-owned REA inputs for either hosted entry point.

No user command or arbitrary source path is executed. Native compilation uses
only the reviewed native.c; project analysis copies the two named source files.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PROJECT_FILES = ('readiness-grant.mjs', 'sign-grant.mjs')


def safe_path(root, relative):
    path = root / relative
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError('Preparation paths must not contain symlinks')
        current = current.parent
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Preparation path escaped repository')
    return path


def prepare(job=None, root=ROOT):
    root = root.resolve(strict=True)
    if job is not None and job not in ('rea-native.job.json', 'rea-project.job.json'):
        return []  # Other reviewed jobs need no generated input.
    generated = []
    if job in (None, 'rea-native.job.json'):
        source = safe_path(root, 'integrations/jobs/rea-fixtures/native.c')
        target = safe_path(root, 'integrations/jobs/rea-fixtures/native.bin')
        if not source.is_file():
            raise ValueError('Missing reviewed native fixture')
        # Stable flags avoid build-id and workspace-path variance. Compile to an
        # isolated temporary path, then atomically replace only this fixed output.
        with tempfile.TemporaryDirectory(dir=target.parent) as directory:
            compiled = Path(directory) / 'native.bin'
            subprocess.run(['gcc', '-O0', '-Wl,--build-id=none', source.name, '-o', str(compiled)],
                           cwd=source.parent, check=True, timeout=60)
            if not compiled.is_file() or compiled.stat().st_size == 0:
                raise ValueError('Native compiler did not create a binary')
            compiled.replace(target)
        generated.append(target)
    if job in (None, 'rea-project.job.json'):
        destination = safe_path(root, 'integrations/jobs/rea-project')
        sources = [safe_path(root, 'integrations/pod/' + name) for name in PROJECT_FILES]
        contents = {source.name: source.read_bytes() for source in sources}
        if destination.exists() and (not destination.is_dir() or
                any(path.name not in PROJECT_FILES for path in destination.iterdir())):
            raise ValueError('Generated project directory contains unexpected files')
        for name in PROJECT_FILES:
            safe_path(root, 'integrations/jobs/rea-project/' + name)
        destination.mkdir(parents=True, exist_ok=True)
        for name, content in contents.items():
            target = destination / name
            target.write_bytes(content)
            generated.append(target)
    return generated


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', help='Reviewed job filename; omitted prepares both generated inputs')
    args = parser.parse_args()
    for path in prepare(args.job):
        print(path.relative_to(ROOT))
