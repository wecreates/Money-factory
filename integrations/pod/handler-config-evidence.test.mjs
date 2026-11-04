import test from 'node:test';
import assert from 'node:assert/strict';
import {createPodAuthorityHandler} from './authority-handler.mjs';
import {createPodEventHandler} from './event-handler.mjs';

const authKey='authority-config-auth-key-'.repeat(2);
const signingKey='authority-config-signing-key-'.repeat(2);
const eventKey='event-config-signing-key-'.repeat(2);
const authorityConfig=()=>({loadSnapshot:async()=>{},authKey,signingKey,clock:Date.now,snapshotTimeoutMs:5000});
const eventConfig=()=>({pool:{connect:async()=>{}},key:eventKey,clock:Date.now,timeoutMs:5000,connectionTimeoutMs:5000});

const proxy=(value,reads)=>new Proxy(value,{get(target,name,receiver){reads.count++;return Reflect.get(target,name,receiver);}});
const accessor=(value,name,reads)=>{
 const result={...value};
 Object.defineProperty(result,name,{enumerable:true,get(){reads.count++;return value[name];}});
 return result;
};
const inherited=value=>Object.assign(Object.create(value),{});
const callableProxy=(value,calls)=>new Proxy(value,{
 get(target,name,receiver){calls.get++;return Reflect.get(target,name,receiver);},
 apply(target,thisArg,args){calls.apply++;return Reflect.apply(target,thisArg,args);},
});

for(const variant of [
 {name:'configuration Proxy',make:proxy},
 ...['loadSnapshot','authKey','signingKey','clock','snapshotTimeoutMs'].map(name=>({name:`${name} accessor`,make:(value,reads)=>accessor(value,name,reads)})),
 {name:'configuration properties',make:value=>inherited(value)},
])test(`authority handler rejects executable or inherited ${variant.name} without invocation`,()=>{
 const reads={count:0};
 assert.throws(()=>createPodAuthorityHandler(variant.make(authorityConfig(),reads)),/AUTHORITY_CONFIG_INVALID/);
 assert.equal(reads.count,0);
});

for(const field of ['loadSnapshot','clock'])test(`authority handler rejects proxied ${field} capability without invocation`,()=>{
 const calls={get:0,apply:0},config=authorityConfig();
 config[field]=callableProxy(config[field],calls);
 assert.throws(()=>createPodAuthorityHandler(config),/AUTHORITY_CONFIG_INVALID/);
 assert.deepEqual(calls,{get:0,apply:0});
});

test('handlers preserve default timing for inert null-prototype configuration',()=>{
 const authority=Object.assign(Object.create(null),authorityConfig());
 delete authority.clock;delete authority.snapshotTimeoutMs;
 const receiver=Object.assign(Object.create(null),eventConfig());
 delete receiver.clock;delete receiver.timeoutMs;delete receiver.connectionTimeoutMs;
 assert.equal(typeof createPodAuthorityHandler(authority),'function');
 assert.equal(typeof createPodEventHandler(receiver),'function');
});

for(const variant of [
 {name:'configuration Proxy',make:proxy},
 ...['pool','key','clock','timeoutMs','connectionTimeoutMs'].map(name=>({name:`${name} accessor`,make:(value,reads)=>accessor(value,name,reads)})),
 {name:'configuration properties',make:value=>inherited(value)},
])test(`event handler rejects executable or inherited ${variant.name} without invocation`,()=>{
 const reads={count:0};
 assert.throws(()=>createPodEventHandler(variant.make(eventConfig(),reads)),/EVENT_HANDLER_CONFIG_INVALID/);
 assert.equal(reads.count,0);
});

test('event handler rejects proxied clock capability without invocation',()=>{
 const calls={get:0,apply:0},config=eventConfig();
 config.clock=callableProxy(config.clock,calls);
 assert.throws(()=>createPodEventHandler(config),/EVENT_HANDLER_CONFIG_INVALID/);
 assert.deepEqual(calls,{get:0,apply:0});
});
