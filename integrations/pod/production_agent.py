"""Run a reviewed repository job through Content Control's local Node/Python lane."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def run(job, content_control, font, output):
    job=Path(job).resolve(strict=True)
    root=Path(content_control).resolve(strict=True)
    spec=json.loads(job.read_text())
    if spec.get('publication_enabled') is not False or spec.get('paid_generation_enabled') is not False:
        raise ValueError('REVIEW_ONLY_REQUIRED')
    output=Path(output).resolve()
    if output.exists():
        raise ValueError('OUTPUT_EXISTS')
    subprocess.run(['node',str(root/'scripts/pod_review_cli.mjs'),str(job),
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
    result['input_sha256']=hashlib.sha256(job.read_bytes()).hexdigest()
    (output/'money-factory-receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('job','content-control','font','output'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.job,args.content_control,args.font,args.output)))
