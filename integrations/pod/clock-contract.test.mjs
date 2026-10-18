import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {issuePodGrant} from './readiness-grant.mjs';
import {acceptPodEvent} from './event-inbox.mjs';

const key='synthetic-clock-contract-key-'.repeat(2),now=1800000000000;
const job={id:'job',business_id:'b',account_id:'a',platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH'};
const readiness={businesses:[{id:'b',content_production_ready:true,max_mode:'PRELAUNCH'}]};
const approval={job_id:'job',business_id:'b',account_id:'a',platform:'kdp',revoked:false,
 production_permission:true,publication_permission:false,expires_at_ms:now+60000,evidence_event_id:'fixture'};
const issue=(clock,expiry=now+60000)=>issuePodGrant({key,job,readiness,approval:{...approval,expires_at_ms:expiry},now:clock});
const invalid=[NaN,Infinity,-1,0.5,now-0.5,now+0.5,Number.MAX_SAFE_INTEGER+1,null,'1800000000000',[],{valueOf:()=>now}];
test('grant issuer rejects invalid clocks before signing',()=>{
 for(const clock of invalid)assert.throws(()=>issue(clock),/AUTHORITY_CLOCK_INVALID/);
});
test('default grant clock is validated too',t=>{
 t.mock.method(Date,'now',()=>NaN);assert.throws(()=>issue(undefined),/AUTHORITY_CLOCK_INVALID/);
});
test('approval expiration must be nonnegative safe integer milliseconds',()=>{
 for(const expiry of invalid.concat(now,now-1))assert.throws(()=>issue(now,expiry),/APPROVAL_REQUIRED/);
});
test('grant timestamps preserve exact valid boundaries and the five-minute cap',()=>{
 for(const [clock,expiry,expected] of [[0,1,1],[now,now+600000,now+300000],
  [Number.MAX_SAFE_INTEGER-1,Number.MAX_SAFE_INTEGER,Number.MAX_SAFE_INTEGER]]){
  const p=JSON.parse(issue(clock,expiry).payload);assert.equal(p.issued_at_ms,clock);
  assert.equal(p.expires_at_ms,expected);assert.equal(p.publication_permission,false);
 }
});

const event={id:'12b4c678-1234-4321-abcd-123456789abc',kind:'pod.test.clock',payload:{}};
const hash=crypto.createHash('sha256').update(JSON.stringify(event)).digest('hex');
function signed(issued){
 const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:issued,event});
 return {payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};
}
function database(){
 const queries=[],releases=[];let connections=0;
 return {queries,releases,get connections(){return connections;},pool:{connect:async()=>{
  connections++;return {query:async sql=>{queries.push(sql);return {rows:[{event_sha256:hash}]};},release:bad=>releases.push(bad)};
 }}};
}
test('invalid inbox clocks cannot acquire a connection',async()=>{
 for(const clock of invalid){const f=database();await assert.rejects(acceptPodEvent(f.pool,signed(now),key,()=>clock),/EVENT_SCOPE_INVALID/);assert.equal(f.connections,0);}
});
test('signed invalid event timestamps cannot acquire a connection',async()=>{
 for(const issued of invalid){const f=database();await assert.rejects(acceptPodEvent(f.pool,signed(issued),key,()=>now),/EVENT_SCOPE_INVALID/);assert.equal(f.connections,0);}
 // Negative times used to pass with a negative clock; fractional times with a fractional clock.
 for(const issued of [-1,now+0.5,Number.MAX_SAFE_INTEGER+1]){const f=database();
  await assert.rejects(acceptPodEvent(f.pool,signed(issued),key,()=>issued),/EVENT_SCOPE_INVALID/);assert.equal(f.connections,0);}
});
test('clock becoming invalid during database waits rolls back and sends no acknowledgement',async()=>{
 for(const clock of invalid){const f=database();let calls=0;
  await assert.rejects(acceptPodEvent(f.pool,signed(now),key,()=>++calls===1?now:clock),/EVENT_SCOPE_INVALID/);
  assert.equal(calls,2);assert.equal(f.queries.at(-1),'ROLLBACK');assert.equal(f.queries.includes('COMMIT'),false);assert.deepEqual(f.releases,[false]);
 }
});
test('inbox preserves inclusive five-minute age and exact millisecond boundaries',async()=>{
 for(const [issued,current] of [[0,0],[0,300000],[now,now],[now,now+300000],[Number.MAX_SAFE_INTEGER,Number.MAX_SAFE_INTEGER]]){
  const f=database();assert.deepEqual(await acceptPodEvent(f.pool,signed(issued),key,()=>current),{accepted_event_id:event.id});assert.equal(f.queries.at(-1),'COMMIT');
 }
 for(const [issued,current] of [[now,now-1],[now,now+300001]]){const f=database();
  await assert.rejects(acceptPodEvent(f.pool,signed(issued),key,()=>current),/EVENT_SCOPE_INVALID/);assert.equal(f.connections,0);}
});
