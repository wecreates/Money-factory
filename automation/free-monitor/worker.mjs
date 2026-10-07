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
    last_change_at:raw.last_change_at??null
  };
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

async function fetchHash(url){
  const r=await fetch(url,{redirect:'follow',headers:{'user-agent':'CYZOR-Free-Monitor/1.0'}});
  const body=await r.arrayBuffer();
  const hash=crypto.createHash('sha256').update(Buffer.from(body)).digest('hex');
  return {hash,checkedAt:Date.now(),status:r.status};
}

export async function runWorker({
  watchesPath='FREE_MONITOR_WATCHES.json',
  statePath='FREE_MONITOR_STATE.json',
  eventsPath='FREE_MONITOR_EVENTS.json',
  intervalMs=300000
}={}){
  const rawWatches=JSON.parse(await fs.readFile(watchesPath,'utf8'));
  const priorState=JSON.parse(await fs.readFile(statePath,'utf8').catch(()=> '{}'));
  const priorEvents=JSON.parse(await fs.readFile(eventsPath,'utf8').catch(()=> '[]'));
  const now=Date.now();
  const nextState={};
  const events=[...priorEvents];
  const results=[];

  for(const raw of rawWatches){
    const base=normalizeWatch({...raw,...priorState[raw.id]});
    if(!dueForCheck(base,now,intervalMs)){
      nextState[base.id]=base;
      results.push({id:base.id,checked:false,reason:'not_due'});
      continue;
    }
    try{
      const check=await fetchHash(base.targetUrl);
      const {changed,next}=evaluateCheck(base,check);
      nextState[base.id]=next;
      if(changed){
        events.push({id:crypto.randomUUID(),watch_id:base.id,at:check.checkedAt,type:'change',label:base.label,target_url:base.targetUrl});
      }
      results.push({id:base.id,checked:true,changed,status:check.status,last_checked_at:check.checkedAt});
    }catch(error){
      nextState[base.id]={...base,last_checked_at:now,last_error:String(error)};
      results.push({id:base.id,checked:true,error:String(error),last_checked_at:now});
    }
  }

  await fs.writeFile(statePath,JSON.stringify(nextState,null,2)+'\n');
  await fs.writeFile(eventsPath,JSON.stringify(events.slice(-500),null,2)+'\n');
  return {ran_at:new Date(now).toISOString(),results};
}

if(isMainEntry(import.meta.url,process.argv[1])){
  const report=await runWorker();
  console.log(JSON.stringify(report,null,2));
}
