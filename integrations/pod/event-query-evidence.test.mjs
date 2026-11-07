import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {acceptPodEvent} from './event-inbox.mjs';

const key='test-only-event-query-evidence-key-'.repeat(2),now=1800000000000;
const event={id:'12b4c678-1234-4321-abcd-123456789abc',job_id:null,kind:'pod.test.query',payload:{},created_at:new Date(now).toISOString()};
const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:now,event});
const envelope={payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};
const hash=crypto.createHash('sha256').update(JSON.stringify(event)).digest('hex');

function fixture(wrap){
 const queries=[],releases=[];
 const client={async query(sql){
  queries.push(sql);
  const result={rows:[{event_sha256:hash}]};
  return sql.startsWith('SELECT')?wrap(result):sql==='COMMIT'?{command:'COMMIT'}:result;
 },release:discard=>releases.push(Boolean(discard))};
 return {pool:{connect:async()=>client},queries,releases};
}

function synchronousFixture(wrap){
 const queries=[],releases=[];
 const client={query(sql){
  queries.push(sql);
  const result={rows:[{event_sha256:hash}]};
  return sql.startsWith('SELECT')?wrap(result):sql==='COMMIT'?{command:'COMMIT'}:result;
 },release:discard=>releases.push(Boolean(discard))};
 return {pool:{connect:async()=>client},queries,releases};
}

for(const variant of [
 {name:'result rows accessor',wrap:(result,reads)=>Object.defineProperty({},'rows',{get(){reads.count++;return result.rows;}})},
 {name:'rows Proxy',wrap:(result,reads)=>({rows:new Proxy(result.rows,{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);}})})},
 {name:'row Proxy',wrap:(result,reads)=>({rows:[new Proxy(result.rows[0],{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);}})]})},
 {name:'field accessor',wrap:(result,reads)=>({rows:[Object.defineProperty({},'event_sha256',{enumerable:true,get(){reads.count++;return result.rows[0].event_sha256;}})]})},
])test(`event inbox rejects executable ${variant.name} without invocation`,async()=>{
 const reads={count:0},f=fixture(result=>variant.wrap(result,reads));
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),/EVENT_QUERY_UNVERIFIED/);
 assert.equal(reads.count,0);
 assert.equal(f.queries.at(-1),'ROLLBACK');
 assert.equal(f.queries.includes('COMMIT'),false);
 assert.deepEqual(f.releases,[false]);
});

test('event inbox does not invoke a synchronous query-result then accessor',async()=>{
 const reads={count:0},f=synchronousFixture(result=>Object.defineProperty(result,'then',{
  enumerable:true,get(){reads.count++;return undefined;}
 }));
 assert.deepEqual(await acceptPodEvent(f.pool,envelope,key,()=>now),{accepted_event_id:event.id});
 assert.equal(reads.count,0);
 assert.equal(f.queries.at(-1),'COMMIT');
 assert.deepEqual(f.releases,[false]);
});

test('event inbox does not let a synchronous query-result then function replace readback evidence',async()=>{
 const calls={count:0},f=synchronousFixture(result=>Object.defineProperty({},'then',{
  enumerable:true,value(resolve){calls.count++;resolve(result);}
 }));
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),/EVENT_QUERY_UNVERIFIED/);
 assert.equal(calls.count,0);
 assert.equal(f.queries.at(-1),'ROLLBACK');
 assert.equal(f.queries.includes('COMMIT'),false);
 assert.deepEqual(f.releases,[false]);
});

for(const variant of [
 {name:'sparse rows',wrap:()=>({rows:Array(1)})},
 {name:'oversized rows',wrap:result=>({rows:[...result.rows,...result.rows]})},
 {name:'extra field',wrap:result=>({rows:[{...result.rows[0],extra:true}]})},
 {name:'missing row',wrap:()=>({rows:[]})},
])test(`event inbox rejects ${variant.name} readback evidence`,async()=>{
 const f=fixture(variant.wrap);
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,()=>now),/EVENT_QUERY_UNVERIFIED/);
 assert.equal(f.queries.at(-1),'ROLLBACK');
 assert.equal(f.queries.includes('COMMIT'),false);
 assert.deepEqual(f.releases,[false]);
});
