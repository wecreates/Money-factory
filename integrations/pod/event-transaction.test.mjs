import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {acceptPodEvent} from './event-inbox.mjs';

const key='test-only-event-transaction-key-'.repeat(2),now=1800000000000;
const event={id:'12b4c678-1234-4321-abcd-123456789abc',job_id:null,kind:'pod.test.transaction',payload:{},created_at:new Date(now).toISOString()};
const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:now,event});
const envelope={payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};
const hash=crypto.createHash('sha256').update(JSON.stringify(event)).digest('hex');
function fixture({failAt,rollbackFails=false,release,beginResult=()=>({command:'BEGIN'}),commitResult=()=>({command:'COMMIT'}),rollbackResult=()=>({command:'ROLLBACK'})}={}){
 const queries=[],releases=[],failure=Error('synthetic database failure');
 const pool={connect:async()=>({query:async sql=>{
  queries.push(sql);
  if(sql===failAt||failAt==='INSERT'&&sql.startsWith('INSERT'))throw failure;
  if(sql==='ROLLBACK'&&rollbackFails)throw Error('synthetic rollback failure');
  if(sql==='ROLLBACK')return rollbackResult();
  if(sql==='BEGIN')return beginResult();
  if(sql==='COMMIT')return commitResult();
  return {rows:[{event_sha256:hash,event_matches:true}]};
 },release:bad=>{releases.push(bad);return release?.();}})};
 return {pool,queries,releases,failure};
}
test('inbox discards unverified rollback without acknowledging or replacing the failure',async()=>{
 let reads=0;
 for(const result of [{command:'SELECT'},undefined,{},Object.create({command:'ROLLBACK'}),
  Object.assign([],{command:'ROLLBACK'}),{get command(){reads++;throw Error('private command getter');}},
  new Proxy({command:'ROLLBACK'},{getOwnPropertyDescriptor(){reads++;throw Error('private descriptor trap');}})]){
  const f=fixture({failAt:'INSERT',rollbackResult:()=>result});
  await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),e=>e===f.failure);
  assert.equal(f.queries.at(-1),'ROLLBACK');assert.equal(f.queries.includes('COMMIT'),false);
  assert.deepEqual(f.releases,[true]);
 }
 assert.equal(reads,0);
});
test('inbox will not write or reuse a connection after unverified BEGIN',async()=>{
 let reads=0;
 for(const result of [{command:'SELECT'},null,{},Object.create({command:'BEGIN'}),
  Object.assign([],{command:'BEGIN'}),{get command(){reads++;throw Error('private command getter');}},
  new Proxy({command:'BEGIN'},{getOwnPropertyDescriptor(){reads++;throw Error('private descriptor trap');}})]){
  const f=fixture({beginResult:()=>result});
  await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),/^Error: EVENT_BEGIN_UNVERIFIED$/);
  assert.deepEqual(f.queries,['BEGIN']);assert.deepEqual(f.releases,[true]);
 }
 assert.equal(reads,0);
});
test('resolved but unverified COMMIT cannot acknowledge or reuse its client',async()=>{
 let reads=0;
 for(const result of [{command:'ROLLBACK'},null,{},Object.create({command:'COMMIT'}),
  {command:['COMMIT']},Object.assign([],{command:'COMMIT'}),{get command(){reads++;throw Error('private command getter');}},
  new Proxy({command:'COMMIT'},{getOwnPropertyDescriptor(){reads++;throw Error('private descriptor trap');}})]){
  const f=fixture({commitResult:()=>result});
  await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),/^Error: EVENT_COMMIT_UNVERIFIED$/);
  assert.equal(f.queries.at(-1),'COMMIT');assert.equal(f.queries.includes('ROLLBACK'),false);
  assert.deepEqual(f.releases,[true]);
 }
 assert.equal(reads,0);
});
test('inbox awaits asynchronous client cleanup before acknowledging a committed event',{timeout:1000},async()=>{
 let resolve,started;const releasing=new Promise(yes=>{started=yes;});
 const f=fixture({release:()=>new Promise(yes=>{resolve=yes;started();})});
 let acknowledged=false;
 const pending=acceptPodEvent(f.pool,envelope,key,()=>now).then(value=>{acknowledged=true;return value;});
 await releasing;await new Promise(yes=>setImmediate(yes));
 try{assert.equal(acknowledged,false);assert.equal(f.queries.at(-1),'COMMIT');}
 finally{resolve();await pending;}
 assert.deepEqual(await pending,{accepted_event_id:event.id});assert.deepEqual(f.releases,[false]);
});
test('inbox rejects a backwards pre-commit clock even within the signed window',async()=>{
 const f=fixture();let reads=0;
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now+(++reads===1?10:9)),{message:'EVENT_SCOPE_INVALID'});
 assert.equal(f.queries.at(-1),'ROLLBACK');assert.equal(f.queries.includes('COMMIT'),false);
 assert.deepEqual(f.releases,[false]);
});
for(const [name,late] of [['expired',now+300001],['regressed',now+9],['invalid',NaN]])
 test(`inbox withholds a committed acknowledgement when its cleanup clock is ${name}`,async()=>{
  let wall=now+10;
  const f=fixture({release:async()=>{await Promise.resolve();wall=late;}});
  await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>wall),{message:'EVENT_SCOPE_INVALID'});
  assert.equal(f.queries.at(-1),'COMMIT');assert.equal(f.queries.includes('ROLLBACK'),false);
  assert.deepEqual(f.releases,[false]);
 });
test('inbox checks the transaction deadline again after its final clock read',async t=>{
 let elapsed=0,reads=0;t.mock.method(performance,'now',()=>elapsed);
 const f=fixture();
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>{if(++reads===3)elapsed=10;return now;},
  {transactionTimeoutMs:10}),{message:'EVENT_TRANSACTION_TIMEOUT'});
 assert.equal(f.queries.at(-1),'COMMIT');assert.deepEqual(f.releases,[false]);
});
test('inbox still acknowledges at the exact signed-window boundary after cleanup',async()=>{
 let wall=now;
 const f=fixture({release:()=>{wall=now+300000;}});
 assert.deepEqual(await acceptPodEvent(f.pool,envelope,key,()=>wall),{accepted_event_id:event.id});
 assert.deepEqual(f.releases,[false]);
});
for(const mode of ['reject','stall'])test(`inbox does not acknowledge after ${mode} during asynchronous cleanup`,{timeout:1000},async()=>{
 const error=Error('private release error');
 const f=fixture({release:()=>{
  if(mode==='stall')return new Promise(()=>{});
  const rejected=Promise.reject(error);rejected.catch(()=>{});return rejected;
 }});
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now,{transactionTimeoutMs:35}),
  mode==='stall'?/^Error: EVENT_TRANSACTION_TIMEOUT$/:/^Error: EVENT_RELEASE_UNVERIFIED$/);
 assert.equal(f.queries.at(-1),'COMMIT');assert.deepEqual(f.releases,[false]);
});
test('release rejection after rollback preserves the original transaction failure',async()=>{
 const f=fixture({failAt:'INSERT',release:()=>Promise.reject(Error('private cleanup failure'))});
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),error=>error===f.failure);
 assert.equal(f.queries.at(-1),'ROLLBACK');assert.deepEqual(f.releases,[false]);
});
test('a synchronous release ending at the transaction deadline cannot acknowledge',async t=>{
 let elapsed=0;t.mock.method(performance,'now',()=>elapsed);
 const f=fixture({release:()=>{elapsed=10;}});
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now,{transactionTimeoutMs:10}),/^Error: EVENT_TRANSACTION_TIMEOUT$/);
 assert.equal(f.queries.at(-1),'COMMIT');assert.deepEqual(f.releases,[false]);
});
test('release cannot use an executable thenable to manufacture acknowledgement',async()=>{
 let reads=0;
 const f=fixture({release:()=>({get then(){reads++;throw Error('private then getter');}})});
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),/^Error: EVENT_RELEASE_UNVERIFIED$/);
 assert.equal(reads,0);assert.deepEqual(f.releases,[false]);
});
test('inbox deadlines precede writes and successful commit returns a reusable connection',async()=>{
 const f=fixture();assert.deepEqual(await acceptPodEvent(f.pool,envelope,key,()=>now),{accepted_event_id:event.id});
 assert.deepEqual(f.queries.slice(0,3),['BEGIN',"SET LOCAL lock_timeout='2s'","SET LOCAL statement_timeout='10s'"]);
 assert.equal(f.queries.at(-1),'COMMIT');assert.deepEqual(f.releases,[false]);
});
test('failed rollback discards the connection and preserves the original failure',async()=>{
 const f=fixture({failAt:'INSERT',rollbackFails:true});
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),error=>error===f.failure);
 assert.equal(f.queries.at(-1),'ROLLBACK');assert.equal(f.queries.includes('COMMIT'),false);
 assert.deepEqual(f.releases,[true]);
});
test('successful rollback returns the connection without acknowledging delivery',async()=>{
 const f=fixture({failAt:'INSERT'});
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),error=>error===f.failure);
 assert.equal(f.queries.at(-1),'ROLLBACK');assert.equal(f.queries.includes('COMMIT'),false);
 assert.equal(f.releases.length,1);assert.notEqual(f.releases[0],true);
});
test('deadline setup failure rolls back before writing any inbox row',async()=>{
 const f=fixture({failAt:"SET LOCAL statement_timeout='10s'"});
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),error=>error===f.failure);
 assert.equal(f.queries.some(sql=>sql.startsWith('INSERT')),false);
 assert.equal(f.queries.at(-1),'ROLLBACK');assert.deepEqual(f.releases,[false]);
});
for(const rollbackFails of [false,true])test(`failed inbox transaction open discards without rollback: ${rollbackFails}`,async()=>{
 const f=fixture({failAt:'BEGIN',rollbackFails});
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),error=>error===f.failure);
 assert.deepEqual(f.queries,['BEGIN']);
 assert.deepEqual(f.releases,[true]);
});
for(const rollbackFails of [false,true])test(`failed inbox commit discards without rollback: ${rollbackFails}`,async()=>{
 const f=fixture({failAt:'COMMIT',rollbackFails});
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),error=>error===f.failure);
 assert.equal(f.queries.at(-1),'COMMIT');
 assert.equal(f.queries.includes('ROLLBACK'),false);
 assert.deepEqual(f.releases,[true]);
});

