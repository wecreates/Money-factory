import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import crypto from 'node:crypto';
import {createPodEventHandler} from './event-handler.mjs';
const key='e'.repeat(32),id='12b4c678-1234-4321-abcd-123456789abc',now=1800000000000;
function envelope(event={id,kind:'pod.production.review_required',payload:{publication_enabled:false}},issued=now){
 const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:issued,event});
 return {payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};
}
// In-memory transaction double: HTTP/security tests, not live database evidence.
function database(){
 const rows=new Map();let connects=0,commits=0,releases=0;
 return {rows,stats:()=>({connects,commits,releases}),connect:async()=>{connects++;return {
  query:async(sql,args)=>{
   if(sql==='COMMIT'){commits++;return {};}
   if(sql.startsWith('INSERT')){if(!rows.has(args[0]))rows.set(args[0],args[1]);return {};}
   if(sql.startsWith('SELECT'))return {rows:[{event_sha256:rows.get(args[0])}]};
   return {};
  },release:()=>{releases++;}
 };}};
}
async function serverFor(pool,run,clock=()=>now){
 const server=http.createServer(createPodEventHandler({pool,key,clock}));
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const url='http://127.0.0.1:'+server.address().port;
 const post=(body,headers={})=>fetch(url,{method:'POST',headers:{'content-type':'application/json','idempotency-key':id,...headers},body:typeof body==='string'?body:JSON.stringify(body)});
 try{await run(post,url);}finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
}
test('signed HTTP delivery acknowledges only after commit and deduplicates stable event IDs',async()=>{
 const pool=database();
 await serverFor(pool,async post=>{
  for(const issued of [now,now-1]){
   const response=await post(envelope(undefined,issued));assert.equal(response.status,200);
   assert.deepEqual(await response.json(),{accepted_event_id:id});
  }
  assert.equal(pool.rows.size,1);assert.deepEqual(pool.stats(),{connects:2,commits:2,releases:2});
  const response=await post(envelope({id,kind:'pod.published',payload:{}}));
  assert.equal(response.status,409);assert.equal(pool.stats().commits,2);assert.equal(pool.stats().releases,3);
 });
});
test('invalid signatures, stale claims, mismatched IDs and malformed requests never connect',async()=>{
 const pool=database();
 await serverFor(pool,async(post,url)=>{
  assert.equal((await post({...envelope(),signature:'0'.repeat(64)})).status,401);
  assert.equal((await post(envelope(undefined,now-300001))).status,400);
  assert.equal((await post(envelope(),{'idempotency-key':'aaaaaaaa-1234-4321-abcd-123456789abc'})).status,400);
  assert.equal((await post(envelope(),{'idempotency-key':'bad'})).status,400);
  assert.equal((await post('{bad')).status,400);
  assert.equal((await post({...envelope(),readiness:{max_mode:'LAUNCH'}})).status,400);
  assert.equal((await post(envelope(),{'content-type':'text/plain'})).status,415);
  assert.equal((await fetch(url)).status,405);
  assert.equal((await post('x'.repeat(524289))).status,413);
  assert.equal(pool.stats().connects,0);
 });
});
test('database failure does not leak details or acknowledge an event',async()=>{
 await serverFor({connect:async()=>{throw Error('password=private connection details');}},async post=>{
  const response=await post(envelope());assert.equal(response.status,503);
  assert.deepEqual(await response.json(),{error:'EVENT_RECEIVER_UNAVAILABLE'});
 });
});
test('missing database and weak receiver keys fail closed at construction',()=>{
 assert.throws(()=>createPodEventHandler({pool:database(),key:'weak'}),/CONFIG_INVALID/);
 assert.throws(()=>createPodEventHandler({key}),/CONFIG_INVALID/);
});
test('event expiring during database work is rolled back and never acknowledged over HTTP',async()=>{
 const base=database();let current=now,rollback=false;
 const pool={connect:async()=>{
  const c=await base.connect();return {release:()=>c.release(),query:async(sql,args)=>{
   const result=await c.query(sql,args);
   if(sql.startsWith('SELECT'))current=now+300001;
   if(sql==='ROLLBACK')rollback=true;
   return result;
  }};
 }};
 await serverFor(pool,async post=>{
  const response=await post(envelope());assert.equal(response.status,400);
  assert.deepEqual(await response.json(),{error:'EVENT_REJECTED'});
  assert.equal(base.stats().commits,0);assert.equal(rollback,true);assert.equal(base.stats().releases,1);
 },()=>current);
});
test('a non-callable clock is rejected before accepting requests',()=>{
 assert.throws(()=>createPodEventHandler({pool:database(),key,clock:now}),/CONFIG_INVALID/);
});
test('a nonfinite clock rejects the event before database access',async()=>{
 const pool=database();
 await serverFor(pool,async post=>{
  assert.equal((await post(envelope())).status,400);assert.equal(pool.stats().connects,0);
 },()=>NaN);
});
