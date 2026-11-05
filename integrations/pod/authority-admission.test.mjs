import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {EventEmitter} from 'node:events';
import {createPodAuthorityHandler} from './authority-handler.mjs';
const authKey='a'.repeat(32),signingKey='s'.repeat(32);
const snapshot=id=>({job:{id,business_id:'b',account_id:'a',platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH'},
 readiness:{businesses:[{id:'b',content_production_ready:true,max_mode:'PRELAUNCH'}]},
 approval:{job_id:id,business_id:'b',account_id:'a',platform:'kdp',revoked:false,production_permission:true,
  publication_permission:false,expires_at_ms:Date.now()+60000,evidence_event_id:'test-only'}});
const handler=(loadSnapshot,options={})=>createPodAuthorityHandler({authKey,signingKey,loadSnapshot,...options});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function invoke(handle,{destroyed=false}={}){
 const res=new EventEmitter();res.destroyed=destroyed;
 res.writeHead=status=>{res.status=status;};res.end=body=>{res.body=JSON.parse(body);res.writableEnded=true;};
 const req={method:'POST',headers:{authorization:'Bearer '+authKey,'content-type':'application/json'},
  destroy(){this.destroyed=true;},async *[Symbol.asyncIterator](){yield Buffer.from('{"job_id":"job"}');}};
 return {res,done:handle(req,res)};
}
async function server(t,handle){
 const server=http.createServer(handle);await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(async()=>{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));});
 return ()=>fetch('http://127.0.0.1:'+server.address().port,{method:'POST',
  headers:{authorization:'Bearer '+authKey,'content-type':'application/json'},body:'{"job_id":"job"}'});
}

test('HTTP timeouts retain shared loader capacity until actual settlement, then admit fresh work',async t=>{
 const pending=[];let calls=0,clockCalls=0,healthy=false;
 const loader=(id,{signal})=>{calls++;if(healthy)return snapshot(id);
  return new Promise((resolve,reject)=>pending.push({resolve,reject,signal}));};
 const options={snapshotTimeoutMs:30,clock:()=>{clockCalls++;return Date.now();}};
 const first=await server(t,handler(loader,options)),second=await server(t,handler(loader,options));
 try{
  const responses=await Promise.all(Array.from({length:32},()=>first()));
  for(const response of responses){assert.equal(response.status,409);assert.deepEqual(await response.json(),{error:'GRANT_BLOCKED'});}
  assert.equal(calls,32);assert.ok(pending.every(x=>x.signal.aborted));assert.equal(clockCalls,0);
  const overflow=await second();assert.equal(overflow.status,409);
  assert.deepEqual(await overflow.json(),{error:'GRANT_BLOCKED'});assert.equal(calls,32);
  // A different loader does not inherit this loader's occupied slots.
  const independent=invoke(handler(id=>snapshot(id)));await independent.done;assert.equal(independent.res.status,200);
  pending.shift().reject(Error('private backend failure'));await tick();healthy=true;
  const recovered=await second();assert.equal(recovered.status,200);assert.equal(calls,33);assert.equal(clockCalls,1);
  assert.equal(JSON.parse((await recovered.json()).payload).publication_permission,false);
  for(const work of pending)work.resolve(snapshot('job'));await tick();assert.equal(clockCalls,1);
 }finally{for(const work of pending)work.resolve(snapshot('job'));await tick();}
});

test('concurrent unresolved snapshots are capped before timeout and release slots on success',async()=>{
 const pending=[];let calls=0,healthy=false;
 const loader=id=>{calls++;return healthy?snapshot(id):new Promise(resolve=>pending.push(()=>resolve(snapshot(id))));};
 const handle=handler(loader,{snapshotTimeoutMs:1000});
 const jobs=Array.from({length:32},()=>invoke(handle));
 try{
  await tick();assert.equal(calls,32);
  const overflow=invoke(handle);await overflow.done;
  assert.equal(overflow.res.status,409);assert.equal(calls,32);
  for(const resolve of pending)resolve();await Promise.all(jobs.map(x=>x.done));
  for(const job of jobs)assert.equal(job.res.status,200);
  healthy=true;const retry=invoke(handle);await retry.done;assert.equal(retry.res.status,200);assert.equal(calls,33);
 }finally{for(const resolve of pending)resolve();await Promise.all(jobs.map(x=>x.done));}
});

test('concurrent slow authority bodies are capped before decoding and release capacity after settlement',async()=>{
 let calls=0;const loadSnapshot=id=>{calls++;return snapshot(id);};
 const handle=handler(loadSnapshot,{snapshotTimeoutMs:1000});
 const invokeBody=({blocked=false}={})=>{
  let release,enteredResolve;
  const entered=new Promise(resolve=>{enteredResolve=resolve;});
  const body=new Promise(resolve=>{release=resolve;});
  const res=new EventEmitter();
  res.writeHead=status=>{res.status=status;};
  res.end=value=>{res.body=JSON.parse(value);res.writableEnded=true;};
  const req={method:'POST',headers:{authorization:'Bearer '+authKey,'content-type':'application/json'},destroy(){this.destroyed=true;},
   async *[Symbol.asyncIterator](){enteredResolve();yield blocked?await body:Buffer.from('{"job_id":"job"}');}};
  return {done:handle(req,res),entered,release:()=>release?.(Buffer.from('{"job_id":"job"}')),res};
 };
 const occupied=Array.from({length:32},()=>invokeBody({blocked:true}));
 await Promise.all(occupied.map(request=>request.entered));
 const overflow=invokeBody();await overflow.done;
 for(const request of occupied)request.release();
 await Promise.all(occupied.map(request=>request.done));
 const recovered=invokeBody();await recovered.done;
 assert.equal(overflow.res.status,409);
 assert.deepEqual(overflow.res.body,{error:'GRANT_BLOCKED'});
 assert.equal(recovered.res.status,200);
 assert.equal(calls,33);
});

test('timed-out authority bodies retain admission until their reads actually settle',async t=>{
 const nativeSetTimeout=globalThis.setTimeout;let fast=true,calls=0;
 t.mock.method(globalThis,'setTimeout',(callback,ms,...args)=>{
  if(fast&&ms===5000){queueMicrotask(()=>callback(...args));return 0;}
  return nativeSetTimeout(callback,ms,...args);
 });
 const handle=handler(id=>{calls++;return snapshot(id);});
 const invokeBody=({blocked=false}={})=>{
  let release,enteredResolve;
  const entered=new Promise(resolve=>{enteredResolve=resolve;});
  const body=new Promise(resolve=>{release=resolve;});
  const res=new EventEmitter();
  res.writeHead=status=>{res.status=status;};
  res.end=value=>{res.body=JSON.parse(value);res.writableEnded=true;};
  const req={method:'POST',headers:{authorization:'Bearer '+authKey,'content-type':'application/json'},
   destroy(){this.destroyed=true;},
   async *[Symbol.asyncIterator](){enteredResolve();yield blocked?await body:Buffer.from('{"job_id":"job"}');}};
  return {done:handle(req,res),entered,release:()=>release?.(Buffer.from('{"job_id":"job"}')),res};
 };
 const occupied=Array.from({length:32},()=>invokeBody({blocked:true}));
 await Promise.all(occupied.map(request=>request.entered));
 await Promise.all(occupied.map(request=>request.done));
 const overflow=invokeBody();await overflow.done;
 assert.equal(overflow.res.status,409);assert.deepEqual(overflow.res.body,{error:'GRANT_BLOCKED'});assert.equal(calls,0);
 for(const request of occupied)request.release();
 await tick();await tick();fast=false;
 const recovered=invokeBody();await recovered.done;
 assert.equal(recovered.res.status,200);assert.equal(calls,1);
});

test('a throwing request destroy hook cannot strand timeout or permit late grant signing',async t=>{
 const nativeSetTimeout=globalThis.setTimeout;let callbackError,calls=0,release,enteredResolve;
 t.mock.method(globalThis,'setTimeout',(callback,ms,...args)=>{
  if(ms===5000){queueMicrotask(()=>{try{callback(...args);}catch(error){callbackError=error;}});return 0;}
  return nativeSetTimeout(callback,ms,...args);
 });
 const handle=handler(id=>{calls++;return snapshot(id);});
 const entered=new Promise(resolve=>{enteredResolve=resolve;});
 const body=new Promise(resolve=>{release=resolve;});
 const res=new EventEmitter();res.writeHead=status=>{res.status=status;};
 res.end=value=>{res.body=JSON.parse(value);res.writableEnded=true;};
 const req={method:'POST',headers:{authorization:'Bearer '+authKey,'content-type':'application/json'},
  destroy(){throw Error('wrapper destroy failed');},
  async *[Symbol.asyncIterator](){enteredResolve();yield await body;}};
 const done=handle(req,res);await entered;await tick();await tick();
 try{
  assert.equal(callbackError,undefined);
  assert.equal(res.status,409);assert.deepEqual(res.body,{error:'GRANT_BLOCKED'});assert.equal(calls,0);
 }finally{release(Buffer.from('{"job_id":"job"}'));await done;}
 await tick();assert.equal(calls,0);
});

test('client disconnects do not release unsettled loader slots or sign late snapshots',async()=>{
 const pending=[];let calls=0,clocks=0,healthy=false;
 const loader=(id,{signal})=>{calls++;return healthy?snapshot(id):new Promise(resolve=>pending.push({resolve,signal}));};
 const handle=handler(loader,{snapshotTimeoutMs:1000,clock:()=>{clocks++;return Date.now();}});
 const jobs=Array.from({length:32},()=>invoke(handle));
 try{
  await tick();assert.equal(calls,32);
  for(const job of jobs){job.res.destroyed=true;job.res.emit('close');}
  await Promise.all(jobs.map(x=>x.done));assert.ok(pending.every(x=>x.signal.aborted));assert.equal(clocks,0);
  const overflow=invoke(handle);await overflow.done;assert.equal(overflow.res.status,409);assert.equal(calls,32);
  for(const work of pending)work.resolve(snapshot('job'));await tick();assert.equal(clocks,0);
  healthy=true;const retry=invoke(handle);await retry.done;assert.equal(retry.res.status,200);assert.equal(clocks,1);
 }finally{for(const work of pending)work.resolve(snapshot('job'));await Promise.all(jobs.map(x=>x.done));}
});

test('pre-aborted requests, synchronous throws and asynchronous failures cannot leak admission slots',async()=>{
 let calls=0,healthy=false;
 const loader=id=>{calls++;if(healthy)return snapshot(id);if(calls%2)throw Error('private failure');return Promise.reject(Error('private failure'));};
 const handle=handler(loader);
 for(let i=0;i<40;i++){const request=invoke(handle,{destroyed:true});await request.done;}assert.equal(calls,0);
 for(let i=0;i<40;i++){const request=invoke(handle);await request.done;assert.equal(request.res.status,409);assert.deepEqual(request.res.body,{error:'GRANT_BLOCKED'});}
 assert.equal(calls,40);healthy=true;const request=invoke(handle);await request.done;
 assert.equal(request.res.status,200);assert.equal(calls,41);
});
