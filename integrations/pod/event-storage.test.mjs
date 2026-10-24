import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import http from 'node:http';
import {acceptPodEvent} from './event-inbox.mjs';
import {createPodEventHandler} from './event-handler.mjs';
const key='u'.repeat(32),now=1800000000000,id='12b4c678-1234-4321-abcd-123456789abc';
const event=payload=>({id,job_id:null,kind:'pod.test.storage',payload,created_at:new Date(now).toISOString()});
const sign=event=>{const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:now,event});
 return {payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};};

for(const [name,text] of [['NUL','\u0000'],['high surrogate','\ud800'],['low surrogate','\udfff'],
 ['two high surrogates','\ud800\ud801'],['reversed pair','\udc00\ud800'],['embedded surrogate','valid\ud800text']]){
 test(`signed ${name} in keys or values cannot acquire a database client`,async()=>{
  let connects=0;const pool={connect:async()=>{connects++;throw Error('UNEXPECTED_DATABASE_ACCESS');}};
  for(const payload of [{note:text},{[text]:'value'},{nested:[{note:text}]}]){
   await assert.rejects(acceptPodEvent(pool,sign(event(payload)),key,()=>now),/EVENT_STORAGE_TEXT_INVALID/);
   assert.equal(connects,0);
  }
 });
}
test('event text validation follows signature authentication',async()=>{
 let connects=0;const pool={connect:async()=>{connects++;throw Error('UNEXPECTED_DATABASE_ACCESS');}};
 await assert.rejects(acceptPodEvent(pool,{...sign(event({note:'\u0000'})),signature:'0'.repeat(64)},key,()=>now),/EVENT_SIGNATURE_INVALID/);
 assert.equal(connects,0);
});
test('HTTP storage-invalid input is rejected without DB work; valid Unicode is stored without normalization',async()=>{
 let connects=0,stored,storedHash;
 const pool={connect:async()=>{connects++;return {release(){},async query(sql,args){
  if(sql.startsWith('INSERT')){stored=structuredClone(args[2]);storedHash=args[1];}
  return sql.startsWith('SELECT')?{rows:[{event_sha256:storedHash}]}:{};
 }};}};
 const server=http.createServer(createPodEventHandler({pool,key,clock:()=>now}));
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const post=e=>fetch('http://127.0.0.1:'+server.address().port,{method:'POST',
  headers:{'content-type':'application/json','idempotency-key':id},body:JSON.stringify(sign(e))});
 try{
  for(const bad of [event({note:'\u0000'}),event({'\udfff':'value'}),{...event({}),kind:'pod.test.\ud800'}]){
   const response=await post(bad);assert.equal(response.status,400);
   assert.deepEqual(await response.json(),{error:'EVENT_REJECTED'});assert.equal(connects,0);
  }
  const valid=event({'🖨️':'café e\u0301 😀 \u0001\t\n\r \\u0000',boundaries:['\ud800\udc00','\udbff\udfff'],nested:[true,null,42]});
  const response=await post(valid);assert.equal(response.status,200);assert.deepEqual(await response.json(),{accepted_event_id:id});
  assert.equal(connects,1);assert.deepEqual(stored,valid);
  assert.equal(storedHash,crypto.createHash('sha256').update(JSON.stringify(valid)).digest('hex'));
 }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
