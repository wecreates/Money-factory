import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {acceptPodEvent} from './event-inbox.mjs';
import {createPodEventHandler} from './event-handler.mjs';

const key='test-only-event-capability-key-'.repeat(2),now=1800000000000;
const event={id:'12b4c678-1234-4321-abcd-123456789abc',job_id:null,kind:'pod.test.capability',payload:{},created_at:new Date(now).toISOString()};
const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:now,event});
const envelope={payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};
const hash=crypto.createHash('sha256').update(JSON.stringify(event)).digest('hex');

function fixture(clientTransform=value=>value){
 const queries=[],releases=[];
 const client={async query(sql){
  queries.push(sql);
  if(sql.startsWith('SELECT'))return {rows:[{event_sha256:hash}]};
  return {};
 },release:discard=>releases.push(Boolean(discard))};
 return {pool:{connect:async()=>clientTransform(client)},client,queries,releases};
}

const callableProxy=(value,calls)=>new Proxy(value,{
 get(target,name,receiver){calls.get++;return Reflect.get(target,name,receiver);},
 apply(target,thisArg,args){calls.apply++;return Reflect.apply(target,thisArg,args);},
});
const ownBindAccessor=(value,reads)=>Object.defineProperty(value,'bind',{configurable:true,get(){
 reads.count++;return Function.prototype.bind;
}});

for(const variant of [
 {name:'pool Proxy',make(f,reads){return new Proxy(f.pool,{get(target,name,receiver){reads.count++;return Reflect.get(target,name,receiver);}});}},
 {name:'pool connect accessor',make(f,reads){return Object.defineProperty({},'connect',{get(){reads.count++;return f.pool.connect;}});}},
 {name:'client query accessor',make(f,reads){return {connect:async()=>Object.defineProperty({release:f.client.release},'query',{get(){reads.count++;return f.client.query;}})};}},
 {name:'client release accessor',make(f,reads){return {connect:async()=>Object.defineProperty({query:f.client.query},'release',{get(){reads.count++;return f.client.release;}})};}},
])test(`event inbox rejects executable ${variant.name} without invocation`,async()=>{
 const f=fixture(),reads={count:0},pool=variant.make(f,reads);
 await assert.rejects(acceptPodEvent(pool,envelope,key,()=>now),/EVENT_DATABASE_CAPABILITY_UNVERIFIED/);
 assert.equal(reads.count,0);
 assert.equal(f.queries.includes('COMMIT'),false);
});

for(const variant of [
 {name:'pool Proxy',make(f,reads){return new Proxy(f.pool,{get(target,name,receiver){reads.count++;return Reflect.get(target,name,receiver);}});}},
 {name:'pool connect accessor',make(f,reads){return Object.defineProperty({},'connect',{get(){reads.count++;return f.pool.connect;}});}},
])test(`event handler rejects executable ${variant.name} during construction without invocation`,()=>{
 const f=fixture(),reads={count:0},pool=variant.make(f,reads);
 assert.throws(()=>createPodEventHandler({pool,key,clock:()=>now}),/EVENT_DATABASE_CAPABILITY_UNVERIFIED/);
 assert.equal(reads.count,0);
});

test('event handler rejects proxied pool connect capability without invocation',()=>{
 const f=fixture(),calls={get:0,apply:0};
 f.pool.connect=callableProxy(f.pool.connect,calls);
 assert.throws(()=>createPodEventHandler({pool:f.pool,key,clock:()=>now}),/EVENT_DATABASE_CAPABILITY_UNVERIFIED/);
 assert.deepEqual(calls,{get:0,apply:0});
});

test('event handler binds pool connect without invoking its own bind accessor',()=>{
 const f=fixture(),reads={count:0};ownBindAccessor(f.pool.connect,reads);
 assert.equal(typeof createPodEventHandler({pool:f.pool,key,clock:()=>now}),'function');
 assert.equal(reads.count,0);
});

test('event inbox does not invoke a synchronous client then accessor',async()=>{
 const f=fixture(),reads={count:0};
 const client=Object.defineProperty(f.client,'then',{configurable:true,get(){reads.count++;return undefined;}});
 const pool={connect:()=>client};
 assert.deepEqual(await acceptPodEvent(pool,envelope,key,()=>now),{accepted_event_id:event.id});
 assert.equal(reads.count,0);
 assert.equal(f.queries.includes('COMMIT'),true);
});

test('event inbox does not let a synchronous client then function replace the capability source',async()=>{
 const f=fixture(),calls={count:0};
 const client=Object.defineProperty({},'then',{value(resolve){calls.count++;resolve(f.client);}});
 const pool={connect:()=>client};
 await assert.rejects(acceptPodEvent(pool,envelope,key,()=>now),/EVENT_DATABASE_CAPABILITY_UNVERIFIED/);
 assert.equal(calls.count,0);
 assert.equal(f.queries.includes('COMMIT'),false);
});

for(const name of ['query','release'])test(`event inbox rejects proxied client ${name} capability without invocation`,async()=>{
 const f=fixture(),calls={get:0,apply:0};
 const pool={connect:async()=>{
  f.client[name]=callableProxy(f.client[name],calls);
  return f.client;
 }};
 await assert.rejects(acceptPodEvent(pool,envelope,key,()=>now),/EVENT_DATABASE_CAPABILITY_UNVERIFIED/);
 assert.deepEqual(calls,{get:0,apply:0});
 assert.equal(f.queries.includes('COMMIT'),false);
});

for(const name of ['query','release'])test(`event inbox binds client ${name} without invoking its own bind accessor`,async()=>{
 const f=fixture(),reads={count:0};ownBindAccessor(f.client[name],reads);
 assert.deepEqual(await acceptPodEvent(f.pool,envelope,key,()=>now),{accepted_event_id:event.id});
 assert.equal(reads.count,0);
 assert.equal(f.queries.includes('COMMIT'),true);
});

test('event inbox rejects proxied clock capability without invocation',async()=>{
 const f=fixture(),calls={get:0,apply:0},clock=callableProxy(()=>now,calls);
 await assert.rejects(acceptPodEvent(f.pool,envelope,key,clock),/EVENT_CLOCK_INVALID/);
 assert.deepEqual(calls,{get:0,apply:0});
 assert.deepEqual(f.queries,[]);
});
