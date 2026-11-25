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
  const originalOpen=fs.open.bind(fs);
  const mock=t.mock.method(fs,'open',async(file,...args)=>{
    const handle=await originalOpen(file,...args);
    if(file===ledgerPath){
      const originalStat=handle.stat.bind(handle);
      handle.stat=async()=>{
        const stat=await originalStat();
        await fs.appendFile(ledgerPath,' ');
        return stat;
      };
    }
    return handle;
  });
  await assert.rejects(runWorker({...options,localAlertLedgerPath:ledgerPath}),/changed while being read/);
  mock.mock.restore();
  assert.equal(requests,1);
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

test('a full archive defers terminal work without evicting existing archive or pending inputs',async t=>{
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
  const deferred=await runWorker({...options,localAlertLedgerPath:ledgerPath});
  assert.equal(deferred.alert_outbox_pending,1);
  assert.equal(deferred.local_alert_archive.terminal_reconciliation_deferred,1);
  assert.deepEqual(pendingAlertIntents(await read(options.eventsPath)),[intent]);
  assert.deepEqual((await read(options.statePath))[LOCAL_ALERT_ARCHIVE_KEY].records,records);
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
