#!/usr/bin/env python3
"""Run a reviewed, repository-owned job through Content Control on a CPU runner."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
from run import ROOT, run

DIRECT_TOOLS = ('rea', 'voicestudio')

OPERATIONS = {
    'voicestudio': ('synthesize',),
    'rea': ('analyze-javascript-application', 'inspect-artifact', 'mcp-smoke', 'capture-owned-process', 'inspect-local-web-page'),
    'youtube-clipper-skill': ('clip', 'captions'),
    'openshorts': ('vertical', 'transcript-windows'),
    'claude-seo': ('parse-html', 'render-page'),
    'toonflow-app': ('import-brief',),
    'ruflo': ('remember-project',),
    'youtube-automation-agent': ('audit',),
}


def inside(root, value, allow_directory=False):
    if not isinstance(value, str) or Path(value).is_absolute():
        raise ValueError('Repository-relative input path required')
    path = (root / value).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not (path.is_file() or (allow_directory and path.is_dir())):
        raise ValueError('Input must remain inside its reviewed repository directory')
    return path


def load_job(job_path, output, root=ROOT):
    job_file = inside(root / 'integrations/jobs', job_path)
    if not job_file.name.endswith('.job.json'):
        raise ValueError('Select a reviewed .job.json file')
    job = json.loads(job_file.read_text())
    if not isinstance(job, dict):
        raise ValueError('Job must be an object')
    if job.get('publication_enabled') is not False or job.get('paid_generation_enabled') is not False:
        raise ValueError('Job must explicitly disable publication and paid generation')
    if job.get('operation') not in OPERATIONS.get(job.get('tool'), ()):
        raise ValueError('Unsupported hosted CPU operation')
    allowed = {'tool','operation','input','subtitles','start','end','publication_enabled','paid_generation_enabled','provenance'}
    if set(job) - allowed:
        raise ValueError('Unknown job fields; output paths and service URLs are worker-owned')
    job.pop('provenance', None)
    if job['tool'] in DIRECT_TOOLS:
        if 'input' not in job:
            raise ValueError('Direct operations require input')
        if 'subtitles' in job:
            raise ValueError('Direct operations do not accept subtitles')
    for key in ('input','subtitles'):
        if key in job:
            job[key] = str(inside(root / 'integrations/jobs', job[key], allow_directory=job['tool']=='rea' and job['operation'] in ('analyze-javascript-application', 'mcp-smoke', 'inspect-local-web-page') and key=='input'))
    suffix = '.wav' if job['tool']=='voicestudio' else '.mp4' if job['operation'] in ('clip','captions','vertical') else '.txt' if job['operation']=='remember-project' else '.json'
    job['output'] = str(output.resolve() / ('result'+suffix))
    return job


def execute(job, runtime, content_control, output):
    output.mkdir(parents=True, exist_ok=False)
    server = None
    log = None
    try:
        if job['tool'] == 'toonflow-app':
            data = output / 'toonflow-data'
            log = (output / 'toonflow.log').open('w')
            server = subprocess.Popen([str(runtime / 'bun/node_modules/.bin/bun'), str(ROOT / 'integrations/toonflow-server.ts')],
                cwd=ROOT, env=dict(os.environ, TOONFLOW_DATA_DIR=str(data), PUBLICATION_ENABLED='false'), stdout=log, stderr=log)
            for _ in range(80):
                try:
                    with urlopen('http://127.0.0.1:3000/api/workspaces/list',timeout=1) as response:
                        workspace = Path(json.load(response)['data']['absolutePath']).resolve()
                    if not workspace.is_relative_to(data.resolve()):
                        raise ValueError('Toonflow workspace escaped worker storage')
                    job['workspace_directory'] = str(workspace)
                    break
                except OSError:
                    if server.poll() is not None:
                        raise RuntimeError('Toonflow failed to start')
                    time.sleep(.25)
            else:
                raise RuntimeError('Toonflow startup timeout')
        private_job = output / 'resolved-job.json'
        private_job.write_text(json.dumps(job))
        if job['tool'] in DIRECT_TOOLS:
            result = run(job, runtime)
            if result.get('status') != 'PASS':
                raise RuntimeError('Direct operation blocked; inspect its result for diagnostics')
        else:
            subprocess.run([sys.executable, str(content_control / 'scripts/repository_tools.py'), str(private_job), '--runtime', str(runtime)],
                env=dict(os.environ, MONEY_FACTORY_ROOT=str(ROOT), PUBLICATION_ENABLED='false'), check=True, timeout=1900)
        private_job.unlink()
        result = Path(job['output'])
        receipt = json.loads(Path(str(result)+'.receipt.json').read_text())
        if receipt['status']!='PASS' or receipt['publication_enabled'] is not False:
            raise ValueError('Invalid operation receipt')
        if hashlib.sha256(result.read_bytes()).hexdigest()!=receipt['output_sha256']:
            raise ValueError('Output does not match its receipt')
        print('Completed reviewed job; publication remains disabled.')
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=10)
        if log is not None:
            log.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', help='File relative to integrations/jobs')
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--content-control', type=Path, help='Required for bridge jobs; REA and VoiceStudio run directly')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--print-tool', action='store_true')
    args=parser.parse_args()
    job=load_job(args.job,args.output)
    if args.print_tool:
        print(job['tool'])
    else:
        if job['tool'] not in DIRECT_TOOLS and args.content_control is None:
            parser.error('--content-control is required for this tool')
        execute(job,args.runtime.resolve(),args.content_control.resolve() if args.content_control else None,args.output.resolve())
        original=inside(ROOT / 'integrations/jobs',args.job)
        evidence={'schema_version':1,'job':args.job,
            'job_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
            'repository_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'execution_engine':'money-factory' if job['tool'] in DIRECT_TOOLS else 'content-control',
            'content_control_revision':None if job['tool'] in DIRECT_TOOLS else subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.content_control,text=True).strip(),
            'output':Path(job['output']).name,'publication_enabled':False,'paid_generation_enabled':False}
        (args.output / 'job-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
