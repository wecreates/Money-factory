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
