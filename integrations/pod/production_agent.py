"""Run a reviewed repository job through Content Control's local Node/Python lane."""
import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
import subprocess


MAX_JOB_BYTES = 4 * 1024 * 1024  # Matches Content Control's local JSON ceiling.
MAX_OUTPUT_JSON_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024


def output_chunks(path, limit):
    # Descriptor checks also cover replacement between path validation and open.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('OUTPUT_FILE_INVALID')
        if info.st_size > limit:
            raise ValueError('OUTPUT_TOO_LARGE')
        source = os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise
    with source:
        total = 0
        while True:
            chunk = source.read(min(1024 * 1024, limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError('OUTPUT_TOO_LARGE')
            yield chunk


def output_json(path):
    body = b''.join(output_chunks(path, MAX_OUTPUT_JSON_BYTES))
    return json.loads(body.decode('utf-8', errors='strict'))

def capture_job(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('JOB_FILE_INVALID')
        source = os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise
    with source:
        body = source.read(MAX_JOB_BYTES + 1)
    if len(body) > MAX_JOB_BYTES:
        raise ValueError('JOB_TOO_LARGE')
    return body

def run(job, content_control, font, output):
    job=Path(job).resolve(strict=True)
    root=Path(content_control).resolve(strict=True)
    body=capture_job(job)
    spec=json.loads(body.decode('utf-8', errors='strict'))
    if not isinstance(spec, dict):
        raise ValueError('JOB_INVALID')
    if spec.get('publication_enabled') is not False or spec.get('paid_generation_enabled') is not False:
        raise ValueError('REVIEW_ONLY_REQUIRED')
    output=Path(output).resolve()
    if output.exists():
        raise ValueError('OUTPUT_EXISTS')
    # Validate, execute and receipt one byte version. The caller's path may be
    # replaced or removed while the child runs; never reopen it for provenance.
    with tempfile.TemporaryDirectory(prefix='pod-mf-job-') as tmp:
        snapshot=Path(tmp)/'job.json'
        with snapshot.open('xb') as target:
            target.write(body)
        snapshot.chmod(0o400)
        subprocess.run(['node',str(root/'scripts/pod_review_cli.mjs'),str(snapshot),
                        str(Path(font).resolve(strict=True)),str(output)],check=True,timeout=260)
    result=output_json(output/'result.json')
    if (result.get('status')!='REVIEW_REQUIRED' or result.get('publication_enabled') is not False or
        result.get('marketplace_ready') is not False):
        raise ValueError('RESULT_SCOPE_INVALID')
    manifest=output_json(output/'package/manifest.json')
    expected=manifest.pop('package_sha256')
    encoded=json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    if hashlib.sha256(encoded).hexdigest()!=expected or result['package_sha256']!=expected:
        raise ValueError('MANIFEST_HASH_MISMATCH')
    files=manifest['files']
    if not isinstance(files, dict) or len(files)>32:
        raise ValueError('ARTIFACT_BATCH_INVALID')
    total=0
    for name,sha in files.items():
        base=(output/'package').resolve()
        path=(base/name).resolve(strict=True)
        if not path.is_relative_to(base):
            raise ValueError('ARTIFACT_HASH_MISMATCH')
        digest=hashlib.sha256()
        for chunk in output_chunks(path, MAX_ARTIFACT_BYTES):
            total+=len(chunk)
            if total>MAX_PACKAGE_BYTES:
                raise ValueError('PACKAGE_TOO_LARGE')
            digest.update(chunk)
        if digest.hexdigest()!=sha:
            raise ValueError('ARTIFACT_HASH_MISMATCH')
    result['input_sha256']=hashlib.sha256(body).hexdigest()
    with (output/'money-factory-receipt.json').open('x', encoding='utf-8') as receipt:
        receipt.write(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('job','content-control','font','output'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.job,args.content_control,args.font,args.output)))
