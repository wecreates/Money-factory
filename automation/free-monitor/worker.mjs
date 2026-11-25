import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {readMonitorPair,writeMonitorPair} from './persistence.mjs';
import {collectResourceObservation,declaredWorkflowWallLimit,requestEnvelopeMs,
  validateWallEnvelope,RUNTIME_STATE_KEY} from './resources.mjs';
import {buildCadenceEvidence} from './cadence.mjs';

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
    last_scheduled_check_slot_at:Number.isSafeInteger(raw.last_scheduled_check_slot_at)
      && raw.last_scheduled_check_slot_at>0?raw.last_scheduled_check_slot_at:null,
    last_change_at:raw.last_change_at??null,
    last_status:raw.last_status??null,
    last_error:raw.last_error??null,
    unavailable_since:Number.isSafeInteger(raw.unavailable_since) && raw.unavailable_since>0
      ? raw.unavailable_since:null,
    last_attempt_count:Number.isInteger(raw.last_attempt_count)?raw.last_attempt_count:null,
    last_attempts:Array.isArray(raw.last_attempts)?raw.last_attempts.map(attempt=>({...attempt})):[],
    last_check_recovered_by_retry:typeof raw.last_check_recovered_by_retry==='boolean'?raw.last_check_recovered_by_retry:null
  };
}

const OBSERVATION_FIELDS=['last_value','last_checked_at','last_scheduled_check_slot_at','last_change_at','last_status','last_error',
  'unavailable_since','last_attempt_count','last_attempts','last_check_recovered_by_retry'];

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

export function dueForCheck(watch,now=Date.now(),intervalMs=300000,scheduledSlot=null){
  if(watch.status!=='active') return false;
  // A slow prior request must not block the next scheduled slot. Keep the
  // actual completion time for manual throttling and observation evidence.
  if(scheduledSlot!==null) return scheduledSlot>watch.last_scheduled_check_slot_at;
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

const ALERT_KINDS=new Set(['outage','recovery']);
const MAX_EVENTS=500;

export function isPendingAlertIntent(event){
  if(event===null || typeof event!=='object' || Array.isArray(event)) return false;
  const exact=new Set(['id','watch_id','at','type','alert_kind','outage_started_at','label',
    'target_url','delivery_status','delivery_attempts','external_delivery_performed',
    'publication_enabled']);
  return Object.keys(event).length===exact.size
    && Object.keys(event).every(key=>exact.has(key))
    && typeof event.id==='string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(event.id)
    && typeof event.watch_id==='string' && event.watch_id.length>0
    && Number.isSafeInteger(event.at) && event.at>0
    && event.type==='alert_intent' && ALERT_KINDS.has(event.alert_kind)
    && Number.isSafeInteger(event.outage_started_at) && event.outage_started_at>0
    && event.at>=event.outage_started_at
    && typeof event.label==='string' && event.label.length>0
    && typeof event.target_url==='string'
    && ['http:','https:'].includes(new URL(event.target_url).protocol)
    && event.delivery_status==='pending' && event.delivery_attempts===0
    && event.external_delivery_performed===false && event.publication_enabled===false;
}

export function pendingAlertIntents(events){
  if(!Array.isArray(events)) throw new Error('events must be an array');
  return events.filter(event=>{
    try{return isPendingAlertIntent(event);}catch{return false;}
  }).map(event=>({...event}));
}

function ensureAlertIntent(events,current,kind,outageStartedAt,at){
  if(!Number.isSafeInteger(outageStartedAt) || outageStartedAt<=0
      || !Number.isSafeInteger(at) || at<outageStartedAt) return;
  const duplicate=pendingAlertIntents(events).some(event=>event.watch_id===current.id
    && event.target_url===current.targetUrl && event.alert_kind===kind
    && event.outage_started_at===outageStartedAt);
  if(duplicate) return;
  events.push({id:crypto.randomUUID(),watch_id:current.id,at,type:'alert_intent',alert_kind:kind,
    outage_started_at:outageStartedAt,label:current.label,target_url:current.targetUrl,
    delivery_status:'pending',delivery_attempts:0,external_delivery_performed:false,
    publication_enabled:false});
}

function recordAlertIntents(events,previous,current){
  const before=availability(previous);
  const after=availability(current);
  if(after==='unavailable'){
    ensureAlertIntent(events,current,'outage',current.unavailable_since,current.unavailable_since);
  }else if(before==='unavailable' && after==='healthy'){
    const outageStartedAt=previous.unavailable_since??previous.last_checked_at;
    // A legacy outage may predate alert-intent support. Retain its pending
    // outage before recording recovery so the delivery stage cannot silently
    // skip the original failure.
    ensureAlertIntent(events,current,'outage',outageStartedAt,outageStartedAt);
    ensureAlertIntent(events,current,'recovery',outageStartedAt,current.last_checked_at);
  }
}

function retainEvents(events){
  const pending=new Set(events.filter(event=>{
    try{return isPendingAlertIntent(event);}catch{return false;}
  }));
  if(pending.size>MAX_EVENTS){
    throw new Error(`Pending alert outbox exceeds ${MAX_EVENTS} event limit`);
  }
  const ordinary=events.filter(event=>!pending.has(event));
  const ordinaryCapacity=MAX_EVENTS-pending.size;
  const retainedOrdinary=new Set(ordinaryCapacity===0?[]:ordinary.slice(-ordinaryCapacity));
  // Pending delivery work is never silently evicted by change-event volume.
  // Preserve source ordering so the event log remains deterministic.
  return events.filter(event=>pending.has(event) || retainedOrdinary.has(event));
}

export const MAX_RESPONSE_BYTES=2*1024*1024;
export const DEFAULT_INTERVAL_MS=300000;
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
  intervalMs=DEFAULT_INTERVAL_MS,
  cadenceIntervalMs=DEFAULT_INTERVAL_MS,
  maxAttempts=DEFAULT_MAX_ATTEMPTS,
  requestTimeoutMs=DEFAULT_REQUEST_TIMEOUT_MS,
  retryBackoffMs=DEFAULT_RETRY_BACKOFF_MS,
  workflowWallLimitMs=declaredWorkflowWallLimit(process.env.MONITOR_WORKFLOW_WALL_LIMIT_MS)
}={}){
  validateRetryPolicy({maxAttempts,requestTimeoutMs,retryBackoffMs});
  const rawWatches=JSON.parse(await fs.readFile(watchesPath,'utf8'));
  const configuredWatches=rawWatches.map(normalizeWatch);
  // State is keyed by ID. Validate the entire configuration before any fetch
  // or write so a later duplicate cannot overwrite a failed target's evidence.
  if(new Set(configuredWatches.map(w=>w.id)).size!==configuredWatches.length){
    throw new Error('duplicate watch id');
  }
  if(configuredWatches.some(w=>w.id===RUNTIME_STATE_KEY)){
    throw new Error('reserved monitor runtime state id');
  }
  const activeWatches=configuredWatches.filter(w=>w.status==='active').length;
  const requestEnvelope=requestEnvelopeMs(activeWatches,{maxAttempts,requestTimeoutMs,retryBackoffMs});
  validateWallEnvelope(workflowWallLimitMs,requestEnvelope);
  const storage={statePath,eventsPath};
  const {state:priorState,events:priorEvents}=await readMonitorPair(storage);
  const now=Date.now();
  const startedAt=new Date(now).toISOString();
  const cadence=buildCadenceEvidence({startedAt,priorRuntime:priorState[RUNTIME_STATE_KEY],
    targetIntervalMs:cadenceIntervalMs,
    invocationSource:process.env.GITHUB_EVENT_NAME||'local',
    invocationId:process.env.GITHUB_RUN_ID||null,
    invocationAttempt:process.env.GITHUB_RUN_ATTEMPT||null});
  const scheduledSlot=intervalMs===cadenceIntervalMs && cadence.scheduled_invocation_qualified
    && cadence.scheduled_chain_status!=='invalid_scheduled_observation'
    ? Date.parse(cadence.last_scheduled_slot_at):null;
  const nextState={};
  const events=[...priorEvents];
  const results=[];

  for(const configured of configuredWatches){
    const base=reconcileWatch(configured,priorState[configured.id]);
    if(!dueForCheck(base,now,intervalMs,scheduledSlot)){
      nextState[base.id]=base;
      results.push({id:base.id,checked:false,reason:'not_due'});
      continue;
    }
    const lastScheduledCheckSlot=scheduledSlot??base.last_scheduled_check_slot_at;
    try{
      const check=await fetchHashWithRetry(base.targetUrl,{maxAttempts,requestTimeoutMs,retryBackoffMs});
      const {changed,next}=evaluateCheck(base,check);
      nextState[base.id]={...next,last_error:null,last_attempt_count:check.attempt_count,
        unavailable_since:null,last_attempts:check.attempts,
        last_scheduled_check_slot_at:lastScheduledCheckSlot,
        last_check_recovered_by_retry:check.recovered_by_retry};
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
      const unavailableSince=base.unavailable_since
        ?? (availability(base)==='unavailable'?base.last_checked_at:null) ?? checkedAt;
      nextState[base.id]={...base,last_checked_at:checkedAt,last_status:error.status??null,last_error:String(error),
        unavailable_since:unavailableSince,last_attempt_count:attempts.length,
        last_scheduled_check_slot_at:lastScheduledCheckSlot,
        last_attempts:attempts,last_check_recovered_by_retry:false};
      results.push({id:base.id,checked:true,error:String(error),last_checked_at:checkedAt,
        attempt_count:attempts.length,attempts,recovered_by_retry:false});
    }
    recordAvailability(events,base,nextState[base.id]);
    recordAlertIntents(events,base,nextState[base.id]);
  }

  const resources=await collectResourceObservation({startedAt,activeWatches,
    policy:{maxAttempts,requestTimeoutMs,retryBackoffMs},workflowWallLimitMs});
  resources.cadence=cadence;
  nextState[RUNTIME_STATE_KEY]=resources;

  const retainedEvents=retainEvents(events);
  await writeMonitorPair(storage,nextState,retainedEvents);
  return {ran_at:new Date(now).toISOString(),
    ok:Object.values(nextState).filter(w=>w.status==='active').every(w=>availability(w)==='healthy'),
    alert_outbox_pending:pendingAlertIntents(retainedEvents).length,resources,results};
}

if(isMainEntry(import.meta.url,process.argv[1])){
  const report=await runWorker();
  console.log(JSON.stringify(report,null,2));
  if(!report.ok) process.exitCode=2;
}
