import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {writeJsonAtomic} from './persistence.mjs';
import {isPendingAlertIntent,pendingAlertIntents} from './worker.mjs';

const LEDGER_SCHEMA=1;
const LEDGER_TYPE='monitor_alert_delivery_ledger';
const RECORD_TYPE='monitor_alert_delivery';
const TERMINAL_STATUSES=new Set(['acknowledged','dead_letter']);

function exactKeys(value,keys){
  return value!==null && typeof value==='object' && !Array.isArray(value)
    && Object.keys(value).length===keys.length && Object.keys(value).every(key=>keys.includes(key));
}

function positiveInteger(value){ return Number.isSafeInteger(value) && value>0; }
function nonnegativeInteger(value){ return Number.isSafeInteger(value) && value>=0; }

function intentProjection(intent){
  return {id:intent.id,watch_id:intent.watch_id,at:intent.at,type:intent.type,
    alert_kind:intent.alert_kind,outage_started_at:intent.outage_started_at,label:intent.label,
    target_url:intent.target_url,delivery_status:intent.delivery_status,
    delivery_attempts:intent.delivery_attempts,
    external_delivery_performed:intent.external_delivery_performed,
    publication_enabled:intent.publication_enabled};
}

export function alertIntentSha256(intent){
  if(!isPendingAlertIntent(intent)) throw new Error('valid pending alert intent required');
  return crypto.createHash('sha256').update(JSON.stringify(intentProjection(intent))).digest('hex');
}

function validateAttempt(attempt,index){
  const keys=['attempt','started_at','completed_at','outcome','error_code'];
  return exactKeys(attempt,keys) && attempt.attempt===index+1
    && positiveInteger(attempt.started_at) && positiveInteger(attempt.completed_at)
    && attempt.completed_at>=attempt.started_at
    && ['acknowledged','error'].includes(attempt.outcome)
    && (attempt.error_code===null
      || (typeof attempt.error_code==='string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(attempt.error_code)))
    && (attempt.outcome==='acknowledged')===(attempt.error_code===null);
}

function validateRecord(record,id){
  const keys=['schema_version','type','intent_id','intent_sha256','watch_id','alert_kind',
    'outage_started_at','delivery_status','delivery_attempts','acknowledged_at',
    'dead_lettered_at','last_error_code','local_receipt_id','external_delivery_performed',
    'publication_enabled','attempts'];
  if(!exactKeys(record,keys) || record.schema_version!==LEDGER_SCHEMA
      || record.type!==RECORD_TYPE || record.intent_id!==id
      || typeof record.intent_sha256!=='string' || !/^[0-9a-f]{64}$/.test(record.intent_sha256)
      || typeof record.watch_id!=='string' || record.watch_id.length===0
      || !['outage','recovery'].includes(record.alert_kind)
      || !positiveInteger(record.outage_started_at)
      || !['pending','acknowledged','dead_letter'].includes(record.delivery_status)
      || !nonnegativeInteger(record.delivery_attempts)
      || !Array.isArray(record.attempts) || record.attempts.length!==record.delivery_attempts
      || !record.attempts.every(validateAttempt)
      || record.external_delivery_performed!==false || record.publication_enabled!==false){
    return false;
  }
  if(record.delivery_status==='pending'){
    return record.acknowledged_at===null && record.dead_lettered_at===null
      && record.local_receipt_id===null
      && (record.delivery_attempts===0
        ? record.last_error_code===null
        : record.attempts.at(-1)?.outcome==='error'
          && record.last_error_code===record.attempts.at(-1)?.error_code);
  }
  if(record.delivery_status==='acknowledged'){
    return positiveInteger(record.acknowledged_at) && record.dead_lettered_at===null
      && record.last_error_code===null && typeof record.local_receipt_id==='string'
      && /^[A-Za-z0-9._:-]{1,128}$/.test(record.local_receipt_id)
      && record.attempts.at(-1)?.outcome==='acknowledged';
  }
  return record.acknowledged_at===null && positiveInteger(record.dead_lettered_at)
    && typeof record.last_error_code==='string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(record.last_error_code)
    && record.local_receipt_id===null && record.attempts.at(-1)?.outcome==='error';
}

function emptyLedger(observedAt){
  return {schema_version:LEDGER_SCHEMA,type:LEDGER_TYPE,observed_at:observedAt,
    external_delivery_performed:false,publication_enabled:false,records:{}};
}

function validateLedger(ledger){
  const keys=['schema_version','type','observed_at','external_delivery_performed',
    'publication_enabled','records'];
  if(!exactKeys(ledger,keys) || ledger.schema_version!==LEDGER_SCHEMA || ledger.type!==LEDGER_TYPE
      || !positiveInteger(ledger.observed_at) || ledger.external_delivery_performed!==false
      || ledger.publication_enabled!==false || ledger.records===null
      || typeof ledger.records!=='object' || Array.isArray(ledger.records)
      || !Object.entries(ledger.records).every(([id,record])=>validateRecord(record,id))){
    throw new Error('invalid alert delivery ledger');
  }
  return ledger;
}

async function readLedger(file,observedAt){
  try{
    const stat=await fs.lstat(file);
    if(stat.isSymbolicLink() || !stat.isFile()) throw new Error('alert delivery ledger must be a regular file');
    return validateLedger(JSON.parse(await fs.readFile(file,'utf8')));
  }catch(error){
    if(error.code==='ENOENT') return emptyLedger(observedAt);
    throw error;
  }
}

function validatePolicy({maxAttempts,attemptTimeoutMs,retryBackoffMs,batchLimit}){
  if(!Number.isInteger(maxAttempts) || maxAttempts<1 || maxAttempts>3)
    throw new Error('maxAttempts must be an integer from 1 to 3');
  if(!Number.isInteger(attemptTimeoutMs) || attemptTimeoutMs<1 || attemptTimeoutMs>60000)
    throw new Error('attemptTimeoutMs must be an integer from 1 to 60000');
  if(!Number.isInteger(retryBackoffMs) || retryBackoffMs<0 || retryBackoffMs>5000)
    throw new Error('retryBackoffMs must be an integer from 0 to 5000');
  if(!Number.isInteger(batchLimit) || batchLimit<1 || batchLimit>20)
    throw new Error('batchLimit must be an integer from 1 to 20');
}

function safeNow(clock){
  const value=clock();
  if(!positiveInteger(value)) throw new Error('delivery clock must return a positive safe integer');
  return value;
}

function errorCode(error){
  if(error?.code==='ATTEMPT_TIMEOUT') return 'ATTEMPT_TIMEOUT';
  if(typeof error?.code==='string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(error.code)) return error.code;
  return 'DELIVERY_REJECTED';
}

async function withTimeout(operation,timeoutMs){
  let timer;
  const timeout=new Promise((_,reject)=>{
    timer=setTimeout(()=>reject(Object.assign(new Error('local sink timed out'),{code:'ATTEMPT_TIMEOUT'})),timeoutMs);
  });
  try{ return await Promise.race([Promise.resolve().then(operation),timeout]); }
  finally{ clearTimeout(timer); }
}

async function acquireLedgerLock(ledgerPath){
  const lockPath=`${ledgerPath}.lock`;
  const nonce=crypto.randomUUID();
  const helper=spawn('flock',['-n',lockPath,'cat'],{stdio:['pipe','pipe','pipe']});
  let ready=false,lost=null,stderr='',stdout='';
  const acquired=new Promise((resolve,reject)=>{
    helper.stderr.on('data',chunk=>{if(stderr.length<4096) stderr+=String(chunk).slice(0,4096-stderr.length);});
    helper.stdout.on('data',chunk=>{
      if(ready) return;
      stdout+=String(chunk);
      if(stdout.includes(`${nonce}\n`)){ready=true;resolve();}
    });
    helper.once('error',error=>reject(Object.assign(new Error(`alert consumer lock helper failed: ${error.message}`),
      {code:'ALERT_CONSUMER_LOCK_ERROR'})));
    helper.once('exit',(code,signal)=>{
      if(!ready){
        if(code===1) reject(Object.assign(new Error('alert consumer ledger is locked'),
          {code:'ALERT_CONSUMER_LOCKED'}));
        else reject(Object.assign(new Error(`alert consumer lock helper exited before acquisition: ${stderr||signal||code}`),
          {code:'ALERT_CONSUMER_LOCK_ERROR'}));
      }else{
        lost=Object.assign(new Error(`alert consumer ledger lock was lost: ${stderr||signal||code}`),
          {code:'ALERT_CONSUMER_LOCK_LOST'});
      }
    });
  });
  helper.stdin.on('error',()=>{});
  helper.stdin.write(`${nonce}\n`);
  await acquired;
  return {
    assertHeld(){
      if(lost || helper.exitCode!==null) throw lost??Object.assign(
        new Error('alert consumer ledger lock was lost'),{code:'ALERT_CONSUMER_LOCK_LOST'});
    },
    async release(){
      if(helper.exitCode!==null) throw lost;
      const exited=new Promise((resolve,reject)=>{
        helper.once('error',reject);
        helper.once('exit',(code,signal)=>code===0?resolve():reject(Object.assign(
          new Error(`alert consumer lock helper release failed: ${stderr||signal||code}`),
          {code:'ALERT_CONSUMER_LOCK_ERROR'})));
      });
      helper.stdin.end();
      await exited;
    }
  };
}

async function withLedgerLock(ledgerPath,operation){
  const lock=await acquireLedgerLock(ledgerPath);
  try{return await operation(lock.assertHeld);}
  finally{await lock.release();}
}

function newRecord(intent,digest){
  return {schema_version:LEDGER_SCHEMA,type:RECORD_TYPE,intent_id:intent.id,
    intent_sha256:digest,watch_id:intent.watch_id,alert_kind:intent.alert_kind,
    outage_started_at:intent.outage_started_at,delivery_status:'pending',delivery_attempts:0,
    acknowledged_at:null,dead_lettered_at:null,last_error_code:null,local_receipt_id:null,
    external_delivery_performed:false,publication_enabled:false,attempts:[]};
}

function validateAcknowledgement(value,intent){
  const keys=['acknowledged','intent_id','receipt_id'];
  return exactKeys(value,keys) && value.acknowledged===true && value.intent_id===intent.id
    && typeof value.receipt_id==='string' && /^[A-Za-z0-9._:-]{1,128}$/.test(value.receipt_id);
}

export async function runAlertConsumer({eventsPath='FREE_MONITOR_EVENTS.json',
  ledgerPath='FREE_MONITOR_ALERT_DELIVERY.json',mode='local-fail',maxAttempts=3,attemptTimeoutMs=5000,
  retryBackoffMs=250,batchLimit=20,clock=Date.now,sleepImpl=ms=>new Promise(resolve=>setTimeout(resolve,ms))}={}){
  validatePolicy({maxAttempts,attemptTimeoutMs,retryBackoffMs,batchLimit});
  const sink=localSinkForMode(mode);
  const source=JSON.parse(await fs.readFile(eventsPath,'utf8'));
  if(!Array.isArray(source)) throw new Error('monitor events must be an array');
  for(const event of source){
    if(event?.type==='alert_intent' && !isPendingAlertIntent(event))
      throw new Error('invalid alert intent in monitor events');
  }
  const intents=pendingAlertIntents(source);
  const sourceIds=new Set();
  for(const intent of intents){
    if(sourceIds.has(intent.id)) throw new Error('duplicate alert intent id in monitor events');
    sourceIds.add(intent.id);
  }
  return withLedgerLock(ledgerPath,async assertLockHeld=>{
  assertLockHeld();
  const initialAt=safeNow(clock);
  const ledger=await readLedger(ledgerPath,initialAt);
  const actionable=[];
  let actionableTotal=0;
  for(const intent of intents){
    const digest=alertIntentSha256(intent);
    const record=ledger.records[intent.id];
    if(record && record.intent_sha256!==digest) throw new Error('alert intent identity mismatch');
    if(record && TERMINAL_STATUSES.has(record.delivery_status)) continue;
    actionableTotal++;
    if(actionable.length<batchLimit) actionable.push({intent,digest,record});
  }
  let attemptedThisRun=0;
  for(const item of actionable){
    const {intent,digest}=item;
    let {record}=item;
    record??=newRecord(intent,digest);
    ledger.records[intent.id]=record;
    if(record.delivery_attempts>=maxAttempts){
      record.delivery_status='dead_letter';record.dead_lettered_at=safeNow(clock);
      ledger.observed_at=safeNow(clock);
      await writeJsonAtomic(ledgerPath,ledger);
      continue;
    }
    while(record.delivery_attempts<maxAttempts && record.delivery_status==='pending'){
      if(record.delivery_attempts>0) await sleepImpl(retryBackoffMs*record.delivery_attempts);
      assertLockHeld();
      const startedAt=safeNow(clock);
      try{
        const acknowledgement=await withTimeout(()=>sink({...intent}),attemptTimeoutMs);
        if(!validateAcknowledgement(acknowledgement,intent))
          throw Object.assign(new Error('local sink acknowledgement rejected'),{code:'ACKNOWLEDGEMENT_INVALID'});
        const completedAt=safeNow(clock);
        record.delivery_attempts++;
        record.attempts.push({attempt:record.delivery_attempts,started_at:startedAt,
          completed_at:completedAt,outcome:'acknowledged',error_code:null});
        record.delivery_status='acknowledged';record.acknowledged_at=completedAt;
        record.dead_lettered_at=null;record.last_error_code=null;
        record.local_receipt_id=acknowledgement.receipt_id;
      }catch(error){
        const completedAt=safeNow(clock);
        const code=errorCode(error);
        record.delivery_attempts++;
        record.attempts.push({attempt:record.delivery_attempts,started_at:startedAt,
          completed_at:completedAt,outcome:'error',error_code:code});
        record.last_error_code=code;
        if(record.delivery_attempts>=maxAttempts){
          record.delivery_status='dead_letter';record.dead_lettered_at=completedAt;
        }
      }
      attemptedThisRun++;
      ledger.observed_at=safeNow(clock);
      assertLockHeld();
      await writeJsonAtomic(ledgerPath,ledger);
      assertLockHeld();
    }
  }
  validateLedger(ledger);
  const records=Object.values(ledger.records);
  return {schema_version:1,type:'monitor_alert_consumer_report',observed_at:ledger.observed_at,
    source_alert_intents:intents.length,selected_alert_intents:actionable.length,
    unprocessed_source_intents:Math.max(0,actionableTotal-actionable.length),attempted_this_run:attemptedThisRun,
    acknowledged_total:records.filter(record=>record.delivery_status==='acknowledged').length,
    dead_letter_total:records.filter(record=>record.delivery_status==='dead_letter').length,
    pending_total:records.filter(record=>record.delivery_status==='pending').length,
    max_attempts:maxAttempts,attempt_timeout_ms:attemptTimeoutMs,retry_backoff_ms:retryBackoffMs,
    batch_limit:batchLimit,source_outbox_mutated:false,external_delivery_performed:false,
    publication_enabled:false};
  });
}

export function localSinkForMode(mode){
  if(mode==='local-ack') return async intent=>({acknowledged:true,intent_id:intent.id,
    receipt_id:`local:${intent.id}`});
  if(mode==='local-fail-once'){
    let failed=false;
    return async intent=>{
      if(!failed){failed=true;throw Object.assign(new Error('local transient rejection'),
        {code:'LOCAL_TRANSIENT'});}
      return {acknowledged:true,intent_id:intent.id,receipt_id:`local:${intent.id}`};
    };
  }
  if(mode==='local-fail') return async()=>{ throw Object.assign(new Error('local sink rejected'),
    {code:'LOCAL_SINK_REJECTED'}); };
  throw new Error('local sink mode must be local-ack, local-fail-once or local-fail');
}

function isMainEntry(importMetaUrl,argv1){
  return argv1 && path.resolve(fileURLToPath(importMetaUrl))===path.resolve(argv1);
}

if(isMainEntry(import.meta.url,process.argv[1])){
  const [eventsPath='FREE_MONITOR_EVENTS.json',ledgerPath='FREE_MONITOR_ALERT_DELIVERY.json',
    mode='local-fail']=process.argv.slice(2);
  runAlertConsumer({eventsPath,ledgerPath,mode}).then(report=>{
    process.stdout.write(JSON.stringify(report,null,2)+'\n');
    if(report.dead_letter_total>0) process.exitCode=2;
  }).catch(error=>{ process.stderr.write(String(error)+'\n');process.exitCode=1; });
}
