import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import http from 'node:http';
import {acceptPodEvent} from './event-inbox.mjs';
import {createPodEventHandler} from './event-handler.mjs';

const key='test-only-pool-wait-key-'.repeat(2),now=1800000000000;
const event={id:'12b4c678-1234-4321-abcd-123456789abc',job_id:null,kind:'pod.test.pool_wait',payload:{},created_at:new Date(now).toISOString()};
const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:now,event});
const envelope={payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};
const hash=crypto.createHash('sha256').update(JSON.stringify(event)).digest('hex');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function fixture(){
 let resolve,reject;const queries=[],releases=[];
 let connected;const connecting=new Promise(yes=>{connected=yes;});
 const client={query:async sql=>{queries.push(sql);return {rows:[{event_sha256:hash}]};},release:bad=>releases.push(bad)};
 const pool={connect:()=>new Promise((yes,no)=>{resolve=yes;reject=no;connected();})};
 return {pool,client,queries,releases,connecting,resolve:()=>resolve(client),reject:()=>reject(Error('private backend failure'))};
}
const accept=pool=>acceptPodEvent(pool,envelope,key,()=>now,{connectionTimeoutMs:20});

test('a stalled pool wait rejects promptly and releases an eventual client without BEGIN',async()=>{
 const f=fixture();const pending=accept(f.pool).then(value=>({value}),error=>({error}));
 const observed=await Promise.race([pending,delay(200).then(()=>({stalled:true}))]);
 f.resolve();await pending;await delay(0);
 assert.equal(observed.error?.message,'EVENT_CONNECTION_TIMEOUT');
 assert.deepEqual(f.queries,[]);assert.equal(f.releases.length,1);assert.notEqual(f.releases[0],true);
});

test('late connection rejection is consumed after the caller times out',async()=>{
 const f=fixture();const pending=accept(f.pool).then(value=>({value}),error=>({error}));
 const observed=await Promise.race([pending,delay(200).then(()=>({stalled:true}))]);
 f.reject();await pending;await delay(0);
 assert.equal(observed.error?.message,'EVENT_CONNECTION_TIMEOUT');assert.deepEqual(f.queries,[]);
 assert.deepEqual(f.releases,[]);
});

for(const finishMs of [9,10,11])test(`pool completion at ${finishMs}ms observes a 10ms monotonic deadline`,async t=>{
 let elapsed=0;t.mock.method(performance,'now',()=>elapsed);
 const f=fixture(),pool={connect:async()=>{elapsed=finishMs;return f.client;}};
 const pending=acceptPodEvent(pool,envelope,key,()=>now,{connectionTimeoutMs:10});
 if(finishMs<10){assert.deepEqual(await pending,{accepted_event_id:event.id});assert.equal(f.queries.at(-1),'COMMIT');}
 else{await assert.rejects(pending,/^Error: EVENT_CONNECTION_TIMEOUT$/);assert.deepEqual(f.queries,[]);}
 assert.equal(f.releases.length,1);assert.notEqual(f.releases[0],true);
});

test('connection errors before the deadline preserve the cause and do not begin a transaction',async()=>{
 const error=Error('private test connection failure');
 await assert.rejects(accept({connect(){throw error;}}),caught=>caught===error);
});

test('invalid connection deadlines fail before asking the pool for a client',async()=>{
 for(const value of [0,-1,1.5,NaN,Infinity,30001,'20',null]){
  let connected=false;
  await assert.rejects(acceptPodEvent({connect(){connected=true;throw Error('unexpected connect');}},envelope,key,()=>now,
   {connectionTimeoutMs:value}),/EVENT_CONNECTION_CONFIG_INVALID/);
  assert.equal(connected,false);
 }
});

for(const dispatchDelayMs of [0,350])test(`HTTP pool timeout survives ${dispatchDelayMs}ms dispatch delay without early client release`,{timeout:10000},async()=>{
 const f=fixture();
 const handler=createPodEventHandler({pool:f.pool,key,clock:()=>now,connectionTimeoutMs:20});
 const server=http.createServer(async(req,res)=>{if(dispatchDelayMs)await delay(dispatchDelayMs);return handler(req,res);});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{
  const pending=fetch('http://127.0.0.1:'+server.address().port,{method:'POST',headers:{
   'content-type':'application/json','idempotency-key':event.id},body:JSON.stringify(envelope)});
  // Synchronize with actual acquisition, not wall-clock HTTP scheduling. The
  // test deadline reports a stalled handler without resolving the client early.
  await f.connecting;
  const response=await pending;
  f.resolve();await delay(0);
  assert.equal(response.status,503);
  assert.deepEqual(await response.json(),{error:'EVENT_RECEIVER_UNAVAILABLE'});
  assert.deepEqual(f.queries,[]);assert.equal(f.releases.length,1);
 }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});

test('HTTP construction rejects invalid connection wait budgets',()=>{
 for(const connectionTimeoutMs of [0,-1,1.5,NaN,Infinity,30001,'20',null])
  assert.throws(()=>createPodEventHandler({pool:{connect(){}},key,connectionTimeoutMs}),/EVENT_HANDLER_CONFIG_INVALID/);
});

test('invalid transaction deadlines fail before asking the pool for a client',async()=>{
 for(const value of [0,-1,1.5,NaN,Infinity,30001,'20',null]){
  let connected=false;
  await assert.rejects(acceptPodEvent({connect(){connected=true;throw Error('unexpected connect');}},envelope,key,()=>now,
   {transactionTimeoutMs:value}),/EVENT_TRANSACTION_CONFIG_INVALID/);
  assert.equal(connected,false);
 }
});

test('HTTP construction rejects invalid transaction budgets',()=>{
 for(const transactionTimeoutMs of [0,-1,1.5,NaN,Infinity,30001,'20',null])
  assert.throws(()=>createPodEventHandler({pool:{connect(){}},key,transactionTimeoutMs}),/EVENT_HANDLER_CONFIG_INVALID/);
});
