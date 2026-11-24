import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {readMonitorPair,writeMonitorPair} from './persistence.mjs';

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
    last_error:raw.last_error??null,
    last_attempt_count:Number.isInteger(raw.last_attempt_count)?raw.last_attempt_count:null,
    last_attempts:Array.isArray(raw.last_attempts)?raw.last_attempts.map(attempt=>({...attempt})):[],
    last_check_recovered_by_retry:typeof raw.last_check_recovered_by_retry==='boolean'?raw.last_check_recovered_by_retry:null
  };
}

const OBSERVATION_FIELDS=['last_value','last_checked_at','last_change_at','last_status','last_error',
  'last_attempt_count','last_attempts','last_check_recovered_by_retry'];

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

function availability(watch){
  if(watch.last_error) return 'unavailable';
  if(watch.last_status>=200 && watch.last_status<300) return 'healthy';
  return 'unknown';
}

function recordAvailability(events,previous,current){
  const before=availability(previous);
  const after=availability(current);
  // Establish a silent healthy baseline. Record the first failure as an
  // observation from unknown and keep later repeated failures in state only.
  if(before===after || (before==='unknown' && after==='healthy')) return;
  events.push({id:crypto.randomUUID(),watch_id:current.id,at:current.last_checked_at,
    type:'availability',label:current.label,target_url:current.targetUrl,
    previous_availability:before,availability:after,http_status:current.last_status});
}

export const MAX_RESPONSE_BYTES=2*1024*1024;
export const DEFAULT_MAX_ATTEMPTS=2;
export const DEFAULT_REQUEST_TIMEOUT_MS=20000;
export const DEFAULT_RETRY_BACKOFF_MS=250;

function isRetryableError(error){
  const status=Number(error?.status);
  if(Number.isInteger(status)) return status===408 || status===425 || status===429 || status>=500;
  if(error?.name==='TimeoutError' || error?.name==='AbortError' || error instanceof TypeError) return true;
  const code=error?.code??error?.cause?.code;
  return ['ECONNRESET','ECONNREFUSED','EHOSTUNREACH','ENETUNREACH','EAI_AGAIN','ETIMEDOUT'].includes(code);
}

function validateRetryPolicy({maxAttempts,requestTimeoutMs,retryBackoffMs}){
  if(!Number.isInteger(maxAttempts) || maxAttempts<1 || maxAttempts>3) throw new Error('maxAttempts must be an integer from 1 to 3');
  if(!Number.isInteger(requestTimeoutMs) || requestTimeoutMs<1 || requestTimeoutMs>60000) throw new Error('requestTimeoutMs must be an integer from 1 to 60000');
  if(!Number.isInteger(retryBackoffMs) || retryBackoffMs<0 || retryBackoffMs>5000) throw new Error('retryBackoffMs must be an integer from 0 to 5000');
}

const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));

async function fetchHash(url,requestTimeoutMs){
  const r=await fetch(url,{redirect:'follow',signal:AbortSignal.timeout(requestTimeoutMs),headers:{'user-agent':'CYZOR-Free-Monitor/1.0'}});
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

async function fetchHashWithRetry(url,{maxAttempts,requestTimeoutMs,retryBackoffMs}){
  const attempts=[];
  for(let attempt=1;attempt<=maxAttempts;attempt++){
    const startedAt=Date.now();
    try{
      const check=await fetchHash(url,requestTimeoutMs);
      attempts.push({attempt,started_at:startedAt,completed_at:check.checkedAt,outcome:'success',
        http_status:check.status,response_bytes:check.response_bytes,response_limit_bytes:check.response_limit_bytes});
      return {...check,attempts,attempt_count:attempts.length,recovered_by_retry:attempts.length>1};
    }catch(error){
      const completedAt=Date.now();
      const retryable=isRetryableError(error);
      const willRetry=retryable && attempt<maxAttempts;
      attempts.push({attempt,started_at:startedAt,completed_at:completedAt,outcome:'error',
        http_status:error.status??null,error:String(error),retryable,will_retry:willRetry});
      if(!willRetry){
        error.attempts=attempts;
        error.checkedAt=completedAt;
        throw error;
      }
      await sleep(retryBackoffMs*attempt);
    }
  }
  throw new Error('retry loop exhausted without an outcome');
}

export async function runWorker({
  watchesPath='FREE_MONITOR_WATCHES.json',
  statePath='FREE_MONITOR_STATE.json',
  eventsPath='FREE_MONITOR_EVENTS.json',
  intervalMs=300000,
  maxAttempts=DEFAULT_MAX_ATTEMPTS,
  requestTimeoutMs=DEFAULT_REQUEST_TIMEOUT_MS,
  retryBackoffMs=DEFAULT_RETRY_BACKOFF_MS
}={}){
  validateRetryPolicy({maxAttempts,requestTimeoutMs,retryBackoffMs});
  const rawWatches=JSON.parse(await fs.readFile(watchesPath,'utf8'));
  const configuredWatches=rawWatches.map(normalizeWatch);
  // State is keyed by ID. Validate the entire configuration before any fetch
  // or write so a later duplicate cannot overwrite a failed target's evidence.
  if(new Set(configuredWatches.map(w=>w.id)).size!==configuredWatches.length){
    throw new Error('duplicate watch id');
  }
  const storage={statePath,eventsPath};
  const {state:priorState,events:priorEvents}=await readMonitorPair(storage);
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
      const check=await fetchHashWithRetry(base.targetUrl,{maxAttempts,requestTimeoutMs,retryBackoffMs});
      const {changed,next}=evaluateCheck(base,check);
      nextState[base.id]={...next,last_error:null,last_attempt_count:check.attempt_count,
        last_attempts:check.attempts,last_check_recovered_by_retry:check.recovered_by_retry};
      if(changed){
        events.push({id:crypto.randomUUID(),watch_id:base.id,at:check.checkedAt,type:'change',label:base.label,target_url:base.targetUrl});
      }
      if(check.recovered_by_retry){
        events.push({id:crypto.randomUUID(),watch_id:base.id,at:check.checkedAt,type:'retry_recovery',
          label:base.label,target_url:base.targetUrl,attempt_count:check.attempt_count,
          first_error:check.attempts[0].error,http_status:check.status});
      }
      results.push({id:base.id,checked:true,changed,status:check.status,last_checked_at:check.checkedAt,
        response_bytes:check.response_bytes,response_limit_bytes:check.response_limit_bytes,
        attempt_count:check.attempt_count,attempts:check.attempts,recovered_by_retry:check.recovered_by_retry});
    }catch(error){
      const checkedAt=error.checkedAt??Date.now();
      const attempts=Array.isArray(error.attempts)?error.attempts:[];
      nextState[base.id]={...base,last_checked_at:checkedAt,last_status:error.status??null,last_error:String(error),
        last_attempt_count:attempts.length,last_attempts:attempts,last_check_recovered_by_retry:false};
      results.push({id:base.id,checked:true,error:String(error),last_checked_at:checkedAt,
        attempt_count:attempts.length,attempts,recovered_by_retry:false});
    }
    recordAvailability(events,base,nextState[base.id]);
  }

  await writeMonitorPair(storage,nextState,events.slice(-500));
  return {ran_at:new Date(now).toISOString(),ok:Object.values(nextState).filter(w=>w.status==='active').every(w=>availability(w)==='healthy'),results};
}

if(isMainEntry(import.meta.url,process.argv[1])){
  const report=await runWorker();
  console.log(JSON.stringify(report,null,2));
  if(!report.ok) process.exitCode=2;
}
