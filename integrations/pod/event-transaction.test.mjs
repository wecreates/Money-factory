import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {acceptPodEvent} from './event-inbox.mjs';

const key='test-only-event-transaction-key-'.repeat(2),now=1800000000000;
const event={id:'12b4c678-1234-4321-abcd-123456789abc',job_id:null,kind:'pod.test.transaction',payload:{},created_at:new Date(now).toISOString()};
const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:now,event});
const envelope={payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};
const hash=crypto.createHash('sha256').update(JSON.stringify(event)).digest('hex');
function fixture({failAt,rollbackFails=false}={}){
 const queries=[],releases=[],failure=Error('synthetic database failure');
 const pool={connect:async()=>({query:async sql=>{
  queries.push(sql);
  if(sql===failAt||failAt==='INSERT'&&sql.startsWith('INSERT'))throw failure;
  if(sql==='ROLLBACK'&&rollbackFails)throw Error('synthetic rollback failure');
  return {rows:[{event_sha256:hash}]};
 },release:bad=>releases.push(bad)})};
 return {pool,queries,releases,failure};
}
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
