import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {EventEmitter} from 'node:events';
import {createPodEventHandler} from './event-handler.mjs';

const key='event-transaction-timeout-key-'.repeat(2);
const now=1800000000000;
const id='12b4c678-1234-4321-abcd-123456789abc';
const event={id,job_id:null,kind:'pod.test.transaction_timeout',payload:{},created_at:new Date(now).toISOString()};
const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:now,event});
const envelope={payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};
const hash=crypto.createHash('sha256').update(JSON.stringify(event)).digest('hex');

function request(){
 const req={method:'POST',headers:{'content-type':'application/json','idempotency-key':id},
  destroy(){this.destroyed=true;},async *[Symbol.asyncIterator](){yield Buffer.from(JSON.stringify(envelope));}};
 const res=new EventEmitter();
 res.writeHead=status=>{res.status=status;};
 res.end=body=>{res.body=JSON.parse(body);res.writableEnded=true;};
 return {req,res};
}

test('a stalled database query cannot retain receiver admission indefinitely',async()=>{
 const queries=[],releases=[];let stalled=true;
 const pool={connect:async()=>({
  query:sql=>{queries.push(sql);if(stalled&&sql!=="BEGIN")return new Promise(()=>{});
   if(sql==='COMMIT')return {command:'COMMIT'};
   return sql.startsWith('SELECT')?{rows:[{event_sha256:hash}]}:{};},
  release:discard=>releases.push(discard),
 })};
 const handle=createPodEventHandler({pool,key,clock:()=>now,connectionTimeoutMs:100,transactionTimeoutMs:10});
 const {req,res}=request();
 const pending=handle(req,res);
 const observed=await Promise.race([
  pending.then(()=>true),
  new Promise(resolve=>setTimeout(()=>resolve(false),100)),
 ]);
 assert.equal(observed,true,'receiver must settle after its database transaction deadline');
 assert.equal(res.status,503);
 assert.deepEqual(res.body,{error:'EVENT_RECEIVER_UNAVAILABLE'});
 assert.deepEqual(queries,['BEGIN',"SET LOCAL lock_timeout='2s'"]);
 assert.deepEqual(releases,[true],'uncertain client must be destroyed, not returned to the pool');
 stalled=false;
 const retry=request();await handle(retry.req,retry.res);
 assert.equal(retry.res.status,200,'settlement must release handler admission for a healthy retry');
 assert.deepEqual(retry.res.body,{accepted_event_id:id});
 assert.deepEqual(releases,[true,false]);
});

test('a rejected release after COMMIT withholds the redacted HTTP acknowledgement',async()=>{
 const queries=[],releases=[];
 const pool={connect:()=>({
  query:sql=>{queries.push(sql);return sql.startsWith('SELECT')?{rows:[{event_sha256:hash}]}:sql==='COMMIT'?{command:'COMMIT'}:{};},
  release:discard=>{releases.push(discard);return Promise.reject(Error('private release error'));},
 })};
 const handle=createPodEventHandler({pool,key,clock:()=>now});
 const {req,res}=request();await handle(req,res);
 assert.equal(res.status,503);assert.deepEqual(res.body,{error:'EVENT_RECEIVER_UNAVAILABLE'});
 assert.equal(queries.at(-1),'COMMIT');assert.deepEqual(releases,[false]);
});
test('an unverified commit produces a redacted HTTP failure and destroys the client',async()=>{
 const queries=[],releases=[];
 const pool={connect:()=>({
  query:sql=>{queries.push(sql);return sql.startsWith('SELECT')?{rows:[{event_sha256:hash}]}:sql==='COMMIT'?{command:'ROLLBACK'}:{};},
  release:discard=>releases.push(discard),
 })};
 const handle=createPodEventHandler({pool,key,clock:()=>now});
 const {req,res}=request();await handle(req,res);
 assert.equal(res.status,503);assert.deepEqual(res.body,{error:'EVENT_RECEIVER_UNAVAILABLE'});
 assert.equal(queries.at(-1),'COMMIT');assert.deepEqual(releases,[true]);
});
