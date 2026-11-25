import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {randomUUID} from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {alertIntentSha256,LOCAL_ALERT_ARCHIVE_KEY,MAX_LOCAL_ALERT_ARCHIVE_RECORDS,
  MAX_LOCAL_ALERT_LEDGER_BYTES,MAX_LOCAL_ALERT_LEDGER_RECORDS,runAlertConsumer} from '../alert-consumer.mjs';
import {pendingAlertIntents,runWorker} from '../worker.mjs';

const watch={id:'example',label:'Example',targetUrl:'https://fixture.invalid/'};
const read=async file=>JSON.parse(await fs.readFile(file,'utf8'));
const write=(file,value)=>fs.writeFile(file,JSON.stringify(value));

async function fixture(t){
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-alert-compaction-'));
  t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const options={watchesPath:path.join(dir,'FREE_MONITOR_WATCHES.json'),statePath:path.join(dir,'FREE_MONITOR_STATE.json'),
    eventsPath:path.join(dir,'FREE_MONITOR_EVENTS.json'),intervalMs:0,maxAttempts:1};
  const ledgerPath=path.join(dir,'delivery.json');
  await write(options.watchesPath,[watch]);
  return {options,ledgerPath};
}

function localConsume({options,ledgerPath},extra){
  return runAlertConsumer({eventsPath:options.eventsPath,ledgerPath,mode:'local-ack',retryBackoffMs:0,...extra});
}

function distinctIntent(template,index){
  const outage=1_000_000+index;
  return {...template,id:randomUUID(),watch_id:`rollover-${index}`,at:outage,
    outage_started_at:outage,label:`Rollover ${index}`,
    target_url:`https://fixture.invalid/rollover/${index}`};
}

function terminalEntry(templateRecord,intent){
  return {intent,local_delivery:{...structuredClone(templateRecord),intent_id:intent.id,
    intent_sha256:alertIntentSha256(intent),watch_id:intent.watch_id,
    alert_kind:intent.alert_kind,outage_started_at:intent.outage_started_at,
    local_receipt_id:`local:${intent.id}`}};
}

async function addTerminalBatch(options,ledgerPath,templateIntent,templateRecord,count,start){
  const entries=Array.from({length:count},(_,offset)=>
    terminalEntry(templateRecord,distinctIntent(templateIntent,start+offset)));
  const ledger=await read(ledgerPath);
  for(const entry of entries) ledger.records[entry.intent.id]=entry.local_delivery;
  ledger.observed_at=Date.now();
  await Promise.all([write(options.eventsPath,entries.map(entry=>entry.intent)),write(ledgerPath,ledger)]);
  return entries;
}

test('terminal receipts compact locally while preserving pending recovery and dedup after restart',async t=>{
  const f=await fixture(t);
  const {options,ledgerPath}=f;
  let healthy=false;
  t.mock.method(globalThis,'fetch',async()=>{
    if(!healthy) throw new TypeError('fixture unreachable');
    return new Response('healthy');
  });
  await runWorker(options);
  const [original]=pendingAlertIntents(await read(options.eventsPath));
  await localConsume(f);
  const compacted=await runWorker({...options,localAlertLedgerPath:ledgerPath});
  assert.equal(compacted.ok,false);
  assert.equal(compacted.alert_outbox_pending,0);
  assert.deepEqual(compacted.local_alert_archive,{compacted_this_run:1,terminal_reconciliation_deferred:0,
    archived_acknowledged:1,archived_dead_letter:0,archive_limit:MAX_LOCAL_ALERT_ARCHIVE_RECORDS,
    external_delivery_performed:false,publication_enabled:false});
  const archived=(await read(options.statePath))[LOCAL_ALERT_ARCHIVE_KEY].records;
  assert.deepEqual(archived,[{intent:original,local_delivery:(await read(ledgerPath)).records[original.id]}]);
  assert.equal((await runWorker(options)).alert_outbox_pending,0);
  assert.equal((await localConsume(f)).attempted_this_run,0);

  healthy=true;
  const recovered=await runWorker(options);
  assert.equal(recovered.alert_outbox_pending,1);
  const [recovery]=pendingAlertIntents(await read(options.eventsPath));
  assert.equal(recovery.alert_kind,'recovery');
  assert.equal(recovery.outage_started_at,original.outage_started_at);
  assert.notEqual(recovery.id,original.id);
  await assert.rejects(localConsume(f,{mode:'local-fail',maxAttempts:3,retryBackoffMs:1,
    sleepImpl:async()=>{throw new Error('interrupted retry fixture');}}),/interrupted retry fixture/);
  const partial=await runWorker({...options,localAlertLedgerPath:ledgerPath});
  assert.equal(partial.local_alert_archive.compacted_this_run,0);
  assert.deepEqual(pendingAlertIntents(await read(options.eventsPath)),[recovery]);
  await localConsume(f,{mode:'local-fail',maxAttempts:2});
  const finished=await runWorker({...options,localAlertLedgerPath:ledgerPath});
  assert.equal(finished.local_alert_archive.archived_dead_letter,1);
  assert.equal(finished.alert_outbox_pending,0);
  assert.equal((await read(options.statePath))[LOCAL_ALERT_ARCHIVE_KEY].records[1].local_delivery.delivery_attempts,2);
});

test('mismatched ledger binding fails closed before watch requests or pair changes',async t=>{
  const f=await fixture(t);
  const {options,ledgerPath}=f;
  let requests=0;
  t.mock.method(globalThis,'fetch',async()=>{requests++;throw new TypeError('fixture unreachable');});
  await runWorker(options);
  await localConsume(f);
  const ledger=await read(ledgerPath);
  const [record]=Object.values(ledger.records);
  record.watch_id='wrong-watch';
  await write(ledgerPath,ledger);
  const [state,events]=await Promise.all([fs.readFile(options.statePath),fs.readFile(options.eventsPath)]);
  await assert.rejects(runWorker({...options,localAlertLedgerPath:ledgerPath}),/alert intent identity mismatch/);
  assert.equal(requests,1);
  assert.deepEqual(await fs.readFile(options.statePath),state);
  assert.deepEqual(await fs.readFile(options.eventsPath),events);
});

test('oversized and over-count ledgers are rejected by the worker and consumer without rewriting evidence',async t=>{
  const f=await fixture(t);
  const {options,ledgerPath}=f;
  let requests=0;
  t.mock.method(globalThis,'fetch',async()=>{requests++;throw new TypeError('fixture unreachable');});
  await runWorker(options);
  await localConsume(f);
  const valid=await read(ledgerPath);
  const [record]=Object.values(valid.records);
  const [state,events]=await Promise.all([fs.readFile(options.statePath),fs.readFile(options.eventsPath)]);
  await fs.truncate(ledgerPath,MAX_LOCAL_ALERT_LEDGER_BYTES+1);
  await assert.rejects(runWorker({...options,localAlertLedgerPath:ledgerPath}),/exceeds byte limit/);
  await assert.rejects(localConsume(f),/exceeds byte limit/);
  assert.equal((await fs.stat(ledgerPath)).size,MAX_LOCAL_ALERT_LEDGER_BYTES+1);

  const [original]=pendingAlertIntents(JSON.parse(events.toString('utf8')));
  const records=Object.fromEntries(Array.from({length:MAX_LOCAL_ALERT_LEDGER_RECORDS+1},()=>{
    const intent={...original,id:randomUUID()};
    return [intent.id,{...record,intent_id:intent.id,intent_sha256:alertIntentSha256(intent),
      local_receipt_id:`local:${intent.id}`}];
  }));
  await write(ledgerPath,{...valid,records});
  const excessiveRows=await fs.readFile(ledgerPath);
  await assert.rejects(runWorker({...options,localAlertLedgerPath:ledgerPath}),/exceeds record limit/);
  await assert.rejects(localConsume(f),/exceeds record limit/);
  assert.deepEqual(await fs.readFile(ledgerPath),excessiveRows);

  const overflowId=Object.keys(records).at(-1);
  delete records[overflowId];
  await write(ledgerPath,{...valid,records});
  const fullLedger=await fs.readFile(ledgerPath);
  await assert.rejects(localConsume(f),/exceeds record limit/);
  assert.deepEqual(await fs.readFile(ledgerPath),fullLedger);
  assert.equal(requests,1);
  assert.deepEqual(await fs.readFile(options.statePath),state);
  assert.deepEqual(await fs.readFile(options.eventsPath),events);
});

test('a changing or symlinked ledger cannot authorize compaction',async t=>{
  const f=await fixture(t);
  const {options,ledgerPath}=f;
  let requests=0;
  t.mock.method(globalThis,'fetch',async()=>{requests++;throw new TypeError('fixture unreachable');});
  await runWorker(options);
  await localConsume(f);
  const link=`${ledgerPath}.link`;
  await fs.symlink(ledgerPath,link);
  await assert.rejects(runWorker({...options,localAlertLedgerPath:link}),/regular file/);
  const [state,events]=await Promise.all([
    fs.readFile(options.statePath),fs.readFile(options.eventsPath)]);
  const ledger=await read(ledgerPath);
  const [record]=Object.values(ledger.records);
  record.watch_id='changed';
  const replacement=Buffer.from(JSON.stringify(ledger,null,2)+'\n');
  assert.equal(replacement.length,(await fs.stat(ledgerPath)).size);
  const originalOpen=fs.open.bind(fs);
  let mutated=false;
  const mock=t.mock.method(fs,'open',async(file,...args)=>{
    const handle=await originalOpen(file,...args);
    if(path.resolve(String(file))===path.resolve(ledgerPath) && !mutated){
      return {
        stat:handle.stat.bind(handle),close:handle.close.bind(handle),
        read:async(...readArgs)=>{
          const result=await handle.read(...readArgs);
          mutated=true;
          const editor=await originalOpen(ledgerPath,'r+');
          try{
            await editor.write(replacement,0,replacement.length,0);
            const future=new Date(Date.now()+60_000);
            await editor.utimes(future,future);
            await editor.sync();
          }finally{await editor.close();}
          return result;
        }
      };
    }
    return handle;
  });
  await assert.rejects(runWorker({...options,localAlertLedgerPath:ledgerPath}),
    /alert delivery ledger changed while being read/);
  mock.mock.restore();
  assert.equal(mutated,true);
  assert.equal(requests,1);
  assert.deepEqual(await fs.readFile(ledgerPath),replacement);
  assert.deepEqual(await fs.readFile(options.statePath),state);
  assert.deepEqual(await fs.readFile(options.eventsPath),events);
  assert.equal(pendingAlertIntents(await read(options.eventsPath)).length,1);
});

test('incoherent terminal histories cannot archive their source intent',async t=>{
  const f=await fixture(t);
  const {options,ledgerPath}=f;
  let requests=0;
  t.mock.method(globalThis,'fetch',async()=>{requests++;throw new TypeError('fixture unreachable');});
  await runWorker(options);
  const [intent]=pendingAlertIntents(await read(options.eventsPath));
  await localConsume(f,{mode:'local-fail-once'});
  const acknowledged=await read(ledgerPath);
  await localConsume({...f,ledgerPath:`${ledgerPath}.dead`},{mode:'local-fail',maxAttempts:2});
  const dead=await read(`${ledgerPath}.dead`);
  const [state,events]=await Promise.all([fs.readFile(options.statePath),fs.readFile(options.eventsPath)]);
  const cases=[
    [acknowledged,record=>Object.assign(record.attempts[0],{outcome:'acknowledged',error_code:null})],
    [acknowledged,record=>record.acknowledged_at++],
    [dead,record=>record.dead_lettered_at=record.attempts.at(-1).completed_at-1],
    [dead,record=>record.last_error_code='LOCAL_TRANSIENT'],
  ];
  for(const [ledger,mutate] of cases){
    const forged=structuredClone(ledger);
    mutate(forged.records[intent.id]);
    await write(ledgerPath,forged);
    await assert.rejects(runWorker({...options,localAlertLedgerPath:ledgerPath}),/invalid alert delivery ledger/);
  }
  assert.equal(requests,1);
  assert.deepEqual(await fs.readFile(options.statePath),state);
  assert.deepEqual(await fs.readFile(options.eventsPath),events);
});

test('worker command opts in to local compaction on the normal state and events paths',async t=>{
  const f=await fixture(t);
  const {options,ledgerPath}=f;
  t.mock.method(globalThis,'fetch',async()=>{throw new TypeError('fixture unreachable');});
  await runWorker(options);
  await localConsume(f);
  await write(options.watchesPath,[{...watch,status:'paused'}]);
  const worker=fileURLToPath(new URL('../worker.mjs',import.meta.url));
  const child=spawn(process.execPath,[worker,'--local-alert-ledger',ledgerPath],{
    cwd:path.dirname(options.statePath),stdio:['ignore','pipe','pipe']});
  let output='',errors='';
  child.stdout.on('data',chunk=>{output+=String(chunk);});
  child.stderr.on('data',chunk=>{errors+=String(chunk);});
  assert.deepEqual(await once(child,'close'),[0,null],errors);
  assert.equal(JSON.parse(output).local_alert_archive.archived_acknowledged,1);
  assert.equal(pendingAlertIntents(await read(options.eventsPath)).length,0);
});

test('a full archive rolls its oldest half into a chained generation before compaction',async t=>{
  const f=await fixture(t);
  const {options,ledgerPath}=f;
  t.mock.method(globalThis,'fetch',async()=>{throw new TypeError('fixture unreachable');});
  await runWorker(options);
  await localConsume(f);
  const [intent]=pendingAlertIntents(await read(options.eventsPath));
  const {records:byId}=await read(ledgerPath);
  const records=Array.from({length:MAX_LOCAL_ALERT_ARCHIVE_RECORDS},(_,i)=>{
    const example={...intent,id:randomUUID(),watch_id:`archived-${i}`};
    const local_delivery={...byId[intent.id],intent_id:example.id,intent_sha256:alertIntentSha256(example),
      watch_id:example.watch_id,local_receipt_id:`local:${example.id}`};
    return {intent:example,local_delivery};
  });
  const state=await read(options.statePath);
  state[LOCAL_ALERT_ARCHIVE_KEY]={schema_version:1,type:'monitor_local_alert_archive',records};
  await write(options.statePath,state);
  await write(options.watchesPath,[{...watch,status:'paused'}]);
  const entry=new URL('../worker.mjs',import.meta.url).href;
  const command=`import fs from 'node:fs/promises';
    import {runWorker} from ${JSON.stringify(entry)};
    const rename=fs.rename;
    fs.rename=async (from,to)=>{
      if(to===${JSON.stringify(`${options.statePath}.pending`)}) {
        process.stdout.write('BEFORE_JOURNAL\\n');
        await new Promise(resolve=>setTimeout(resolve,60_000));
      }
      return rename(from,to);
    };
    await runWorker(${JSON.stringify({...options,localAlertLedgerPath:ledgerPath})});`;
  const child=spawn(process.execPath,['--input-type=module','--eval',command],{stdio:['ignore','pipe','pipe']});
  t.after(()=>{if(child.exitCode===null && child.signalCode===null) child.kill('SIGKILL');});
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('worker did not reach journal write within timeout')),5000);
    child.stdout.on('data',chunk=>{
      if(String(chunk).includes('BEFORE_JOURNAL')){clearTimeout(timer);resolve();}
    });
    child.once('error',error=>{clearTimeout(timer);reject(error);});
    child.once('exit',code=>{clearTimeout(timer);reject(new Error(`worker exited early: ${code}`));});
  });
  const exited=once(child,'exit');
  child.kill('SIGKILL');
  assert.deepEqual(await exited,[null,'SIGKILL']);
  assert.equal((await fs.readdir(path.dirname(ledgerPath)))
    .filter(name=>name.startsWith(`${path.basename(ledgerPath)}.archive-`)).length,1);
  const rolled=await runWorker({...options,localAlertLedgerPath:ledgerPath});
  assert.equal(rolled.alert_outbox_pending,0);
  assert.equal(rolled.local_alert_archive.terminal_reconciliation_deferred,0);
  assert.equal(rolled.local_alert_archive.rolled_over_this_run,250);
  assert.equal(rolled.local_alert_archive.archive_generations,1);
  assert.equal(rolled.local_alert_archive.recovered_rollover_generation,1);
  assert.equal(rolled.local_alert_archive.archived_acknowledged,501);
  assert.deepEqual(pendingAlertIntents(await read(options.eventsPath)),[]);
  const archive=(await read(options.statePath))[LOCAL_ALERT_ARCHIVE_KEY];
  assert.equal(archive.schema_version,2);
  assert.equal(archive.records.length,251);
  assert.deepEqual(archive.records.slice(0,250),records.slice(250));
  assert.deepEqual(archive.records[250].intent,intent);
  const [generation]=archive.generations;
  const generationFile=`${ledgerPath}.archive-${String(generation.sequence).padStart(4,'0')}-${generation.sha256}.json`;
  const external=await read(generationFile);
  assert.equal(external.previous_sha256,null);
  assert.deepEqual(external.records,records.slice(0,250));
  const replay=await runWorker({...options,localAlertLedgerPath:ledgerPath});
  assert.equal(replay.alert_outbox_pending,0);
  assert.equal(replay.local_alert_archive.archive_generations,1);
});

test('committed generations retire terminal ledger rows and continue delivery past 1000 outcomes',async t=>{
  const f=await fixture(t);
  const {options,ledgerPath}=f;
  t.mock.method(globalThis,'fetch',async()=>{throw new TypeError('fixture unreachable');});
  await runWorker(options);
  await localConsume(f);
  const [firstIntent]=pendingAlertIntents(await read(options.eventsPath));
  const firstLedger=await read(ledgerPath);
  const templateRecord=firstLedger.records[firstIntent.id];
  const initial=Array.from({length:MAX_LOCAL_ALERT_ARCHIVE_RECORDS},(_,index)=>
    terminalEntry(templateRecord,distinctIntent(firstIntent,index)));
  const state=await read(options.statePath);
  state[LOCAL_ALERT_ARCHIVE_KEY]={schema_version:1,type:'monitor_local_alert_archive',records:initial};
  firstLedger.records=Object.fromEntries([
    ...initial.map(entry=>[entry.intent.id,entry.local_delivery]),
    [firstIntent.id,templateRecord]
  ]);
  firstLedger.observed_at=Date.now();
  await Promise.all([write(options.statePath,state),write(ledgerPath,firstLedger),
    write(options.watchesPath,[{...watch,status:'paused'}])]);

  const firstRollover=await runWorker({...options,localAlertLedgerPath:ledgerPath});
  assert.equal(firstRollover.local_alert_archive.archive_generations,1);
  assert.equal(Object.keys((await read(ledgerPath)).records).length,501);
  const beforeRetirement=await read(ledgerPath);
  const disagreement=structuredClone(beforeRetirement);
  const changedId=initial[0].intent.id;
  disagreement.records[changedId].attempts[0].completed_at++;
  disagreement.records[changedId].acknowledged_at++;
  await write(ledgerPath,disagreement);
  const pairedBefore=await Promise.all([fs.readFile(options.statePath),fs.readFile(options.eventsPath)]);
  await assert.rejects(runWorker({...options,localAlertLedgerPath:ledgerPath}),
    /archive generation and alert delivery ledger disagree/);
  assert.deepEqual(await Promise.all([fs.readFile(options.statePath),fs.readFile(options.eventsPath)]),pairedBefore);
  await write(ledgerPath,beforeRetirement);
  const firstRetirement=await runWorker({...options,localAlertLedgerPath:ledgerPath});
  assert.equal(firstRetirement.local_alert_archive.ledger_records_retired_this_run,250);
  assert.equal(Object.keys((await read(ledgerPath)).records).length,251);

  await addTerminalBatch(options,ledgerPath,firstIntent,templateRecord,249,500);
  await runWorker({...options,localAlertLedgerPath:ledgerPath});
  let sequence=749;
  let lastDelivered;
  for(let generation=2;generation<=3;generation++){
    const delivered=distinctIntent(firstIntent,++sequence);
    lastDelivered=delivered;
    await write(options.eventsPath,[delivered]);
    const delivery=await localConsume(f,{batchLimit:1});
    assert.equal(delivery.attempted_this_run,1);
    assert.equal((await read(ledgerPath)).records[delivered.id].delivery_status,'acknowledged');
    const rollover=await runWorker({...options,localAlertLedgerPath:ledgerPath});
    assert.equal(rollover.local_alert_archive.archive_generations,generation);
    assert.equal(rollover.local_alert_archive.archived_acknowledged,500+(generation-1)*250+1);
    const retirement=await runWorker({...options,localAlertLedgerPath:ledgerPath});
    assert.equal(retirement.local_alert_archive.ledger_records_retired_this_run,250);
    assert.equal(Object.keys((await read(ledgerPath)).records).length,251);
    if(generation<3){
      await addTerminalBatch(options,ledgerPath,firstIntent,templateRecord,249,sequence+1);
      await runWorker({...options,localAlertLedgerPath:ledgerPath});
      sequence+=249;
    }
  }
  const archive=(await read(options.statePath))[LOCAL_ALERT_ARCHIVE_KEY];
  assert.equal(archive.generations.length,3);
  assert.equal(archive.generations.reduce((sum,item)=>sum+item.record_count,0)+archive.records.length,1001);
  assert.equal(pendingAlertIntents(await read(options.eventsPath)).length,0);
  const retainedLedger=await read(ledgerPath);
  assert.equal(Object.keys(retainedLedger.records).length,251);
  assert.equal(retainedLedger.records[lastDelivered.id].delivery_status,'acknowledged');

  const retiredIntent=initial[0].intent;
  assert.equal(retainedLedger.records[retiredIntent.id],undefined);
  await write(options.eventsPath,[retiredIntent]);
  const replay=await runWorker({...options,localAlertLedgerPath:ledgerPath});
  assert.equal(replay.local_alert_archive.compacted_this_run,1);
  assert.equal(pendingAlertIntents(await read(options.eventsPath)).length,0);
  assert.equal((await localConsume(f,{batchLimit:1})).attempted_this_run,0);
});

test('an ambiguous outage key preserves both original intent IDs',async t=>{
  const f=await fixture(t);
  const {options,ledgerPath}=f;
  t.mock.method(globalThis,'fetch',async()=>{throw new TypeError('fixture unreachable');});
  await runWorker(options);
  await localConsume(f);
  const events=await read(options.eventsPath);
  const [intent]=pendingAlertIntents(events);
  const duplicate={...intent,id:randomUUID()};
  await write(options.eventsPath,[...events,duplicate]);
  const result=await runWorker({...options,localAlertLedgerPath:ledgerPath});
  assert.equal(result.local_alert_archive.terminal_reconciliation_deferred,1);
  assert.equal(result.local_alert_archive.compacted_this_run,0);
  assert.deepEqual(pendingAlertIntents(await read(options.eventsPath)),[intent,duplicate]);
});

test('SIGKILL between event and state replacement restores terminal evidence on restart',async t=>{
  const f=await fixture(t);
  const {options,ledgerPath}=f;
  t.mock.method(globalThis,'fetch',async()=>{throw new TypeError('fixture unreachable');});
  await runWorker(options);
  const [intent]=pendingAlertIntents(await read(options.eventsPath));
  await localConsume(f);
  await write(options.watchesPath,[{...watch,status:'paused'}]);
  const entry=new URL('../worker.mjs',import.meta.url).href;
  const command=`import fs from 'node:fs/promises';
    import {runWorker} from ${JSON.stringify(entry)};
    const rename=fs.rename;
    fs.rename=async (from,to)=>{
      await rename(from,to);
      if(to===${JSON.stringify(options.eventsPath)}) {
        process.stdout.write('EVENTS_REPLACED\\n');
        await new Promise(resolve=>setTimeout(resolve,60_000));
      }
    };
    await runWorker(${JSON.stringify({...options,localAlertLedgerPath:ledgerPath})});`;
  const child=spawn(process.execPath,['--input-type=module','--eval',command],{stdio:['ignore','pipe','pipe']});
  t.after(()=>{if(child.exitCode===null && child.signalCode===null) child.kill('SIGKILL');});
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('worker did not replace events within timeout')),5000);
    child.stdout.on('data',chunk=>{
      if(String(chunk).includes('EVENTS_REPLACED')){clearTimeout(timer);resolve();}
    });
    child.once('error',error=>{clearTimeout(timer);reject(error);});
    child.once('exit',code=>{clearTimeout(timer);reject(new Error(`worker exited early: ${code}`));});
  });
  const exited=once(child,'exit');
  child.kill('SIGKILL');
  assert.deepEqual(await exited,[null,'SIGKILL']);
  assert.equal((await read(options.statePath))[LOCAL_ALERT_ARCHIVE_KEY],undefined);
  assert.equal(pendingAlertIntents(await read(options.eventsPath)).length,0);
  const journal=await read(`${options.statePath}.pending`);
  assert.deepEqual(journal.state[LOCAL_ALERT_ARCHIVE_KEY].records[0].intent,intent);
  await runWorker(options);
  assert.deepEqual((await read(options.statePath))[LOCAL_ALERT_ARCHIVE_KEY],journal.state[LOCAL_ALERT_ARCHIVE_KEY]);
  assert.equal(pendingAlertIntents(await read(options.eventsPath)).length,0);
  await assert.rejects(fs.stat(`${options.statePath}.pending`),{code:'ENOENT'});
});
