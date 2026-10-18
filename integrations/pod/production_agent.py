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
    result=json.loads((output/'result.json').read_text())
    if (result.get('status')!='REVIEW_REQUIRED' or result.get('publication_enabled') is not False or
        result.get('marketplace_ready') is not False):
        raise ValueError('RESULT_SCOPE_INVALID')
    manifest=json.loads((output/'package/manifest.json').read_text())
    expected=manifest.pop('package_sha256')
    encoded=json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    if hashlib.sha256(encoded).hexdigest()!=expected or result['package_sha256']!=expected:
        raise ValueError('MANIFEST_HASH_MISMATCH')
    for name,sha in manifest['files'].items():
        base=(output/'package').resolve()
        path=(base/name).resolve(strict=True)
        if not path.is_relative_to(base) or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError('ARTIFACT_HASH_MISMATCH')
    result['input_sha256']=hashlib.sha256(body).hexdigest()
    (output/'money-factory-receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('job','content-control','font','output'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.job,args.content_control,args.font,args.output)))
