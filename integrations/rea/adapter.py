"""Offline REA static analysis; never execute a target or enable providers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

VERSION = '6.4.0'


def analyze(target, runtime):
    target = Path(target)
    if target.is_symlink():
        raise ValueError('Linked inputs are not supported')
    target = target.resolve(strict=True)
    if not target.is_dir():
        raise ValueError('An authorized local JavaScript directory is required')
    # Refuse links: the authorized target must not redirect analysis elsewhere.
    if any(p.is_symlink() for p in target.rglob('*')):
        raise ValueError('Linked inputs are not supported')
    package = Path(runtime).resolve() / 'node_modules/rea-agents'
    if json.loads((package/'package.json').read_text())['version'] != VERSION:
        raise ValueError('REA version does not match reviewed pin')
    manifest = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(target.rglob('*')) if p.is_file()}
    if not manifest:
        raise ValueError('Target is empty')
    # An isolated home avoids inherited REA provider configuration. No API keys.
    with tempfile.TemporaryDirectory(prefix='cyzor-rea-') as home:
        env = {'PATH': os.environ.get('PATH', ''), 'HOME': home,
               'PUBLICATION_ENABLED': 'false', 'PAID_GENERATION_ENABLED': 'false'}
        run = subprocess.run(['node', str(package/'scripts/rea.mjs'),
            'analyze-javascript-application', str(target), '--json',
            '--analysis-timeout-ms', '30000', '--max-heap-mb', '256'],
            env=env, capture_output=True, text=True, timeout=90)
    evidence = json.loads(run.stdout)
    after = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(target.rglob('*')) if p.is_file()}
    if after != manifest:
        raise ValueError('Target changed during inspection')
    success = run.returncode == 0 and not evidence.get('error')
    return {'schema_version': 1, 'tool': 'REA', 'version': VERSION,
        'operation': 'analyze-javascript-application',
        'status': 'PASS' if success else 'BLOCKED', 'exit_code': run.returncode,
        'input_sha256': manifest, 'evidence': evidence,
        'publication_enabled': False, 'paid_generation_enabled': False,
        'production_ready': False,
        'scope': 'Offline source analysis only; partial observations never imply completion'}


def save_evidence(output, result):
    # Exclusive creation rejects files and dangling links without a check/write race.
    with Path(output).open('x') as handle:
        handle.write(json.dumps(result,indent=2)+'\n')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args=parser.parse_args()
    result=analyze(args.target,args.runtime)
    save_evidence(args.output,result)
    raise SystemExit(0 if result['status']=='PASS' else 2)
