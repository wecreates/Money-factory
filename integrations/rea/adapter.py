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


def _target(path, directory=False):
    path=Path(path)
    if path.is_symlink(): raise ValueError('Linked inputs are not supported')
    path=path.resolve(strict=True)
    if directory:
        if not path.is_dir() or any(p.is_symlink() for p in path.rglob('*')):
            raise ValueError('Unlinked input directory required')
    elif not path.is_file(): raise ValueError('Input file required')
    return path


def _cli(runtime, arguments):
    package=Path(runtime).resolve()/'node_modules/rea-agents'
    if json.loads((package/'package.json').read_text())['version']!=VERSION:
        raise ValueError('REA version does not match reviewed pin')
    with tempfile.TemporaryDirectory(prefix='cyzor-rea-') as home:
        env={'PATH':os.environ.get('PATH',''),'HOME':home,'PUBLICATION_ENABLED':'false','PAID_GENERATION_ENABLED':'false'}
        result=subprocess.run(['node',str(package/'scripts/rea.mjs'),*map(str,arguments),'--json'],env=env,capture_output=True,text=True,timeout=90)
    try: evidence=json.loads(result.stdout)
    except json.JSONDecodeError: evidence={'error':'Invalid upstream JSON','stderr':result.stderr[-2000:]}
    return result.returncode,evidence


def dispatch(job, runtime):
    """Fixed Money Factory operations; provider credentials never inherited."""
    operation=job['operation'];target=job.get('input')
    if job.get('publication_enabled') is not False or job.get('paid_generation_enabled') is not False:
        raise ValueError('Explicit free, publication-disabled job required')
    if operation=='analyze-javascript-application': return analyze(target,runtime)
    if operation=='mcp-smoke':
        if __package__:
            from .mcp_probe import probe
        else:
            from mcp_probe import probe
        return probe(runtime,_target(target,True))
    if operation=='inspect-local-web-page':
        target=_target(target,True)
        manifest={str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(target.rglob('*')) if p.is_file()}
        result=subprocess.run(['node',str(Path(__file__).with_name('browser_probe.mjs')),str(Path(runtime).resolve()),str(target)],capture_output=True,text=True,timeout=120,
            env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','PLAYWRIGHT_BROWSERS_PATH')})
        evidence=json.loads(result.stdout)
        after={str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(target.rglob('*')) if p.is_file()}
        if manifest!=after: raise ValueError('Target changed during inspection')
        return {'schema_version':1,'tool':'REA','version':VERSION,'operation':operation,'status':'PASS' if result.returncode==0 and evidence.get('status')=='PASS' else 'BLOCKED','input_sha256':manifest,'evidence':evidence,'publication_enabled':False,'paid_generation_enabled':False,'production_ready':False,'scope':'Dedicated local-page CDP observation only'}
    target=_target(target);before=hashlib.sha256(target.read_bytes()).hexdigest()
    if operation=='inspect-artifact':
        code,evidence=_cli(runtime,['inspect-artifact',target])
        normalized=evidence.get('normalized_result',{})
        valid=normalized.get('subject',{}).get('root_sha256')==before and bool(normalized.get('observations'))
    elif operation=='capture-owned-process':
        if target.suffix not in ('.js','.mjs','.cjs'): raise ValueError('Reviewed Node source file required')
        import shutil
        with tempfile.TemporaryDirectory(prefix='cyzor-rea-process-') as folder:
            scenario=Path(folder)/'scenario.json'
            scenario.write_text(json.dumps({'executable':shutil.which('node'),'arguments':[str(target)],'working_directory':folder,'timeout_ms':5000,'idle_timeout_ms':5000}))
            code,evidence=_cli(runtime,['capture-process',scenario])
        normalized=evidence.get('normalized_result',{})
        valid=normalized.get('exit',{}).get('code')==0 and bool(normalized.get('frames')) and normalized.get('truncated') is False
    else: raise ValueError('Unsupported REA operation')
    if before!=hashlib.sha256(target.read_bytes()).hexdigest(): raise ValueError('Target changed during inspection')
    return {'schema_version':1,'tool':'REA','version':VERSION,'operation':operation,'status':'PASS' if code==0 and valid and not evidence.get('error') else 'BLOCKED','exit_code':code,'input_sha256':{target.name:before},'evidence':evidence,'publication_enabled':False,'paid_generation_enabled':False,'production_ready':False,'scope':'Requested operation only; native inventory is not decompilation; process capture executes reviewed source in a temporary working directory, not an OS sandbox'}
