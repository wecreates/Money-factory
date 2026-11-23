import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeWatch, evaluateCheck, dueForCheck, isMainEntry} from '../worker.mjs';

test('normalizeWatch accepts an active HTTPS watch',()=>{
  const w=normalizeWatch({id:'demo',kind:'change',targetUrl:'https://example.com/',label:'Demo',status:'active'});
  assert.equal(w.id,'demo');
  assert.equal(w.targetUrl,'https://example.com/');
  assert.equal(w.status,'active');
});

test('dueForCheck is true when no prior check exists',()=>{
  assert.equal(dueForCheck({status:'active',last_checked_at:null},Date.now(),300000),true);
});

test('dueForCheck honors cadence interval',()=>{
  const now=1_000_000;
  assert.equal(dueForCheck({status:'active',last_checked_at:now-299999},now,300000),false);
  assert.equal(dueForCheck({status:'active',last_checked_at:now-300000},now,300000),true);
});

test('evaluateCheck records baseline without false change event',()=>{
  const out=evaluateCheck({last_value:null,last_checked_at:null},{hash:'abc',checkedAt:123,status:200});
  assert.equal(out.changed,false);
  assert.equal(out.next.last_value,'abc');
  assert.equal(out.next.last_checked_at,123);
});

test('evaluateCheck flags changed content after baseline',()=>{
  const out=evaluateCheck({last_value:'abc',last_checked_at:100},{hash:'def',checkedAt:200,status:200});
  assert.equal(out.changed,true);
  assert.equal(out.next.last_value,'def');
  assert.equal(out.next.last_checked_at,200);
});


test('isMainEntry matches a file URL to the executable path',()=>{
  assert.equal(isMainEntry('file:///tmp/free-monitor/worker.mjs','/tmp/free-monitor/worker.mjs'),true);
  assert.equal(isMainEntry('file:///tmp/free-monitor/worker.mjs','/tmp/free-monitor/other.mjs'),false);
});


test('normalizeWatch preserves status metadata',()=>{
  const w=normalizeWatch({id:'demo2',targetUrl:'https://example.com/',status:'active',last_status:200});
  assert.equal(w.last_status,200);
});

import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {runWorker} from '../worker.mjs';

test('duplicate normalized IDs reject before requests or state/event writes',async(t)=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-duplicate-'));
  const options={watchesPath:path.join(dir,'watches.json'),statePath:path.join(dir,'state.json'),eventsPath:path.join(dir,'events.json'),intervalMs:0};
  let requests=0;
  t.mock.method(globalThis,'fetch',async url=>{
    requests++;
    return new Response('fixture',{status:url.includes('failed')?502:200});
  });
  const state='{"prior":{"last_error":"retained failure"}}\n';
  const events='[{"type":"retained-event"}]\n';
  try{
    await fs.writeFile(options.statePath,state);await fs.writeFile(options.eventsPath,events);
    for(const status of ['active','paused']){
      await fs.writeFile(options.watchesPath,JSON.stringify([
        {id:'same',targetUrl:'https://failed.invalid/'},
        {id:' same ',targetUrl:'https://healthy.invalid/',status}
      ]));
      await assert.rejects(runWorker(options),/duplicate watch id/);
      assert.equal(requests,0);
      assert.equal(await fs.readFile(options.statePath,'utf8'),state);
      assert.equal(await fs.readFile(options.eventsPath,'utf8'),events);
    }
  }finally{await fs.rm(dir,{recursive:true,force:true});}
});

test('real HTTP failure persists 502, exits nonzero, and recovery clears the error',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-health-'));
  let status=502;
  const server=http.createServer((req,res)=>{res.writeHead(status);res.end('fixture');});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const options={watchesPath:path.join(dir,'FREE_MONITOR_WATCHES.json'),statePath:path.join(dir,'FREE_MONITOR_STATE.json'),eventsPath:path.join(dir,'FREE_MONITOR_EVENTS.json'),intervalMs:0};
  try{
    const watch={id:'fixture',targetUrl:'http://127.0.0.1:'+server.address().port,status:'active'};
    await fs.writeFile(options.watchesPath,JSON.stringify([watch]));
    await fs.writeFile(options.statePath,JSON.stringify({fixture:{...watch,last_status:200,last_value:'old'}}));
    const child=spawn(process.execPath,[fileURLToPath(new URL('../worker.mjs',import.meta.url))],{cwd:dir,stdio:['ignore','pipe','pipe']});
    let out='';child.stdout.on('data',chunk=>out+=chunk);
    const exit=await new Promise((resolve,reject)=>{child.on('error',reject);child.on('exit',resolve);});
    assert.equal(exit,2);assert.equal(JSON.parse(out).ok,false);
    const state=JSON.parse(await fs.readFile(options.statePath,'utf8'));
    assert.equal(state.fixture.last_status,502);assert.match(state.fixture.last_error,/502/);
    assert.equal((await runWorker({...options,intervalMs:999999})).ok,false);
    status=200;
    assert.equal((await runWorker(options)).ok,true);
    const recovered=JSON.parse(await fs.readFile(options.statePath,'utf8')).fixture;
    assert.equal(recovered.last_status,200);assert.equal(recovered.last_error,null);
    await new Promise(resolve=>server.close(resolve));
    assert.equal((await runWorker(options)).ok,false);
    assert.equal(JSON.parse(await fs.readFile(options.statePath,'utf8')).fixture.last_status,null);
  }finally{server.closeAllConnections();server.close();await fs.rm(dir,{recursive:true,force:true});}
});

test('availability transitions record per-probe completion, deduplicate and preserve the content baseline',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-availability-'));
  let status=200, body='baseline', responseAt=0;
  const server=http.createServer((req,res)=>{
    if(req.url==='/delay'){
      setTimeout(()=>res.end('stable'),50);
      return;
    }
    responseAt=Date.now();
    res.writeHead(status);
    res.end(body);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  const options={watchesPath:path.join(dir,'watches.json'),statePath:path.join(dir,'state.json'),eventsPath:path.join(dir,'events.json'),intervalMs:0};
  const watch={id:'target',targetUrl:origin+'/target'};
  const configure=url=>fs.writeFile(options.watchesPath,JSON.stringify([{id:'delay',targetUrl:origin+'/delay'},{...watch,targetUrl:url}]));
  const readEvents=async()=>JSON.parse(await fs.readFile(options.eventsPath,'utf8'));
  const readState=async()=>JSON.parse(await fs.readFile(options.statePath,'utf8')).target;
  try{
    await configure(watch.targetUrl);
    assert.equal((await runWorker(options)).ok,true);
    const baseline=await readState();
    assert.deepEqual(await readEvents(),[]);
    status=503;
    const failed=await runWorker(options);
    assert.equal(failed.ok,false);
    const failedTarget=failed.results.find(result=>result.id==='target');
    assert.ok(failedTarget.last_checked_at>=responseAt,'failure time precedes the response');
    assert.equal((await readState()).last_checked_at,failedTarget.last_checked_at);
    assert.equal((await readState()).last_value,baseline.last_value);
    const [failure]=await readEvents();
    assert.deepEqual({type:failure.type,from:failure.previous_availability,to:failure.availability,status:failure.http_status,at:failure.at},
      {type:'availability',from:'healthy',to:'unavailable',status:503,at:failedTarget.last_checked_at});
    await runWorker(options);
    assert.deepEqual(await readEvents(),[failure]);

    status=200;
    const recovered=await runWorker(options);
    assert.equal(recovered.ok,true);
    const recoveredTarget=recovered.results.find(result=>result.id==='target');
    assert.equal(recoveredTarget.changed,false);
    assert.equal((await readState()).last_change_at,baseline.last_change_at);
    const [,recovery]=await readEvents();
    assert.deepEqual({type:recovery.type,from:recovery.previous_availability,to:recovery.availability,status:recovery.http_status,at:recovery.at},
      {type:'availability',from:'unavailable',to:'healthy',status:200,at:recoveredTarget.last_checked_at});
    await runWorker(options);
    assert.deepEqual(await readEvents(),[failure,recovery]);

    body='updated';
    const recent=Array.from({length:498},(_,i)=>({id:`old-${i}`,type:'change'}));
    await fs.writeFile(options.eventsPath,JSON.stringify([...recent,failure,recovery]));
    await runWorker(options);
    const events=await readEvents();
    assert.equal(events.length,500);
    assert.deepEqual(events.slice(0,-1),[...recent.slice(1),failure,recovery]);
    const {id,...change}=events.at(-1);
    assert.ok(id);
    assert.deepEqual(change,{watch_id:'target',type:'change',label:'target',target_url:watch.targetUrl,at:(await readState()).last_change_at});

    status=503;
    const retarget=origin+'/new-target';
    await configure(retarget);
    await runWorker(options);
    const firstFailure=(await readEvents()).at(-1);
    assert.equal(firstFailure.previous_availability,'unknown');
    assert.equal(firstFailure.availability,'unavailable');
    assert.equal(firstFailure.target_url,retarget);
    assert.equal((await readState()).last_value,null);
  }finally{server.closeAllConnections();server.close();await fs.rm(dir,{recursive:true,force:true});}
});

import crypto from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {MAX_RESPONSE_BYTES} from '../worker.mjs';

test('decoded body ceiling preserves baseline on declared, chunked and gzip overflow, then recovers',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-limit-'));
  const exact=Buffer.alloc(MAX_RESPONSE_BYTES,97);
  const overflow=Buffer.alloc(MAX_RESPONSE_BYTES+1,98);
  let mode='exact';
  const server=http.createServer((req,res)=>{
    if(mode==='gzip'){
      const compressed=gzipSync(overflow);
      res.writeHead(200,{'content-encoding':'gzip','content-length':compressed.length});
      res.end(compressed);
    }else if(mode==='chunked'){
      res.writeHead(200,{'transfer-encoding':'chunked'});
      res.write(overflow.subarray(0,MAX_RESPONSE_BYTES));res.end(overflow.subarray(MAX_RESPONSE_BYTES));
    }else{
      const body=mode==='exact'?exact:overflow;
      res.writeHead(200,{'content-length':body.length});res.end(body);
    }
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const options={watchesPath:path.join(dir,'watches.json'),statePath:path.join(dir,'state.json'),eventsPath:path.join(dir,'events.json'),intervalMs:0};
  try{
    await fs.writeFile(options.watchesPath,JSON.stringify([{id:'bounded',targetUrl:'http://127.0.0.1:'+server.address().port}]));
    const first=await runWorker(options);
    assert.equal(first.ok,true);
    assert.equal(first.results[0].response_bytes,MAX_RESPONSE_BYTES);
    assert.equal(first.results[0].response_limit_bytes,MAX_RESPONSE_BYTES);
    const baseline=JSON.parse(await fs.readFile(options.statePath,'utf8')).bounded;
    assert.equal(baseline.last_value,crypto.createHash('sha256').update(exact).digest('hex'));
    for(mode of ['declared','chunked','gzip']){
      const failed=await runWorker(options);
      assert.equal(failed.ok,false,mode);
      assert.match(failed.results[0].error,/Decoded response exceeds 2097152 byte limit/);
      const state=JSON.parse(await fs.readFile(options.statePath,'utf8')).bounded;
      assert.equal(state.last_value,baseline.last_value);
      assert.equal(state.last_change_at,baseline.last_change_at);
      assert.equal(state.last_status,null);
      const [event,...remaining]=JSON.parse(await fs.readFile(options.eventsPath,'utf8'));
      assert.equal(event.type,'availability');assert.equal(event.availability,'unavailable');
      assert.equal(event.http_status,null);assert.deepEqual(remaining,[]);
    }
    mode='exact';
    assert.equal((await runWorker(options)).ok,true);
    const recovered=JSON.parse(await fs.readFile(options.statePath,'utf8')).bounded;
    assert.equal(recovered.last_error,null);assert.equal(recovered.last_value,baseline.last_value);
    const events=JSON.parse(await fs.readFile(options.eventsPath,'utf8'));
    assert.deepEqual(events.map(event=>[event.type,event.availability]),[['availability','unavailable'],['availability','healthy']]);
  }finally{server.closeAllConnections();server.close();await fs.rm(dir,{recursive:true,force:true});}
});

test('overflow cancels the response reader and never reads or hashes remaining body',async(t)=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-cancel-'));
  let reads=0,canceled=false,released=false;
  const reader={
    async read(){reads++;return {done:false,value:new Uint8Array(MAX_RESPONSE_BYTES+1)};},
    async cancel(){canceled=true;},
    releaseLock(){released=true;}
  };
  t.mock.method(globalThis,'fetch',async()=>({ok:true,status:200,body:{getReader:()=>reader}}));
  const options={watchesPath:path.join(dir,'watches.json'),statePath:path.join(dir,'state.json'),eventsPath:path.join(dir,'events.json'),intervalMs:0};
  try{
    await fs.writeFile(options.watchesPath,JSON.stringify([{id:'bounded',targetUrl:'http://fixture.invalid'}]));
    const report=await runWorker(options);
    assert.equal(report.ok,false);assert.equal(reads,1);assert.equal(canceled,true);assert.equal(released,true);
    assert.equal(JSON.parse(await fs.readFile(options.statePath,'utf8')).bounded.last_value,null);
  }finally{await fs.rm(dir,{recursive:true,force:true});}
});

import {reconcileWatch} from '../worker.mjs';

test('configuration controls metadata while only matching observations survive',()=>{
  const prior={id:'same',targetUrl:'https://example.com',kind:'change',label:'Old',status:'active',last_value:'hash',last_checked_at:100,last_change_at:90,last_status:200,last_error:null};
  const raw={id:'same',target_url:'https://example.com/',label:'New',status:'paused',last_value:'untrusted-config-hash'};
  const merged=reconcileWatch(raw,prior);
  assert.equal(merged.targetUrl,'https://example.com/');assert.equal(merged.label,'New');assert.equal(merged.status,'paused');
  assert.equal(merged.last_value,'hash');assert.equal(merged.last_checked_at,100);
  for(const changed of [{...raw,kind:'availability'},{...raw,target_url:'https://other.example/'}, {...raw,id:'different'}]){
    const reset=reconcileWatch(changed,prior);
    for(const field of ['last_value','last_checked_at','last_change_at','last_status','last_error']) assert.equal(reset[field],null);
  }
  assert.equal(reconcileWatch(raw,{...prior,targetUrl:'not a url'}).last_value,null);
  assert.equal(reconcileWatch(raw,undefined).last_value,null);
});

test('local retarget starts a fresh baseline; pause and reactivate honor current configuration',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-config-'));
  const hits={a:0,b:0};let bodyB='target-b';
  const server=http.createServer((req,res)=>{
    const target=req.url==='/a'?'a':'b';hits[target]++;
    res.end(target==='a'?'target-a':bodyB);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  const options={watchesPath:path.join(dir,'watches.json'),statePath:path.join(dir,'state.json'),eventsPath:path.join(dir,'events.json'),intervalMs:0};
  const configure=watch=>fs.writeFile(options.watchesPath,JSON.stringify([{id:'current',...watch}]));
  const state=async()=>JSON.parse(await fs.readFile(options.statePath,'utf8')).current;
  try{
    await configure({targetUrl:origin+'/a',label:'A'});
    assert.equal((await runWorker(options)).ok,true);
    const baseline=await state();
    await configure({targetUrl:origin+'/a',label:'Renamed'});
    const unchanged=await runWorker({...options,intervalMs:999999});
    assert.equal(unchanged.results[0].checked,false);assert.equal(hits.a,1);
    assert.equal((await state()).last_value,baseline.last_value);assert.equal((await state()).label,'Renamed');
    await configure({target_url:origin+'/b',label:'B'});
    const retargeted=await runWorker({...options,intervalMs:999999});
    assert.equal(retargeted.results[0].checked,true);assert.equal(retargeted.results[0].changed,false);
    assert.deepEqual(hits,{a:1,b:1});
    assert.equal((await state()).last_value,crypto.createHash('sha256').update('target-b').digest('hex'));
    assert.equal((await state()).last_change_at,null);
    assert.deepEqual(JSON.parse(await fs.readFile(options.eventsPath,'utf8')),[]);
    await configure({targetUrl:origin+'/b',status:'paused',label:'Paused B'});
    assert.equal((await runWorker(options)).results[0].checked,false);
    assert.equal((await state()).status,'paused');assert.equal(hits.b,1);
    bodyB='changed-b';
    await configure({targetUrl:origin+'/b',status:'active',label:'Active B'});
    const resumed=await runWorker(options);
    assert.equal(resumed.results[0].checked,true);assert.equal(resumed.results[0].changed,true);assert.equal(hits.b,2);
    const events=JSON.parse(await fs.readFile(options.eventsPath,'utf8'));
    assert.equal(events.length,1);assert.equal(events[0].label,'Active B');assert.equal(events[0].target_url,origin+'/b');
    await configure({targetUrl:origin+'/b',kind:'availability'});
    const newKind=await runWorker({...options,intervalMs:999999});
    assert.equal(newKind.results[0].checked,true);assert.equal(newKind.results[0].changed,false);
    assert.equal((await state()).kind,'availability');assert.equal((await state()).last_change_at,null);
    assert.equal(JSON.parse(await fs.readFile(options.eventsPath,'utf8')).length,1);
  }finally{server.closeAllConnections();server.close();await fs.rm(dir,{recursive:true,force:true});}
});
