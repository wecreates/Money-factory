#!/usr/bin/env python3
"""Persist small public job results after verifying the reviewed source and receipt."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
LIMIT=1024*1024


def blob(root, revision, path):
    return subprocess.check_output(['git','show',f'{revision}:{path}'],cwd=root)


def read_file(folder,name):
    path=folder/name
    if path.is_symlink() or not path.is_file() or path.stat().st_size>LIMIT:
        raise ValueError('Missing, oversized or linked evidence')
    return path.read_bytes()


def persist(folder, run_id, attempt, revision, root=ROOT):
    if not re.fullmatch(r'[1-9][0-9]*',run_id) or not re.fullmatch(r'[1-9][0-9]*',attempt):
        raise ValueError('Numeric workflow identity required')
    if not re.fullmatch(r'[a-f0-9]{40}',revision):
        raise ValueError('Full source revision required')
    evidence_bytes=read_file(folder,'job-evidence.json')
    evidence=json.loads(evidence_bytes)
    if evidence.get('schema_version')!=1 or evidence.get('repository_revision')!=revision or evidence.get('publication_enabled') is not False or evidence.get('paid_generation_enabled') is not False:
        raise ValueError('Unverified job evidence')
    name=evidence.get('job','')
    path=PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or not name.endswith('.job.json'):
        raise ValueError('Invalid reviewed job path')
    job_bytes=blob(root,revision,'integrations/jobs/'+name)
    if hashlib.sha256(job_bytes).hexdigest()!=evidence.get('job_sha256'):
        raise ValueError('Reviewed job hash mismatch')
    job=json.loads(job_bytes)
    if job.get('publication_enabled') is not False or job.get('paid_generation_enabled') is not False:
        raise ValueError('Reviewed job authorization mismatch')
    output=evidence.get('output')
    expected='result.mp4' if job.get('operation') in ('clip','captions','vertical') else 'result.txt' if job.get('operation')=='remember-project' else 'result.json'
    if output!=expected:
        raise ValueError('Unexpected result filename')
    receipt_bytes=read_file(folder,output+'.receipt.json')
    receipt=json.loads(receipt_bytes)
    registry=json.loads(blob(root,revision,'integrations/repositories.json'))
    sources={entry['id']:entry['revision'] for entry in registry['repositories'] + registry.get('engineering_tools', [])}
    if receipt.get('status')!='PASS' or receipt.get('publication_enabled') is not False or receipt.get('tool')!=job.get('tool') or receipt.get('operation')!=job.get('operation') or receipt.get('revision')!=sources.get(job.get('tool')) or not re.fullmatch(r'[a-f0-9]{64}',receipt.get('output_sha256','')):
        raise ValueError('Operation receipt mismatch')
    if job.get('tool') == 'rea':
        if evidence.get('execution_engine') != 'money-factory' or evidence.get('content_control_revision') is not None:
            raise ValueError('REA requires Money Factory execution evidence')
    elif not re.fullmatch(r'[a-f0-9]{40}',evidence.get('content_control_revision','')):
        raise ValueError('Content Control source identity required')
    files={'job-evidence.json':evidence_bytes,output+'.receipt.json':receipt_bytes}
    if output!='result.mp4':
        data=read_file(folder,output)
        data.decode('utf-8')
        if hashlib.sha256(data).hexdigest()!=receipt['output_sha256']:
            raise ValueError('Result hash mismatch')
        if output.endswith('.json'):
            json.loads(data)
        files[output]=data
    # Media stays in its explicit retention-bound artifact, never silently in Git.
    record={'schema_version':1,'workflow_run_id':run_id,'workflow_run_attempt':attempt,
            'source_revision':revision,'job':name,'tool':receipt['tool'],'operation':receipt['operation'],
            'operation_status':'PASS','result_persisted':output!='result.mp4',
            'output_sha256':receipt['output_sha256'],
            'workflow_url':f'https://github.com/wecreates/Money-factory/actions/runs/{run_id}',
            'publication_enabled':False,'production_ready':False,
            'scope':'Operation execution evidence; findings and content approval are separate'}
    files['record.json']=(json.dumps(record,indent=2)+'\n').encode()
    destination=root/'integrations/results/runs'/f'{run_id}-{attempt}'
    # Verify the entire write set before changing anything, including replay cases.
    for filename,data in files.items():
        target=destination/filename
        if target.exists() and target.read_bytes()!=data:
            raise ValueError('Existing immutable run record differs')
    destination.mkdir(parents=True,exist_ok=True)
    for filename,data in files.items():
        (destination/filename).write_bytes(data)
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir',type=Path,required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--attempt',required=True)
    parser.add_argument('--revision',required=True)
    args=parser.parse_args()
    print(persist(args.artifact_dir,args.run_id,args.attempt,args.revision))
