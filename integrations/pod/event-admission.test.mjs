import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import http from 'node:http';
import {acceptPodEvent} from './event-inbox.mjs';
import {createPodEventHandler} from './event-handler.mjs';

const key='test-only-pool-admission-'.repeat(2),now=1800000000000;
const event={id:'12b4c678-1234-4321-abcd-123456789abc',job_id:null,kind:'pod.test.admission',payload:{},created_at:new Date(now).toISOString()};
const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:now,event});
const envelope={payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};
const hash=crypto.createHash('sha256').update(JSON.stringify(event)).digest('hex');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){
 const pending=[],queries=[],releases=[];
 const client={query:async sql=>{queries.push(sql);return {rows:[{event_sha256:hash}]};},release:()=>releases.push(true)};
 const pool={connect:()=>new Promise((resolve,reject)=>pending.push({resolve:()=>resolve(client),reject}))};
 return {pool,pending,queries,releases,resolveAll:()=>pending.forEach(p=>p.resolve())};
}
const accept=(pool,connectionTimeoutMs=10)=>acceptPodEvent(pool,envelope,key,()=>now,{connectionTimeoutMs});
async function fill(f){
 const settled=await Promise.allSettled(Array.from({length:32},()=>accept(f.pool)));
 assert.ok(settled.every(x=>x.status==='rejected'&&x.reason.message==='EVENT_CONNECTION_TIMEOUT'));
 assert.equal(f.pending.length,32);
}

test('timed-out waiters retain admission until their actual connection settles',async()=>{
 const f=fixture();
 try{
  await fill(f);
  for(let i=0;i<8;i++)await assert.rejects(accept(f.pool),/^Error: EVENT_CONNECTION_BUSY$/);
  assert.equal(f.pending.length,32,'overload must not call pool.connect');
  f.pending[0].resolve();await tick();
  assert.equal(f.releases.length,1);assert.deepEqual(f.queries,[]);
  await assert.rejects(accept(f.pool),/^Error: EVENT_CONNECTION_TIMEOUT$/);
  assert.equal(f.pending.length,33,'one settled waiter admits exactly one replacement');
  await assert.rejects(accept(f.pool),/^Error: EVENT_CONNECTION_BUSY$/);
 }finally{f.resolveAll();await tick();}
 assert.equal(f.releases.length,33);assert.deepEqual(f.queries,[]);
});

test('a late rejection frees admission and independent pools do not share the cap',async()=>{
 const f=fixture(),other=fixture();
 try{
  await fill(f);
  await assert.rejects(accept(other.pool),/^Error: EVENT_CONNECTION_TIMEOUT$/);
  assert.equal(other.pending.length,1);
  f.pending[0].reject(Error('private connection error'));await tick();
  await assert.rejects(accept(f.pool),/^Error: EVENT_CONNECTION_TIMEOUT$/);
  assert.equal(f.pending.length,33);
  await assert.rejects(accept(f.pool),/^Error: EVENT_CONNECTION_BUSY$/);
 }finally{f.resolveAll();other.resolveAll();await tick();}
 assert.equal(f.releases.length,32);assert.deepEqual(f.queries,[]);
});

test('on-time success and synchronous connection errors never leak admission',async()=>{
 const pool={connect:async()=>({query:async()=>({rows:[{event_sha256:hash}]}),release(){}})};
 for(let i=0;i<70;i++)assert.deepEqual(await accept(pool,1000),{accepted_event_id:event.id});
 const error=Error('private early error'),bad={connect(){throw error;}};
 for(let i=0;i<70;i++)await assert.rejects(accept(bad,1000),e=>e===error);
});

test('HTTP overload shares the pool limit and returns only the retryable public error',async()=>{
 const f=fixture();
 const server=http.createServer(createPodEventHandler({pool:f.pool,key,clock:()=>now,connectionTimeoutMs:10}));
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{
  await fill(f);
  const response=await fetch('http://127.0.0.1:'+server.address().port,{method:'POST',headers:{
   'content-type':'application/json','idempotency-key':event.id},body:JSON.stringify(envelope)});
  assert.equal(response.status,503);assert.deepEqual(await response.json(),{error:'EVENT_RECEIVER_UNAVAILABLE'});
  assert.equal(f.pending.length,32);assert.deepEqual(f.queries,[]);
 }finally{f.resolveAll();await tick();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
