"""One standalone command: existing producer, editable timeline, optional speech diagnostics, portable delivery."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

from integrations.agent_capacity import shared_admission_lock
from integrations.owned_process import interruptible_processes
from integrations.content_control.cycle_av_review import automated_review_command, read_automated_review
from integrations.content_control.video_job import producer_module, guarded_runner, check_completed, digest, validate
from integrations.content_control.review_package import package_review
from integrations.content_control.runtime_doctor import describe_source, inspect_runtime

ROOT=Path(__file__).resolve().parents[2]
TOOLS=('integrations/content_control/produce_review_bundle.py','integrations/content_control/review_package.py',
       'integrations/content_control/video_job.py','integrations/content_control/runtime_doctor.py',
       'integrations/content_control/cycle_av_review.py','integrations/content_control/cycle_av_benchmarks.py',
       'integrations/content_control/cycle_package.py',
       'integrations/owned_process.py','integrations/agent_capacity.py',
       'integrations/opentimelineio/export_review.py','integrations/dnsmos/score.py')


def write(path,value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')


def execute_stage(result,output,name,command,runner,deadline):
    entry={'name':name,'status':'RUNNING','log':name+'.log'}
    result['steps'].append(entry);write(output/'bundle.json',result)
    try:
        runner(list(map(str,command)),cwd=ROOT,log=output/entry['log'],deadline=deadline,env=os.environ)
    except BaseException:
        entry['status']='BLOCKED';write(output/'bundle.json',result)
        raise
    entry['status']='PASS';write(output/'bundle.json',result)


def produce_bundle(output,*,content_control_root,source_commit,source_manifest_sha256,
                   video_python,picture_python,otio_python,timeout=900,
                   dnsmos_python=None,dnsmos_model=None):
    request={'operation':'produce-episode1-review','source_commit':source_commit,
             'source_manifest_sha256':source_manifest_sha256,'timeout_seconds':timeout,
             'publication_enabled':False,'paid_generation_enabled':False}
    validate(request)
    output=Path(output).absolute(); output.mkdir(parents=True,exist_ok=False)
    result={'schema_version':1,'status':'BLOCKED','started_at':datetime.now(timezone.utc).isoformat(),
            'publication_enabled':False,'paid_generation_enabled':False,'production_approved':False,
            'full_av_review':False,'production_ready':False,'execution_mode':'standalone_serialized_artifact_run',
            'queue_capacity_admission_verified':False,'steps':[],
            'scope':'Existing approved inputs to a portable unpublished review. No creative approval or always-on host claim.'}
    deadline=time.monotonic()+timeout
    source_root=Path(content_control_root).resolve()
    before={name:digest(ROOT/name) for name in TOOLS}
    result['tool_sha256']=before
    stage='preflight'
    write(output/'bundle.json',result)
    try:
        if sys.version_info<(3,11) or not hasattr(os,'sched_getaffinity'):
            raise ValueError('Linux/WSL2 and Python3.11+ required')
        if bool(dnsmos_python)!=bool(dnsmos_model):
            raise ValueError('Optional DNSMOS requires both runtime and local pinned model')
        runtimes=[video_python,picture_python,otio_python]+([dnsmos_python] if dnsmos_python else [])
        for runtime in runtimes:
            if not Path(runtime).is_absolute() or not Path(runtime).is_file() or not os.access(runtime,os.X_OK):
                raise ValueError('Explicit absolute executable runtime paths required')
        if any(os.environ.get(flag,'false').lower()!='false'
               for flag in ('PUBLICATION_ENABLED','PAID_GENERATION_ENABLED')):
            raise ValueError('Publication and paid generation must remain disabled')
        cpus=sorted(os.sched_getaffinity(0))[:2]
        if len(cpus)<2: raise ValueError('Two CPU affinity slots required')
        result['cpu_affinity']=cpus
        # Serializes with the agent workers without claiming their unavailable
        # host-budget admission. This command is an explicitly chosen artifact run.
        with interruptible_processes(),shared_admission_lock() as lease:
            runner=guarded_runner(lease,cpus)
            def run(name,command):
                nonlocal stage
                stage=name
                execute_stage(result,output,name,command,runner,deadline)
            source=describe_source(source_root,expected_commit=source_commit,lease_fd=lease,deadline=deadline)
            runtime=inspect_runtime(source_root,video_python,picture_python,lease_fd=lease,deadline=deadline)
            write(output/'prerequisites.json',{'source':source,'runtime':runtime})
            if runtime.get('status')!='PASS': raise ValueError('Runtime prerequisites blocked')
            if source['source_manifest_sha256']!=source_manifest_sha256: raise ValueError('Source manifest mismatch')
            result['source']=source
            remaining=math.floor(deadline-time.monotonic())
            if remaining<30: raise TimeoutError('Budget exhausted before production')
            stage='production'
            # Every nested producer stage uses the same guardian/lease/deadline.
            def bounded_stage(command,**kwargs):
                kwargs['deadline']=min(kwargs['deadline'],deadline)
                return runner(command,**kwargs)
            with producer_module(source_root) as producer:
                produced=producer.produce(output/'review',python=video_python,picture_python=picture_python,
                    timeout=remaining,root=source_root,command_runner=bounded_stage)
            if produced.get('status')!='AWAITING_REVIEW':
                result['pipeline_failed_step']=produced.get('failed_step')
                raise ValueError('Existing producer did not complete')
            receipt=check_completed(output/'review',source)
            run_sha=digest(output/'review/run.json')
            review_path=output/'automated-review.json'
            stage='automated-review'
            run(stage,automated_review_command(output/'review',review_path,receipt,deadline))
            try:
                raw=read_automated_review(review_path,receipt['candidate_sha256'],receipt['artifacts_sha256']['captions.vtt'])
                review_sha=hashlib.sha256(raw).hexdigest()
            except (OSError,ValueError):
                result['steps'][-1]['status']='BLOCKED'
                raise
            result['automated_review_sha256']=review_sha
            run('editable-export',[otio_python,'-m','integrations.opentimelineio.export_review',
                '--review-dir',output/'review','--run-sha256',run_sha,'--output',output/'edit'])
            diagnostic={'status':'SKIPPED','reason':'Optional isolated-speech diagnostic not requested'}
            diagnostic_dir=None
            if dnsmos_python:
                stage='speech-diagnostic'; diagnostic_dir=output/'diagnostics'; diagnostic_dir.mkdir()
                narration=source_root/'public/audio/episode1-narration.mp3'
                source_hash=source['source_files']['public/audio/episode1-narration.mp3']
                if digest(narration)!=source_hash: raise ValueError('Isolated narration source changed')
                wav=diagnostic_dir/'isolated-narration.wav'
                try:
                    run('speech-conversion',['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-n',
                        '-threads','2','-i',narration,'-ar','16000','-ac','1','-c:a','pcm_s16le',wav])
                    run('speech-diagnostic',[dnsmos_python,'-m','integrations.dnsmos.score',
                        '--audio',wav,'--model',Path(dnsmos_model).absolute(),'--isolated-speech'])
                    diagnostic=json.loads((output/'speech-diagnostic.log').read_text())
                    if (diagnostic.get('status')!='DIAGNOSTIC_COMPLETE' or diagnostic.get('audio_sha256')!=digest(wav)
                        or any(diagnostic.get(key) is not False for key in ('publication_enabled','production_approved','full_av_review'))):
                        raise ValueError('Diagnostic identity or scope mismatch')
                except (OSError,ValueError,RuntimeError,TimeoutError) as error:
                    diagnostic={'status':'BLOCKED','reason':str(error),'scope':'Optional diagnostic only; no quality approval'}
                diagnostic['source_narration_sha256']=source_hash
                diagnostic['publication_enabled']=False; diagnostic['production_approved']=False
                write(diagnostic_dir/'speech-diagnostic.json',diagnostic)
            result['speech_diagnostic']=diagnostic
            stage='source-after'
            after=describe_source(source_root,expected_commit=source_commit,lease_fd=lease,deadline=deadline)
            write(output/'source-after.json',after)
            if after.get('source_manifest_sha256')!=source_manifest_sha256: raise ValueError('Source changed during production')
            if before!={name:digest(ROOT/name) for name in TOOLS}: raise ValueError('Integration source changed during run')
            if time.monotonic()>=deadline: raise TimeoutError('Bundle deadline exhausted')
            stage='delivery'
            delivered=package_review(output/'review',output/'delivery',expected_run_sha256=run_sha,
                expected_candidate_sha256=receipt['candidate_sha256'],
                provenance={'execution_mode':result['execution_mode'],'source_commit':source_commit,
                            'source_manifest_sha256':source_manifest_sha256,'tool_sha256':before,
                            'automated_review_sha256':review_sha,
                            'speech_diagnostic_status':diagnostic['status']},
                edit_dir=output/'edit',diagnostics_dir=diagnostic_dir,
                automated_review=(review_path,review_sha),deadline=deadline)
            if time.monotonic()>=deadline: raise TimeoutError('Bundle deadline exhausted during delivery')
            result.update(status='AWAITING_REVIEW',technical_status='PASS',candidate_sha256=receipt['candidate_sha256'],
                run_sha256=run_sha,source_inputs_unchanged=True,delivery=delivered)
    except (OSError,ValueError,RuntimeError,TimeoutError,KeyError,TypeError) as error:
        result.update(status='BLOCKED',failed_step=stage,reason=str(error),partial_outputs_retained=True)
        for entry in result['steps']:
            if entry['status']=='RUNNING':entry['status']='BLOCKED'
    finally:
        result['finished_at']=datetime.now(timezone.utc).isoformat(); write(output/'bundle.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('output','content-control-root','source-commit','source-manifest-sha256','video-python','picture-python','otio-python'):
        p.add_argument('--'+arg,required=True)
    p.add_argument('--timeout',type=int,default=900)
    p.add_argument('--dnsmos-python');p.add_argument('--dnsmos-model')
    args=vars(p.parse_args());result=produce_bundle(**args);print(json.dumps(result,indent=2))
    return 0 if result['status']=='AWAITING_REVIEW' else 2


if __name__=='__main__':raise SystemExit(main())
