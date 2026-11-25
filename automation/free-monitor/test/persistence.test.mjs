import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {runWorker} from '../worker.mjs';
import {MAX_MONITOR_PERSISTENCE_BYTES,readMonitorPair} from '../persistence.mjs';

async function fixture(t) {
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-pair-'));
  t.after(()=>fs.rm(directory,{recursive:true,force:true}));
  const options={watchesPath:path.join(directory,'watches.json'),statePath:path.join(directory,'state.json'),
    eventsPath:path.join(directory,'events.json'),intervalMs:0};
  const pending=`${options.statePath}.pending`;
  await fs.writeFile(options.watchesPath,JSON.stringify([{id:'fixture',targetUrl:'https://fixture.invalid/'}]));
  return {options,pending};
}

const read=async file=>JSON.parse(await fs.readFile(file,'utf8'));

test('an interrupted second replacement replays before cadence or event decisions',async t=>{
  const {options,pending}=await fixture(t);
  let status=200,requests=0;
  t.mock.method(globalThis,'fetch',async()=>{
    requests++;
    return new Response('stable',{status});
  });
  assert.equal((await runWorker(options)).ok,true);
  const baseline=await read(options.statePath);

  status=503;
  let interrupt=true;
  const rename=fs.rename;
  t.mock.method(fs,'rename',async (source,target)=>{
    if (interrupt && target===options.statePath) {
      throw Object.assign(new Error('interrupted state replacement'),{code:'EIO'});
    }
    return rename(source,target);
  });
  await assert.rejects(runWorker(options),{code:'EIO'});
  const journal=await read(pending);
  assert.deepEqual(await read(options.statePath),baseline);
  assert.deepEqual(await read(options.eventsPath),journal.events);
  assert.equal(journal.state.fixture.last_status,503);
  assert.equal(journal.events.length,2);
  const [outage,outageAlert]=journal.events;
  assert.equal(outage.availability,'unavailable');
  assert.equal(outage.at,journal.state.fixture.last_checked_at);
  assert.equal(outageAlert.type,'alert_intent');
  assert.equal(outageAlert.alert_kind,'outage');
  assert.equal(outageAlert.delivery_status,'pending');

  await assert.rejects(runWorker(options),{code:'EIO'});
  assert.equal(requests,3,'a failed replay must stop before the next poll');
  assert.deepEqual(await read(options.eventsPath),[outage,outageAlert]);
  interrupt=false;
  const skipped=await runWorker({...options,intervalMs:300000});
  assert.equal(skipped.ok,false);
  assert.equal(skipped.results[0].reason,'not_due');
  assert.equal(requests,3);
  assert.equal((await read(options.statePath)).fixture.last_status,503);
  assert.deepEqual(await read(options.eventsPath),[outage,outageAlert]);
  await assert.rejects(fs.stat(pending),{code:'ENOENT'});

  status=200;
  assert.equal((await runWorker(options)).ok,true);
  const [retained,retainedAlert,recovery,recoveryAlert,...extra]=await read(options.eventsPath);
  assert.deepEqual(retained,outage);
  assert.deepEqual(retainedAlert,outageAlert);
  assert.equal(recovery.previous_availability,'unavailable');
  assert.equal(recovery.availability,'healthy');
  assert.equal(recoveryAlert.type,'alert_intent');
  assert.equal(recoveryAlert.alert_kind,'recovery');
  assert.deepEqual(extra,[]);
});

test('unexpected evidence errors stop before requests without overwriting artifacts',async t=>{
  const {options,pending}=await fixture(t);
  const mockedFetch=t.mock.method(globalThis,'fetch',async()=>new Response('fixture'));
  await fs.mkdir(options.eventsPath);
  await assert.rejects(runWorker(options),/monitor events must be a regular file/);
  await fs.rmdir(options.eventsPath);
  await fs.writeFile(options.eventsPath,'null');
  await assert.rejects(runWorker(options),/Invalid monitor events/);
  assert.equal(await fs.readFile(options.eventsPath,'utf8'),'null');

  await fs.writeFile(options.statePath,'[]');
  await fs.writeFile(options.eventsPath,'[]');
  await assert.rejects(runWorker(options),/Invalid monitor state/);
  assert.equal(await fs.readFile(options.statePath,'utf8'),'[]');

  const wrongPair=JSON.stringify({schema_version:1,events_path:'other.json',state:{},events:[]});
  await fs.writeFile(pending,wrongPair);
  await assert.rejects(runWorker(options),/Invalid pending monitor persistence journal/);
  assert.equal(await fs.readFile(pending,'utf8'),wrongPair);

  const directory=path.dirname(options.statePath);
  const alias=path.join(directory,'alias');
  await fs.symlink(directory,alias,'dir');
  await assert.rejects(runWorker({...options,eventsPath:path.join(alias,'state.json')}),/paths must be distinct/);
  await assert.rejects(runWorker({...options,eventsPath:path.join(alias,'state.json.pending')}),/paths must be distinct/);
  assert.equal(mockedFetch.mock.callCount(),0);
});

test('persistence inputs and a pre-existing combined pending snapshot have a hard byte ceiling',async t=>{
  const {options,pending}=await fixture(t);
  const mockedFetch=t.mock.method(globalThis,'fetch',async()=>new Response('fixture'));
  await fs.writeFile(options.statePath,'{}');
  await fs.truncate(options.statePath,MAX_MONITOR_PERSISTENCE_BYTES+1);
  await assert.rejects(runWorker(options),new RegExp(
    `monitor state exceeds ${MAX_MONITOR_PERSISTENCE_BYTES} byte limit`));
  assert.equal(mockedFetch.mock.callCount(),0);
  assert.equal((await fs.stat(options.statePath)).size,MAX_MONITOR_PERSISTENCE_BYTES+1);

  const state=Buffer.from(JSON.stringify({fixture:{payload:'s'.repeat(4_300_000)}}));
  const events=Buffer.from(JSON.stringify([{payload:'e'.repeat(4_300_000)}]));
  assert.ok(state.length<MAX_MONITOR_PERSISTENCE_BYTES);
  assert.ok(events.length<MAX_MONITOR_PERSISTENCE_BYTES);
  await fs.writeFile(options.statePath,state);
  await fs.writeFile(options.eventsPath,events);
  await assert.rejects(runWorker(options),new RegExp(
    `combined monitor persistence snapshot exceeds ${MAX_MONITOR_PERSISTENCE_BYTES} byte limit`));
  assert.equal(mockedFetch.mock.callCount(),0);
  assert.deepEqual(await fs.readFile(options.statePath),state);
  assert.deepEqual(await fs.readFile(options.eventsPath),events);
  await assert.rejects(fs.stat(pending),{code:'ENOENT'});

  await fs.rm(options.eventsPath);
  await fs.rm(options.statePath);
  await fs.writeFile(options.statePath,'{}');
  await fs.symlink(options.statePath,pending);
  await assert.rejects(readMonitorPair(options),/pending monitor persistence journal must be a regular file/);
});

test('same-size in-place mutation is rejected through stable descriptor metadata',async t=>{
  const {options}=await fixture(t);
  await fs.writeFile(options.statePath,'{"fixture":{}}\n');
  await fs.writeFile(options.eventsPath,'[]\n');
  const open=fs.open;
  let mutated=false;
  t.mock.method(fs,'open',async (file,...args)=>{
    const handle=await open(file,...args);
    if(path.resolve(String(file))!==path.resolve(options.statePath) || mutated) return handle;
    return {
      stat:handle.stat.bind(handle),
      close:handle.close.bind(handle),
      read:async (...readArgs)=>{
        const result=await handle.read(...readArgs);
        mutated=true;
        const editor=await open(options.statePath,'r+');
        try{
          await editor.write(Buffer.from('g'),0,1,2);
          const future=new Date(Date.now()+60_000);
          await editor.utimes(future,future);
          await editor.sync();
        }finally{await editor.close();}
        return result;
      }
    };
  });
  await assert.rejects(readMonitorPair(options),/monitor state changed while being read/);
  assert.equal(mutated,true);
  assert.equal((await fs.stat(options.statePath)).size,Buffer.byteLength('{"fixture":{}}\n'));
});
