import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

export function isMainEntry(importMetaUrl,argv1){
  if(!argv1) return false;
  return path.resolve(fileURLToPath(importMetaUrl))===path.resolve(argv1);
}

export function normalizeWatch(raw){
  const id=String(raw?.id||'').trim();
  if(!id) throw new Error('watch id required');
  const targetUrl=new URL(raw.targetUrl||raw.target_url).toString();
  if(!['http:','https:'].includes(new URL(targetUrl).protocol)) throw new Error('http(s) only');
  return {
    id,
    kind:raw.kind||'change',
    targetUrl,
    label:String(raw.label||id),
    status:raw.status||'active',
    last_value:raw.last_value??null,
    last_checked_at:raw.last_checked_at??null,
    last_change_at:raw.last_change_at??null,
    last_status:raw.last_status??null,
    last_error:raw.last_error??null
  };
}

const OBSERVATION_FIELDS=['last_value','last_checked_at','last_change_at','last_status','last_error'];

export function reconcileWatch(raw,prior){
  const current=normalizeWatch(raw);
  // Configuration owns identity and controls. Only observations from the same
  // normalized target and kind may survive; a retarget needs a fresh baseline.
  for(const field of OBSERVATION_FIELDS) current[field]=null;
  let previous;
  try{ previous=normalizeWatch(prior); }catch{ return current; }
  if(previous.id===current.id && previous.targetUrl===current.targetUrl && previous.kind===current.kind){
    for(const field of OBSERVATION_FIELDS) current[field]=previous[field];
  }
  return current;
}

export function dueForCheck(watch,now=Date.now(),intervalMs=300000){
  if(watch.status!=='active') return false;
  if(!watch.last_checked_at) return true;
  return now-Number(watch.last_checked_at)>=intervalMs;
}

export function evaluateCheck(watch,check){
  const previous=watch.last_value;
  const changed=previous!==null && previous!==check.hash;
  return {
    changed,
    next:{
      ...watch,
      last_value:check.hash,
      last_checked_at:check.checkedAt,
      last_change_at:changed?check.checkedAt:watch.last_change_at??null,
      last_status:check.status
    }
  };
}

export const MAX_RESPONSE_BYTES=2*1024*1024;

async function fetchHash(url){
  const r=await fetch(url,{redirect:'follow',signal:AbortSignal.timeout(20000),headers:{'user-agent':'CYZOR-Free-Monitor/1.0'}});
  if(!r.ok){ await r.body?.cancel(); throw Object.assign(new Error(`HTTP ${r.status} from monitored URL`),{status:r.status}); }
  // Fetch exposes decoded bytes, so compressed and chunked responses share the
  // same ceiling. Never trust Content-Length or retain the whole response.
  const hash=crypto.createHash('sha256');
  let bytes=0;
  const reader=r.body?.getReader();
  if(reader){
    try{
      while(true){
        const {done,value}=await reader.read();
        if(done) break;
        bytes+=value.byteLength;
        if(bytes>MAX_RESPONSE_BYTES){
          throw new Error(`Decoded response exceeds ${MAX_RESPONSE_BYTES} byte limit`);
        }
        hash.update(value);
      }
    }catch(error){
      await reader.cancel().catch(()=>{});
      throw error;
    }finally{
      reader.releaseLock();
    }
  }
  return {hash:hash.digest('hex'),checkedAt:Date.now(),status:r.status,
    response_bytes:bytes,response_limit_bytes:MAX_RESPONSE_BYTES};
}

export async function runWorker({
  watchesPath='FREE_MONITOR_WATCHES.json',
  statePath='FREE_MONITOR_STATE.json',
  eventsPath='FREE_MONITOR_EVENTS.json',
  intervalMs=300000
}={}){
  const rawWatches=JSON.parse(await fs.readFile(watchesPath,'utf8'));
  const configuredWatches=rawWatches.map(normalizeWatch);
  // State is keyed by ID. Validate the entire configuration before any fetch
  // or write so a later duplicate cannot overwrite a failed target's evidence.
  if(new Set(configuredWatches.map(w=>w.id)).size!==configuredWatches.length){
    throw new Error('duplicate watch id');
  }
  const priorState=JSON.parse(await fs.readFile(statePath,'utf8').catch(()=> '{}'));
  const priorEvents=JSON.parse(await fs.readFile(eventsPath,'utf8').catch(()=> '[]'));
  const now=Date.now();
  const nextState={};
  const events=[...priorEvents];
  const results=[];

  for(const configured of configuredWatches){
    const base=reconcileWatch(configured,priorState[configured.id]);
    if(!dueForCheck(base,now,intervalMs)){
      nextState[base.id]=base;
      results.push({id:base.id,checked:false,reason:'not_due'});
      continue;
    }
    try{
      const check=await fetchHash(base.targetUrl);
      const {changed,next}=evaluateCheck(base,check);
      nextState[base.id]={...next,last_error:null};
      if(changed){
        events.push({id:crypto.randomUUID(),watch_id:base.id,at:check.checkedAt,type:'change',label:base.label,target_url:base.targetUrl});
      }
      results.push({id:base.id,checked:true,changed,status:check.status,last_checked_at:check.checkedAt,
        response_bytes:check.response_bytes,response_limit_bytes:check.response_limit_bytes});
    }catch(error){
      nextState[base.id]={...base,last_checked_at:now,last_status:error.status??null,last_error:String(error)};
      results.push({id:base.id,checked:true,error:String(error),last_checked_at:now});
    }
  }

  await fs.writeFile(statePath,JSON.stringify(nextState,null,2)+'\n');
  await fs.writeFile(eventsPath,JSON.stringify(events.slice(-500),null,2)+'\n');
  return {ran_at:new Date(now).toISOString(),ok:Object.values(nextState).filter(w=>w.status==='active').every(w=>!w.last_error && w.last_status>=200 && w.last_status<300),results};
}

if(isMainEntry(import.meta.url,process.argv[1])){
  const report=await runWorker();
  console.log(JSON.stringify(report,null,2));
  if(!report.ok) process.exitCode=2;
}
