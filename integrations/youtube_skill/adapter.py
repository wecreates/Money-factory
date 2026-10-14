"""Six real, offline upstream YouTube analysis CLIs with bounded inputs."""
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

REVISION='a2feb2104981a375ffd4f87ee04f4f5344ac43c6'
SCRIPTS={'hook-score':'yt-script/hookscore.py','package-lint':'yt-package/title.py',
         'edit-plan':'yt-edit/deadair.py','chapters':'yt-chapters/chapters.py',
         'retention':'yt-retention/retention.py','outliers':'yt-viral/swipe.py'}


def text(payload,key,limit=200000):
    value=payload.get(key)
    if not isinstance(value,str) or not value.strip() or len(value)>limit or '\0' in value:
        raise ValueError(f'{key} must be nonempty bounded text')
    return value


def number(value,minimum,maximum):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not minimum<=value<=maximum:
        raise ValueError('Invalid numeric option')
    return value


def transcript(payload):
    value=text(payload,'transcript_srt')
    matches=re.findall(r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})',value)
    if not matches:raise ValueError('No SRT timestamps')
    last=-1
    for match in matches:
        h,m,s,ms,h2,m2,s2,ms2=map(int,match)
        start=h*3600+m*60+s+ms/1000;end=h2*3600+m2*60+s2+ms2/1000
        if max(m,s,m2,s2)>=60 or start<last or end<=start or end>86400:raise ValueError('Invalid or overlapping SRT cues')
        last=end
    return value


def command(operation,payload,folder):
    def write(name,value):
        path=folder/name;path.write_text(value,encoding='utf-8');return str(path)
    if operation=='hook-score':return ['--hook',text(payload,'hook',3000)]
    if operation=='package-lint':return ['--title',text(payload,'title',1000),'--thumb',text(payload,'thumb',500)]
    if operation in ('edit-plan','chapters'):
        args=[write('transcript.srt',transcript(payload))]
        if operation=='edit-plan':return args+['--floor',str(number(payload.get('floor',.45),.05,10))]
        target=number(payload.get('target',7),3,50)
        if int(target)!=target:raise ValueError('Chapter target must be integer')
        return args+['--target',str(int(target))]
    if operation=='retention':
        if payload.get('axis')!='percent':raise ValueError('Retention input must explicitly use percent timeline')
        duration=number(payload.get('duration'),1,86400)
        value=text(payload,'retention_csv');points=[]
        for index,row in enumerate(csv.reader(io.StringIO(value))):
            if not row:continue
            if len(row)!=2:raise ValueError('Retention CSV requires exactly two columns')
            try: x,y=(float(v.strip().removesuffix('%')) for v in row)
            except ValueError:
                if index==0:continue
                raise ValueError('Malformed retention row')
            number(x,0,100);number(y,0,1000)
            if points and x<=points[-1][0]:raise ValueError('Retention timeline must increase')
            points.append((x,y))
        if len(points)<8:raise ValueError('Retention requires at least eight points')
        args=[write('retention.csv',value),'--duration',str(duration)]
        if 'transcript_srt' in payload:args+=['--transcript',write('transcript.srt',transcript(payload))]
        return args
    if operation=='outliers':
        rows=payload.get('collected')
        if not isinstance(rows,list) or not 1<=len(rows)<=2000:raise ValueError('Provide 1..2000 collected videos')
        for row in rows:
            if not isinstance(row,dict):raise ValueError('Malformed collected video')
            text(row,'channel',500);text(row,'title',2000);number(row.get('views'),0,1e12)
            if 'url' in row and (not isinstance(row['url'],str) or len(row['url'])>2000):raise ValueError('Invalid video URL')
        return [write('collected.json',json.dumps(rows)),'--min',str(number(payload.get('minimum_multiple',1.5),0,1000))]
    raise ValueError('Unsupported YouTube skill operation')


def dispatch(job,upstream):
    if job.get('publication_enabled') is not False or job.get('paid_generation_enabled') is not False:
        raise ValueError('Explicit free, publication-disabled job required')
    operation=job['operation']
    if operation not in SCRIPTS:raise ValueError('Unsupported YouTube skill operation')
    input_path=Path(job['input'])
    if input_path.is_symlink() or not input_path.is_file() or input_path.stat().st_size>1024*1024:raise ValueError('Bounded unlinked input JSON required')
    raw=input_path.read_bytes();payload=json.loads(raw)
    if not isinstance(payload,dict):raise ValueError('Input must be a JSON object')
    upstream=Path(upstream).resolve()
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=upstream,text=True).strip()
    if revision!=REVISION:raise ValueError('Unexpected upstream revision')
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=upstream,text=True).strip():raise ValueError('Modified upstream source')
    script=upstream/'skills'/SCRIPTS[operation]
    with tempfile.TemporaryDirectory(prefix='money-factory-youtube-') as tmp:
        folder=Path(tmp);args=command(operation,payload,folder)
        env={'PATH':os.environ.get('PATH',''),'HOME':tmp,'PYTHONHASHSEED':'0','PYTHONIOENCODING':'utf-8'}
        run=subprocess.run([sys.executable,str(script),*args,'--json'],cwd=folder,env=env,capture_output=True,text=True,timeout=30)
    try:findings=json.loads(run.stdout)
    except json.JSONDecodeError:findings=None
    success=run.returncode==0 and isinstance(findings,(dict,list))
    if input_path.read_bytes()!=raw:raise ValueError('Input changed during analysis')
    return {'schema_version':1,'tool':'youtube-agent-skill','operation':operation,
      'status':'PASS' if success else 'BLOCKED','execution_status':'PASS' if success else 'BLOCKED',
      'exit_code':run.returncode,'upstream_revision':revision,'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),
      'input_sha256':hashlib.sha256(raw).hexdigest(),'findings':findings,'stdout':run.stdout,'stderr':run.stderr,
      'publication_enabled':False,'paid_generation_enabled':False,'production_ready':False,
      'scope':'Actual offline heuristic execution; negative findings retained, not audience prediction or publication approval'}
