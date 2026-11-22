"""Portable unpublished delivery shared by standalone and durable queue callers."""
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import time
import zipfile

SHA = re.compile(r'^[0-9a-f]{64}$')
LIMIT = 256 * 1024 * 1024
RESERVED={'index.html','delivery-manifest.json','timeline.otio','export-receipt.json','diagnostics'}


def check_deadline(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError('Delivery deadline exhausted')


def copy_chunks(source, target, deadline):
    while True:
        check_deadline(deadline)
        chunk=source.read(1024*1024)
        if not chunk: break
        target.write(chunk)
    check_deadline(deadline)


def copy_file(source,target,deadline):
    with source.open('rb') as incoming,target.open('xb') as outgoing:
        copy_chunks(incoming,outgoing,deadline)


def digest(path,deadline=None):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while True:
            check_deadline(deadline)
            chunk=stream.read(1024*1024)
            if not chunk:break
            value.update(chunk)
    return value.hexdigest()


def require(value,message):
    if not value: raise ValueError(message)


def no_symlinks(path):
    require(not any(p.is_symlink() for p in (path,*path.parents)), 'Symlink ancestors forbidden')


def regular_files(directory):
    no_symlinks(directory)
    require(directory.is_dir() and not directory.is_symlink(),'Regular directory required')
    files=sorted(directory.iterdir())
    require(all(p.is_file() and not p.is_symlink() for p in files),'Only regular packet files allowed')
    require(sum(p.stat().st_size for p in files)<=LIMIT,'Packet size limit exceeded')
    return files


def inspect_packet(directory,run_sha,candidate,deadline=None):
    files=regular_files(directory)
    require(not RESERVED.intersection(p.name for p in files),'Reserved delivery filename in input')
    require(SHA.fullmatch(run_sha or '') and SHA.fullmatch(candidate or ''),'Exact run and candidate hashes required')
    require(digest(directory/'run.json',deadline)==run_sha,'Run hash mismatch')
    run=json.loads((directory/'run.json').read_text())
    require(run.get('status')=='AWAITING_REVIEW' and run.get('technical_status')=='PASS','Completed review packet required')
    require(all(run.get(k) is False for k in ('publication_enabled','production_approved','full_av_review')),'Approval flags must remain false')
    require(run.get('candidate_sha256')==candidate and digest(directory/'video.mp4',deadline)==candidate,'Candidate hash mismatch')
    require(run.get('caption_sha256')==digest(directory/'captions.vtt',deadline),'Caption hash mismatch')
    artifacts=run.get('artifacts_sha256')
    require(isinstance(artifacts,dict) and {'video.mp4','captions.vtt','video.mp4.json'}<=artifacts.keys(),'Required artifacts missing')
    for name,expected in artifacts.items():
        require(isinstance(name,str) and Path(name).name==name and name not in ('.','..'),'Invalid artifact path')
        require(SHA.fullmatch(expected or '') and digest(directory/name,deadline)==expected,'Artifact hash mismatch: '+name)
    require({p.name for p in files}==set(artifacts)|{'run.json'},'Unrecorded files in review packet')
    return run,files


def package_review(review_dir,output_dir,*,expected_run_sha256,expected_candidate_sha256,
                   provenance,edit_dir=None,diagnostics_dir=None,deadline=None):
    """No rendering or process launches. Caller owns production/admission policy.

    Exact trusted run/candidate pins are required; provenance is descriptive, never
    an approval capability. Output directory must not exist. Failed delivery is
    removed while original production files are retained unchanged.
    """
    review=Path(review_dir)
    output=Path(output_dir)
    require(not output.exists() and not output.is_symlink(),'Delivery output already exists')
    no_symlinks(output)
    output=output.resolve(strict=False)
    for source in (review, *([Path(edit_dir)] if edit_dir is not None else []), *([Path(diagnostics_dir)] if diagnostics_dir is not None else [])):
        require(not output.is_relative_to(source.resolve(strict=False)),'Output must be outside input directories')
    run,files=inspect_packet(review,expected_run_sha256,expected_candidate_sha256,deadline)
    # Reject non-JSON data before creating an output.
    json.dumps(provenance,allow_nan=False)
    output.mkdir()
    try:
        target=output/'review'; target.mkdir()
        for path in files: copy_file(path,target/path.name,deadline)
        inspect_packet(target,expected_run_sha256,expected_candidate_sha256,deadline)
        optional=[]
        if edit_dir is not None:
            edit=Path(edit_dir)
            regular_files(edit)
            receipt=json.loads((edit/'export-receipt.json').read_text())
            require(receipt.get('status')=='INTERCHANGE_VERIFIED' and receipt.get('roundtrip_verified') is True,'OTIO export incomplete')
            require(receipt.get('input_run_sha256')==expected_run_sha256 and receipt.get('candidate_sha256')==expected_candidate_sha256,'OTIO source mismatch')
            require(receipt.get('publication_enabled') is False and receipt.get('production_approved') is False,'OTIO approval mismatch')
            for name,expected in receipt.get('files_sha256',{}).items():
                require(Path(name).name==name and digest(edit/name,deadline)==expected,'OTIO artifact mismatch')
            require(receipt.get('files_sha256',{}).get('video.mp4')==expected_candidate_sha256,'OTIO media mismatch')
            require(receipt['files_sha256'].get('run.json')==expected_run_sha256 and 'timeline.otio' in receipt['files_sha256'],'OTIO provenance missing')
            for name in ('timeline.otio','export-receipt.json'): copy_file(edit/name,target/name,deadline)
            # Recheck the copied timeline independently of the source directory.
            require(digest(target/'timeline.otio',deadline)==receipt['files_sha256']['timeline.otio'],'Copied OTIO mismatch')
            optional.append('timeline.otio')
        if diagnostics_dir is not None:
            diagnostic=Path(diagnostics_dir)
            diagnostic_files=regular_files(diagnostic)
            sub=target/'diagnostics'; sub.mkdir()
            for path in diagnostic_files: copy_file(path,sub/path.name,deadline)
            optional.append('diagnostics/')
        candidate=html.escape(expected_candidate_sha256)
        page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CYZOR video review</title><style>body{font:17px system-ui;max-width:750px;margin:24px auto;padding:0 16px;background:#101722;color:#f0f4fa}video{display:block;max-width:100%;max-height:75vh;margin:auto}a{color:#9fd3ff}code{overflow-wrap:anywhere}</style><h1>Unpublished video review</h1><video controls playsinline preload="metadata" src="video.mp4"></video><p>Watch and listen to the complete video. Technical checks do not establish creative approval. Publishing remains disabled.</p><p><a href="video.mp4">Open or download video</a> · <a href="captions.vtt">Caption text and timing</a> · <a href="REVIEW.md">Review notes</a></p><p>Captions are already burned into the picture. Local caption-track support varies by browser; the video does not require a separate track.</p>'''
        if not (target/'REVIEW.md').exists():
            page=page.replace(' · <a href="REVIEW.md">Review notes</a>','')
        if edit_dir is not None:
            page+='<p><a href="timeline.otio">Editable cut timeline</a>: trimmed rendered MP4; no recovered artwork or separate stems. Use its Audio track once. NLE import remains unverified.</p>'
        page+='<p>Candidate SHA-256: <code>'+candidate+'</code></p></html>\n'
        (target/'index.html').write_text(page)
        manifest={'schema_version':1,'status':'AWAITING_REVIEW','publication_enabled':False,
            'paid_generation_enabled':False,'production_approved':False,'full_av_review':False,'production_ready':False,
            'candidate_sha256':expected_candidate_sha256,'run_sha256':expected_run_sha256,
            'provenance':provenance,'optional_artifacts':optional,
            'scope':'Portable review delivery only; playback, NLE and creative acceptance require independent observation.',
            'files_sha256':{str(p.relative_to(target)):digest(p,deadline) for p in sorted(target.rglob('*')) if p.is_file()}}
        (target/'delivery-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True,allow_nan=False)+'\n')
        archive=output/'review-package.zip'
        with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(target.rglob('*')):
                if path.is_file():
                    with path.open('rb') as incoming,bundle.open('review/'+str(path.relative_to(target)),'w') as outgoing:
                        copy_chunks(incoming,outgoing,deadline)
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                with bundle.open(name) as stream:
                    while True:
                        check_deadline(deadline)
                        if not stream.read(1024*1024):break
        result=dict(manifest,archive_sha256=digest(archive,deadline),archive='review-package.zip',entrypoint='review/index.html')
        (output/'package.json').write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
        return result
    except BaseException:
        shutil.rmtree(output)
        raise
