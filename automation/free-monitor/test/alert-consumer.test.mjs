import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {alertIntentSha256,runAlertConsumer,MAX_LOCAL_ALERT_SOURCE_BYTES} from '../alert-consumer.mjs';

function intent(patch={}){
  const outage=patch.outage_started_at??10_000;
  return {id:patch.id??crypto.randomUUID(),watch_id:'fixture',at:patch.at??outage,
    type:'alert_intent',alert_kind:patch.alert_kind??'outage',outage_started_at:outage,
    label:'Fixture',target_url:'https://fixture.invalid/',delivery_status:'pending',
    delivery_attempts:0,external_delivery_performed:false,publication_enabled:false,...patch};
}

async function fixture(t,events=[intent()]){
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-alert-consumer-'));
  t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const eventsPath=path.join(dir,'events.json'),ledgerPath=path.join(dir,'ledger.json');
  await fs.writeFile(eventsPath,JSON.stringify(events));
  let now=20_000;
  return {eventsPath,ledgerPath,clock:()=>now++,events};
}

test('local acknowledgement is durable, source-bound and idempotent',async t=>{
  const f=await fixture(t);
  const first=await runAlertConsumer({...f,mode:'local-ack',retryBackoffMs:0});
  assert.deepEqual({attempted:first.attempted_this_run,ack:first.acknowledged_total,dead:first.dead_letter_total},
    {attempted:1,ack:1,dead:0});
  assert.equal(first.source_outbox_mutated,false);
  const ledger=JSON.parse(await fs.readFile(f.ledgerPath,'utf8'));
  const record=ledger.records[f.events[0].id];
  assert.equal(record.intent_sha256,alertIntentSha256(f.events[0]));
  assert.equal(record.delivery_status,'acknowledged');assert.equal(record.delivery_attempts,1);
  assert.equal(record.external_delivery_performed,false);assert.equal(record.publication_enabled,false);
  const replay=await runAlertConsumer({...f,mode:'local-ack',retryBackoffMs:0});
  assert.equal(replay.attempted_this_run,0);
});

test('transient local rejection retries unchanged intent then acknowledges',async t=>{
  const f=await fixture(t);const waits=[];
  const report=await runAlertConsumer({...f,mode:'local-fail-once',retryBackoffMs:7,
    sleepImpl:async ms=>waits.push(ms)});
  assert.equal(report.acknowledged_total,1);assert.equal(report.attempted_this_run,2);
  assert.deepEqual(waits,[7]);
  const record=JSON.parse(await fs.readFile(f.ledgerPath,'utf8')).records[f.events[0].id];
  assert.deepEqual(record.attempts.map(attempt=>[attempt.outcome,attempt.error_code]),
    [['error','LOCAL_TRANSIENT'],['acknowledged',null]]);
});

test('exhausted bounded retries retain a terminal dead letter',async t=>{
  const f=await fixture(t);const waits=[];
  const report=await runAlertConsumer({...f,mode:'local-fail',maxAttempts:3,retryBackoffMs:5,
    sleepImpl:async ms=>waits.push(ms)});
  assert.equal(report.dead_letter_total,1);assert.equal(report.attempted_this_run,3);
  assert.deepEqual(waits,[5,10]);
  const record=JSON.parse(await fs.readFile(f.ledgerPath,'utf8')).records[f.events[0].id];
  assert.equal(record.delivery_status,'dead_letter');assert.equal(record.delivery_attempts,3);
  assert.equal(record.last_error_code,'LOCAL_SINK_REJECTED');assert.ok(record.dead_lettered_at);
  const replay=await runAlertConsumer({...f,mode:'local-fail',maxAttempts:3,retryBackoffMs:0});
  assert.equal(replay.attempted_this_run,0);
});

test('interrupted retry resumes or terminalizes without an immortal pending record',async t=>{
  const f=await fixture(t);
  await assert.rejects(runAlertConsumer({...f,mode:'local-fail',maxAttempts:3,retryBackoffMs:1,
    sleepImpl:async()=>{throw new Error('fixture interruption');}}),/fixture interruption/);
  let record=JSON.parse(await fs.readFile(f.ledgerPath,'utf8')).records[f.events[0].id];
  assert.equal(record.delivery_status,'pending');assert.equal(record.delivery_attempts,1);
  const report=await runAlertConsumer({...f,mode:'local-fail',maxAttempts:1,retryBackoffMs:0});
  record=JSON.parse(await fs.readFile(f.ledgerPath,'utf8')).records[f.events[0].id];
  assert.equal(report.attempted_this_run,0);assert.equal(report.dead_letter_total,1);
  assert.equal(record.delivery_status,'dead_letter');assert.equal(record.delivery_attempts,1);
  assert.equal(record.last_error_code,'LOCAL_SINK_REJECTED');
});

test('same event id with changed signed content fails closed before delivery',async t=>{
  const f=await fixture(t);
  await runAlertConsumer({...f,mode:'local-ack',retryBackoffMs:0});
  await fs.writeFile(f.eventsPath,JSON.stringify([{...f.events[0],label:'Changed'}]));
  await assert.rejects(runAlertConsumer({...f,mode:'local-ack',retryBackoffMs:0}),/identity mismatch/);
});

test('duplicate source IDs fail closed before ledger creation',async t=>{
  const first=intent();
  const f=await fixture(t,[first,{...first,label:'Conflicting duplicate'}]);
  await assert.rejects(runAlertConsumer({...f,mode:'local-ack'}),/duplicate alert intent id/);
  await assert.rejects(fs.stat(f.ledgerPath),{code:'ENOENT'});
  await assert.rejects(fs.stat(`${f.ledgerPath}.lock`),{code:'ENOENT'});
});

test('live concurrency rejects, SIGKILL releases the kernel lock, and restart resumes',async t=>{
  const f=await fixture(t);
  const moduleUrl=new URL('../alert-consumer.mjs',import.meta.url).href;
  const script=`import {runAlertConsumer} from ${JSON.stringify(moduleUrl)};
    await runAlertConsumer({eventsPath:${JSON.stringify(f.eventsPath)},ledgerPath:${JSON.stringify(f.ledgerPath)},
      mode:'local-fail',maxAttempts:3,retryBackoffMs:5000});`;
  const child=spawn(process.execPath,['--input-type=module','--eval',script],{stdio:['ignore','pipe','pipe']});
  let childStderr='';child.stderr.on('data',chunk=>{childStderr+=String(chunk);});
  t.after(()=>{if(child.exitCode===null) child.kill('SIGKILL');});
  let retained;
  for(let attempt=0;attempt<100;attempt++){
    try{
      retained=JSON.parse(await fs.readFile(f.ledgerPath,'utf8'));
      if(retained.records[f.events[0].id]?.delivery_attempts===1) break;
    }catch(error){if(error.code!=='ENOENT') throw error;}
    await new Promise(resolve=>setTimeout(resolve,20));
  }
  assert.equal(retained?.records[f.events[0].id]?.delivery_attempts,1,childStderr);
  await assert.rejects(runAlertConsumer({eventsPath:f.eventsPath,ledgerPath:f.ledgerPath,
    mode:'local-ack',retryBackoffMs:0}),error=>
    error.code==='ALERT_CONSUMER_LOCKED');
  child.kill('SIGKILL');
  await new Promise((resolve,reject)=>{
    child.once('exit',resolve);child.once('error',reject);
  });
  let report;
  for(let attempt=0;attempt<100;attempt++){
    try{
      report=await runAlertConsumer({eventsPath:f.eventsPath,ledgerPath:f.ledgerPath,
        mode:'local-ack',retryBackoffMs:0});
      break;
    }catch(error){
      if(error.code!=='ALERT_CONSUMER_LOCKED') throw error;
      await new Promise(resolve=>setTimeout(resolve,20));
    }
  }
  assert.equal(report?.acknowledged_total,1);
  const recovered=JSON.parse(await fs.readFile(f.ledgerPath,'utf8')).records[f.events[0].id];
  assert.equal(recovered.delivery_status,'acknowledged');
  assert.equal(recovered.delivery_attempts,2);
});

test('invalid alert intent and unsafe policy fail before ledger creation',async t=>{
  const malformed=intent({delivery_status:'delivered',external_delivery_performed:true});
  const f=await fixture(t,[malformed]);
  await assert.rejects(runAlertConsumer({...f,mode:'local-ack'}),/invalid alert intent/);
  await assert.rejects(runAlertConsumer({...f,mode:'local-ack',maxAttempts:4}),/maxAttempts/);
  await assert.rejects(fs.stat(f.ledgerPath),{code:'ENOENT'});
});

test('batch ceiling advances past terminal records without starving later intents',async t=>{
  const events=[intent(),intent({outage_started_at:11_000,at:11_001,alert_kind:'recovery'})];
  const f=await fixture(t,events);
  const report=await runAlertConsumer({...f,mode:'local-ack',batchLimit:1,retryBackoffMs:0});
  assert.deepEqual({source:report.source_alert_intents,selected:report.selected_alert_intents,
    unprocessed:report.unprocessed_source_intents},{source:2,selected:1,unprocessed:1});
  const ledger=JSON.parse(await fs.readFile(f.ledgerPath,'utf8'));
  assert.deepEqual(Object.keys(ledger.records),[events[0].id]);
  const second=await runAlertConsumer({...f,mode:'local-ack',batchLimit:1,retryBackoffMs:0});
  assert.deepEqual({source:second.source_alert_intents,selected:second.selected_alert_intents,
    unprocessed:second.unprocessed_source_intents},{source:2,selected:1,unprocessed:0});
  const complete=JSON.parse(await fs.readFile(f.ledgerPath,'utf8'));
  assert.deepEqual(Object.keys(complete.records),events.map(event=>event.id));
  const terminalReplay=await runAlertConsumer({...f,mode:'local-ack',batchLimit:1,retryBackoffMs:0});
  assert.deepEqual({selected:terminalReplay.selected_alert_intents,
    unprocessed:terminalReplay.unprocessed_source_intents},{selected:0,unprocessed:0});
});


test('oversized event source fails before ledger lock or delivery',async t=>{
  const f=await fixture(t);
  const handle=await fs.open(f.eventsPath,'w');
  await handle.truncate(MAX_LOCAL_ALERT_SOURCE_BYTES+1);await handle.close();
  await assert.rejects(runAlertConsumer({...f,mode:'local-ack'}),/monitor events exceeds byte limit/);
  await assert.rejects(fs.stat(f.ledgerPath),{code:'ENOENT'});
  await assert.rejects(fs.stat(`${f.ledgerPath}.lock`),{code:'ENOENT'});
});

test('event count ceiling applies before batching, including unrelated events',async t=>{
  const f=await fixture(t,Array.from({length:501},()=>({type:'fixture'})));
  await assert.rejects(runAlertConsumer({...f,mode:'local-ack',batchLimit:1}),/monitor events exceeds record limit/);
  await assert.rejects(fs.stat(`${f.ledgerPath}.lock`),{code:'ENOENT'});
  await fs.writeFile(f.eventsPath,JSON.stringify(Array.from({length:500},()=>({type:'fixture'}))));
  const result=await runAlertConsumer({...f,mode:'local-ack'});
  assert.equal(result.attempted_this_run,0);
});

test('source symlinks and named pipes reject before ledger creation',async t=>{
  const f=await fixture(t);
  const original=`${f.eventsPath}.regular`;await fs.rename(f.eventsPath,original);
  await fs.symlink(original,f.eventsPath);
  await assert.rejects(runAlertConsumer({...f,mode:'local-ack'}),/monitor events must be a regular file/);
  await fs.unlink(f.eventsPath);
  const child=spawn('mkfifo',[f.eventsPath]);
  const code=await new Promise((resolve,reject)=>{child.on('exit',resolve);child.on('error',reject);});
  assert.equal(code,0);
  await assert.rejects(runAlertConsumer({...f,mode:'local-ack'}),/monitor events must be a regular file/);
  await assert.rejects(fs.stat(`${f.ledgerPath}.lock`),{code:'ENOENT'});
});

test('JSON null ledger still rejects rather than becoming a missing ledger',async t=>{
  const f=await fixture(t);await fs.writeFile(f.ledgerPath,'null');
  await assert.rejects(runAlertConsumer({...f,mode:'local-ack'}),/invalid alert delivery ledger/);
  assert.equal(await fs.readFile(f.ledgerPath,'utf8'),'null');
});
