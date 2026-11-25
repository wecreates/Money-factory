import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {constants as fsConstants} from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {isDeepStrictEqual} from 'node:util';
import {writeJsonAtomic,writeSerializedExclusive} from './persistence.mjs';
import {alertIntentKey,isPendingAlertIntent,MONITOR_EVENT_LIMIT,pendingAlertIntents} from './alert-intents.mjs';

const LEDGER_SCHEMA=1;
const LEDGER_TYPE='monitor_alert_delivery_ledger';
const RECORD_TYPE='monitor_alert_delivery';
const TERMINAL_STATUSES=new Set(['acknowledged','dead_letter']);
export const LOCAL_ALERT_ARCHIVE_KEY='_monitor_local_alert_archive';
export const MAX_LOCAL_ALERT_ARCHIVE_RECORDS=500;
export const LOCAL_ALERT_ARCHIVE_ROLLOVER_RECORDS=250;
export const MAX_LOCAL_ALERT_ARCHIVE_GENERATIONS=16;
export const MAX_LOCAL_ALERT_LEDGER_RECORDS=MAX_LOCAL_ALERT_ARCHIVE_RECORDS+MONITOR_EVENT_LIMIT;
export const MAX_LOCAL_ALERT_LEDGER_BYTES=8*1024*1024;
export const MAX_LOCAL_ALERT_SOURCE_BYTES=8*1024*1024;

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
      || !nonnegativeInteger(record.delivery_attempts) || record.delivery_attempts>3
      || !Array.isArray(record.attempts) || record.attempts.length!==record.delivery_attempts
      || !record.attempts.every(validateAttempt)
      || record.attempts.slice(0,-1).some(attempt=>attempt.outcome!=='error')
      || record.external_delivery_performed!==false || record.publication_enabled!==false){
    return false;
  }
  const finalAttempt=record.attempts.at(-1);
  if(record.delivery_status==='pending'){
    return record.acknowledged_at===null && record.dead_lettered_at===null
      && record.local_receipt_id===null
      && (record.delivery_attempts===0
        ? record.last_error_code===null
        : finalAttempt?.outcome==='error' && record.last_error_code===finalAttempt.error_code);
  }
  if(record.delivery_status==='acknowledged'){
    return positiveInteger(record.acknowledged_at) && record.dead_lettered_at===null
      && record.last_error_code===null && typeof record.local_receipt_id==='string'
      && /^[A-Za-z0-9._:-]{1,128}$/.test(record.local_receipt_id)
      && finalAttempt?.outcome==='acknowledged' && record.acknowledged_at===finalAttempt.completed_at;
  }
  return record.acknowledged_at===null && positiveInteger(record.dead_lettered_at)
    && record.local_receipt_id===null && finalAttempt?.outcome==='error'
    && record.dead_lettered_at>=finalAttempt.completed_at && record.last_error_code===finalAttempt.error_code;
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
      || typeof ledger.records!=='object' || Array.isArray(ledger.records)){
    throw new Error('invalid alert delivery ledger');
  }
  const ids=Object.keys(ledger.records);
  if(ids.length>MAX_LOCAL_ALERT_LEDGER_RECORDS) throw new Error('alert delivery ledger exceeds record limit');
  if(!ids.every(id=>validateRecord(ledger.records[id],id))) throw new Error('invalid alert delivery ledger');
  return ledger;
}

async function readBoundedBytes(file,{label,byteLimit,optional=false}){
  if(!fsConstants.O_NOFOLLOW || !fsConstants.O_NONBLOCK){
    throw new Error('bounded alert reads require no-follow and nonblocking file flags');
  }
  let handle;
  try{
    handle=await fs.open(file,fsConstants.O_RDONLY|fsConstants.O_NOFOLLOW|fsConstants.O_NONBLOCK);
  }catch(error){
    if(error.code==='ENOENT' && optional) return undefined;
    if(error.code==='ELOOP') throw new Error(`${label} must be a regular file`);
    throw error;
  }
  try{
    const opened=await handle.stat({bigint:true});
    if(!opened.isFile()) throw new Error(`${label} must be a regular file`);
    if(opened.size>BigInt(byteLimit)) throw new Error(`${label} exceeds byte limit`);
    // Read at most the observed size plus one byte from the opened inode. The
    // extra byte detects file growth without an unbounded path-based read.
    const bytes=Buffer.alloc(Number(opened.size)+1);
    let offset=0;
    while(offset<bytes.length){
      const {bytesRead}=await handle.read(bytes,offset,bytes.length-offset,offset);
      if(!bytesRead) break;
      offset+=bytesRead;
    }
    const final=await handle.stat({bigint:true});
    if(offset!==Number(opened.size) || final.size!==opened.size
        || final.dev!==opened.dev || final.ino!==opened.ino
        || final.mtimeNs!==opened.mtimeNs || final.ctimeNs!==opened.ctimeNs){
      throw new Error(`${label} changed while being read`);
    }
    return bytes.subarray(0,offset);
  }finally{
    await handle.close();
  }
}

async function readBoundedJson(file,options){
  const bytes=await readBoundedBytes(file,options);
  return bytes===undefined?undefined:JSON.parse(bytes.toString('utf8'));
}

async function readLedger(file,observedAt,{required=false}={}){
  const ledger=await readBoundedJson(file,{label:'alert delivery ledger',
    byteLimit:MAX_LOCAL_ALERT_LEDGER_BYTES,optional:!required});
  return ledger===undefined && !required?emptyLedger(observedAt):validateLedger(ledger);
}

async function writeLedger(file,ledger){
  validateLedger(ledger);
  if(Buffer.byteLength(JSON.stringify(ledger,null,2))+1>MAX_LOCAL_ALERT_LEDGER_BYTES){
    throw new Error('alert delivery ledger exceeds byte limit');
  }
  await writeJsonAtomic(file,ledger);
}

function recordMatchesIntent(record,intent){
  return record.intent_sha256===alertIntentSha256(intent) && record.watch_id===intent.watch_id
    && record.alert_kind===intent.alert_kind && record.outage_started_at===intent.outage_started_at;
}

function isLocalTerminalRecord(record,intent){
  return TERMINAL_STATUSES.has(record.delivery_status)
    && (record.delivery_status!=='acknowledged' || record.local_receipt_id===`local:${intent.id}`);
}

function archiveIntentKey(intent){
  return alertIntentKey(intent.watch_id,intent.target_url,intent.alert_kind,intent.outage_started_at);
}

function validateGenerationMetadata(metadata,index){
  return exactKeys(metadata,['sequence','sha256','record_count'])
    && metadata.sequence===index+1 && typeof metadata.sha256==='string'
    && /^[0-9a-f]{64}$/.test(metadata.sha256)
    && Number.isSafeInteger(metadata.record_count) && metadata.record_count>0
    && metadata.record_count<=LOCAL_ALERT_ARCHIVE_ROLLOVER_RECORDS;
}

function validateArchiveShape(archive){
  const legacy=exactKeys(archive,['schema_version','type','records']) && archive.schema_version===1;
  const current=exactKeys(archive,['schema_version','type','records','generations'])
    && archive.schema_version===2 && Array.isArray(archive.generations)
    && archive.generations.length<=MAX_LOCAL_ALERT_ARCHIVE_GENERATIONS
    && archive.generations.every(validateGenerationMetadata);
  if((!legacy && !current) || archive.type!=='monitor_local_alert_archive'
    || !Array.isArray(archive.records) || archive.records.length>MAX_LOCAL_ALERT_ARCHIVE_RECORDS){
    throw new Error('invalid local alert archive');
  }
  return current?archive.generations:[];
}

function indexArchiveRecords(records,indexed,keys){
  for(const entry of records){
    if(!exactKeys(entry,['intent','local_delivery']) || !isPendingAlertIntent(entry.intent)
      || !validateRecord(entry.local_delivery,entry.intent.id)
      || !isLocalTerminalRecord(entry.local_delivery,entry.intent)
      || !recordMatchesIntent(entry.local_delivery,entry.intent)
      || indexed.has(entry.intent.id) || keys.has(archiveIntentKey(entry.intent))){
      throw new Error('invalid or duplicate local alert archive record');
    }
    indexed.set(entry.intent.id,entry);
    keys.add(archiveIntentKey(entry.intent));
  }
}

function generationFile(ledgerPath,metadata){
  const absolute=path.resolve(ledgerPath);
  return path.join(path.dirname(absolute),
    `${path.basename(absolute)}.archive-${String(metadata.sequence).padStart(4,'0')}-${metadata.sha256}.json`);
}

function serializeGeneration(sequence,previousSha256,records){
  return JSON.stringify({schema_version:1,type:'monitor_local_alert_archive_generation',sequence,
    previous_sha256:previousSha256,records},null,2)+'\n';
}

async function readGeneration(ledgerPath,metadata,previousSha256){
  const file=generationFile(ledgerPath,metadata);
  const bytes=await readBoundedBytes(file,{label:'local alert archive generation',
    byteLimit:MAX_LOCAL_ALERT_LEDGER_BYTES});
  if(crypto.createHash('sha256').update(bytes).digest('hex')!==metadata.sha256){
    throw new Error('local alert archive generation digest mismatch');
  }
  const generation=JSON.parse(bytes.toString('utf8'));
  if(!exactKeys(generation,['schema_version','type','sequence','previous_sha256','records'])
    || generation.schema_version!==1 || generation.type!=='monitor_local_alert_archive_generation'
    || generation.sequence!==metadata.sequence || generation.previous_sha256!==previousSha256
    || !Array.isArray(generation.records) || generation.records.length!==metadata.record_count){
    throw new Error('invalid local alert archive generation');
  }
  return generation.records;
}

async function loadArchive(archive,ledgerPath){
  const generations=validateArchiveShape(archive);
  const indexed=new Map();
  const keys=new Set();
  const generationRecords=new Map();
  let previousSha256=null;
  for(const metadata of generations){
    if(ledgerPath===undefined) throw new Error('local alert archive generations require a ledger path');
    const records=await readGeneration(ledgerPath,metadata,previousSha256);
    indexArchiveRecords(records,indexed,keys);
    for(const entry of records) generationRecords.set(entry.intent.id,entry.local_delivery);
    previousSha256=metadata.sha256;
  }
  indexArchiveRecords(archive.records,indexed,keys);
  return {indexed,keys,generations,generationRecords};
}

async function readLedgerRetiringGenerations(ledgerPath,generationRecords){
  if(ledgerPath===undefined) return {ledger:null,retired:0};
  if(generationRecords.size===0){
    return {ledger:await readLedger(ledgerPath,Date.now(),{required:true}),retired:0};
  }
  return withLedgerLock(ledgerPath,async assertLockHeld=>{
    assertLockHeld();
    const ledger=await readLedger(ledgerPath,Date.now(),{required:true});
    let retired=0;
    for(const [id,archivedRecord] of generationRecords){
      if(!Object.hasOwn(ledger.records,id)) continue;
      if(!isDeepStrictEqual(ledger.records[id],archivedRecord)){
        throw new Error('archive generation and alert delivery ledger disagree');
      }
      delete ledger.records[id];
      retired++;
    }
    if(retired){
      ledger.observed_at=Date.now();
      assertLockHeld();
      await writeLedger(ledgerPath,ledger);
      assertLockHeld();
    }
    return {ledger,retired};
  });
}

async function ensureGeneration(ledgerPath,sequence,previousSha256,records){
  const serialized=serializeGeneration(sequence,previousSha256,records);
  if(Buffer.byteLength(serialized)>MAX_LOCAL_ALERT_LEDGER_BYTES){
    throw new Error('local alert archive generation exceeds byte limit');
  }
  const sha256=crypto.createHash('sha256').update(serialized).digest('hex');
  const metadata={sequence,sha256,record_count:records.length};
  const file=generationFile(ledgerPath,metadata);
  return withLedgerLock(ledgerPath,async assertLockHeld=>{
    assertLockHeld();
    let recovered=false;
    try{
      await writeSerializedExclusive(file,serialized);
    }catch(error){
      if(error.code!=='EEXIST') throw error;
      const existing=await readBoundedBytes(file,{label:'local alert archive generation',
        byteLimit:MAX_LOCAL_ALERT_LEDGER_BYTES});
      if(!existing.equals(Buffer.from(serialized))) throw new Error('conflicting local alert archive generation');
      recovered=true;
    }
    assertLockHeld();
    return {metadata,recovered};
  });
}

// This computes a new pair image. Only the worker's existing serial journaled
// writer may persist it. The ledger is read once from an atomic snapshot.
export async function reconcileLocalAlertOutbox(events,priorArchive,ledgerPath){
  const archive=priorArchive??{schema_version:1,type:'monitor_local_alert_archive',records:[]};
  const {indexed,keys,generations,generationRecords}=await loadArchive(archive,ledgerPath);
  const {ledger,retired:retiredLedgerRecords}=await readLedgerRetiringGenerations(
    ledgerPath,generationRecords);
  const sourceIds=new Set();
  const sourceKeyCounts=new Map();
  for(const event of events){
    if(event.type!=='alert_intent') continue;
    if(!isPendingAlertIntent(event)) throw new Error('invalid alert intent in monitor events');
    if(sourceIds.has(event.id)) throw new Error('duplicate alert intent id in monitor events');
    sourceIds.add(event.id);
    const key=archiveIntentKey(event);
    sourceKeyCounts.set(key,(sourceKeyCounts.get(key)??0)+1);
  }
  const retained=[];
  let records=[...archive.records];
  let nextGenerations=[...generations];
  let compacted=0;
  let deferred=0;
  let rolledOver=0;
  let recoveredRollover=0;
  const terminalCandidate=events.some(event=>event.type==='alert_intent'
    && !indexed.has(event.id) && !keys.has(archiveIntentKey(event))
    && sourceKeyCounts.get(archiveIntentKey(event))===1
    && ledger && TERMINAL_STATUSES.has(ledger.records[event.id]?.delivery_status));
  if(terminalCandidate && records.length===MAX_LOCAL_ALERT_ARCHIVE_RECORDS
    && nextGenerations.length<MAX_LOCAL_ALERT_ARCHIVE_GENERATIONS){
    const retiring=records.slice(0,LOCAL_ALERT_ARCHIVE_ROLLOVER_RECORDS);
    const sequence=nextGenerations.length+1;
    const previousSha256=nextGenerations.at(-1)?.sha256??null;
    const rollover=await ensureGeneration(ledgerPath,sequence,previousSha256,retiring);
    nextGenerations.push(rollover.metadata);
    records=records.slice(LOCAL_ALERT_ARCHIVE_ROLLOVER_RECORDS);
    rolledOver=retiring.length;
    recoveredRollover=Number(rollover.recovered);
  }
  for(const event of events){
    if(event.type!=='alert_intent'){retained.push(event);continue;}
    const key=archiveIntentKey(event);
    const archived=indexed.get(event.id);
    const record=ledger && Object.hasOwn(ledger.records,event.id)?ledger.records[event.id]:null;
    if(record && !recordMatchesIntent(record,event)) throw new Error('alert intent identity mismatch');
    if(archived){
      if(!recordMatchesIntent(archived.local_delivery,event)) throw new Error('archived alert intent identity mismatch');
      compacted++;
      continue;
    }
    if(keys.has(key)) throw new Error('conflicting alert intent for archived outage or recovery');
    if(record && TERMINAL_STATUSES.has(record.delivery_status)){
      if(!isLocalTerminalRecord(record,event)) throw new Error('invalid local terminal alert record');
      if(records.length<MAX_LOCAL_ALERT_ARCHIVE_RECORDS && sourceKeyCounts.get(key)===1){
        const entry={intent:event,local_delivery:record};
        records.push(entry);
        indexed.set(event.id,entry);
        keys.add(key);
        compacted++;
        continue;
      }
      deferred++;
    }
    retained.push(event);
  }
  const nextArchive=nextGenerations.length
    ? {schema_version:2,type:'monitor_local_alert_archive',records,generations:nextGenerations}
    : {...archive,records};
  const report={
    compacted_this_run:compacted,terminal_reconciliation_deferred:deferred,
    archived_acknowledged:[...indexed.values()]
      .filter(entry=>entry.local_delivery.delivery_status==='acknowledged').length,
    archived_dead_letter:[...indexed.values()]
      .filter(entry=>entry.local_delivery.delivery_status==='dead_letter').length,
    archive_limit:MAX_LOCAL_ALERT_ARCHIVE_RECORDS,
    external_delivery_performed:false,publication_enabled:false};
  if(rolledOver || nextGenerations.length){
    Object.assign(report,{rolled_over_this_run:rolledOver,archive_generations:nextGenerations.length,
      recovered_rollover_generation:recoveredRollover,
      ledger_records_retired_this_run:retiredLedgerRecords});
  }
  return {events:retained,archive:nextArchive,keys,report};
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
  const source=await readBoundedJson(eventsPath,{label:'monitor events',byteLimit:MAX_LOCAL_ALERT_SOURCE_BYTES});
  if(!Array.isArray(source)) throw new Error('monitor events must be an array');
  if(source.length>MONITOR_EVENT_LIMIT) throw new Error('monitor events exceeds record limit');
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
  const newRecords=actionable.filter(item=>!item.record).length;
  if(Object.keys(ledger.records).length+newRecords>MAX_LOCAL_ALERT_LEDGER_RECORDS){
    throw new Error('alert delivery ledger exceeds record limit');
  }
  let attemptedThisRun=0;
  for(const item of actionable){
    const {intent,digest}=item;
    let {record}=item;
    record??=newRecord(intent,digest);
    ledger.records[intent.id]=record;
    if(record.delivery_attempts>=maxAttempts){
      record.delivery_status='dead_letter';
      record.dead_lettered_at=Math.max(safeNow(clock),record.attempts.at(-1).completed_at);
      ledger.observed_at=safeNow(clock);
      assertLockHeld();
      await writeLedger(ledgerPath,ledger);
      assertLockHeld();
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
      await writeLedger(ledgerPath,ledger);
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
