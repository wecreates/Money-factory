import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import http from 'node:http';
import {acceptPodEvent} from './event-inbox.mjs';
import {createPodEventHandler} from './event-handler.mjs';
const key='s'.repeat(32),now=1800000000000,id='12b4c678-1234-4321-abcd-123456789abc';
function sign(eventId=id){
 const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:now,
  event:{id:eventId,kind:'pod.test.envelope',payload:{publication_enabled:false}}});
 return {payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};
}
test('event signatures require a primitive string with exactly 64 lowercase hex characters',async()=>{
 let connects=0;const pool={connect:async()=>{connects++;throw Error('UNEXPECTED_DATABASE_ACCESS');}},valid=sign();
 for(const signature of [[valid.signature],{value:valid.signature},null,123,true,
   valid.signature+'\n',valid.signature+'\r\n',valid.signature.slice(0,-1),valid.signature+'0',valid.signature.toUpperCase()]){
  await assert.rejects(acceptPodEvent(pool,{...valid,signature},key,()=>now),/EVENT_ENVELOPE_INVALID/);
  assert.equal(connects,0);
 }
});
test('signed event IDs require a primitive UUID string without a trailing line terminator',async()=>{
 let connects=0;const pool={connect:async()=>{connects++;throw Error('UNEXPECTED_DATABASE_ACCESS');}};
 for(const eventId of [[id],id+'\n',id+'\r',id+'\u2028',id+'\u2029',null,{},true]){
  await assert.rejects(acceptPodEvent(pool,sign(eventId),key,()=>now),/EVENT_SCOPE_INVALID/);
  assert.equal(connects,0);
 }
});
test('malformed signature types return HTTP 400 without claiming a receiver outage',async()=>{
 let connects=0;const pool={connect:async()=>{connects++;throw Error('UNEXPECTED_DATABASE_ACCESS');}};
 const server=http.createServer(createPodEventHandler({pool,key,clock:()=>now}));
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const post=envelope=>fetch('http://127.0.0.1:'+server.address().port,{method:'POST',
  headers:{'content-type':'application/json','idempotency-key':id},body:JSON.stringify(envelope)});
 try{
  const valid=sign();
  for(const signature of [[valid.signature],valid.signature+'\n']){
   const response=await post({...valid,signature});assert.equal(response.status,400);
   assert.deepEqual(await response.json(),{error:'EVENT_REJECTED'});assert.equal(connects,0);
  }
  const wrong=await post({...valid,signature:'0'.repeat(64)});assert.equal(wrong.status,401);
  assert.deepEqual(await wrong.json(),{error:'EVENT_REJECTED'});assert.equal(connects,0);
 }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
test('canonical signatures still admit lower- and uppercase UUID strings with unchanged hashes',async()=>{
 for(const eventId of [id,id.toUpperCase()]){
  let hash,stored,commits=0;
  const pool={connect:async()=>({release(){},async query(sql,args){
   if(sql.startsWith('INSERT')){hash=args[1];stored=args[2];}
   if(sql==='COMMIT')commits++;
   return sql.startsWith('SELECT')?{rows:[{event_sha256:hash}]}:{};
  }})};
  const envelope=sign(eventId);
  assert.deepEqual(await acceptPodEvent(pool,envelope,key,()=>now,{expectedEventId:eventId}),{accepted_event_id:eventId});
  assert.equal(commits,1);assert.equal(stored.id,eventId);
  assert.equal(hash,crypto.createHash('sha256').update(JSON.stringify(JSON.parse(envelope.payload).event)).digest('hex'));
 }
});
