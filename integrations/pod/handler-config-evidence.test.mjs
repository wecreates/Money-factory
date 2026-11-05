import test from 'node:test';
import assert from 'node:assert/strict';
import {createPodAuthorityHandler} from './authority-handler.mjs';
import {createPodEventHandler} from './event-handler.mjs';
import {exactHandlerConfig} from './handler-config.mjs';

const authKey='authority-config-auth-key-'.repeat(2);
const signingKey='authority-config-signing-key-'.repeat(2);
const eventKey='event-config-signing-key-'.repeat(2);
const authorityConfig=()=>({loadSnapshot:async()=>{},authKey,signingKey,clock:Date.now,snapshotTimeoutMs:5000});
const eventConfig=()=>({pool:{connect:async()=>{}},key:eventKey,clock:Date.now,timeoutMs:5000,connectionTimeoutMs:5000,transactionTimeoutMs:15000});

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
 ['fields Proxy',reads=>({fields:new Proxy(['key'],{get(target,name,receiver){reads.count++;return Reflect.get(target,name,receiver);}}),defaults:{},errorCode:'CONFIG_INVALID'})],
 ['field accessor',reads=>{const fields=['key'];Object.defineProperty(fields,'0',{get(){reads.count++;return 'key';}});return {fields,defaults:{},errorCode:'CONFIG_INVALID'};}],
 ['defaults Proxy',reads=>({fields:['key'],defaults:new Proxy({key:'default'},{
  getOwnPropertyDescriptor(target,name){reads.count++;return Reflect.getOwnPropertyDescriptor(target,name);},
  get(target,name,receiver){reads.count++;return Reflect.get(target,name,receiver);}
 }),errorCode:'CONFIG_INVALID'})],
 ['default accessor',reads=>{const defaults={};Object.defineProperty(defaults,'key',{get(){reads.count++;return 'default';}});return {fields:['key'],defaults,errorCode:'CONFIG_INVALID'};}],
 ['error-code coercion',reads=>({fields:['key'],defaults:{},errorCode:{toString(){reads.count++;return 'CONFIG_INVALID';}},config:null})],
])test(`shared handler config boundary rejects executable ${variant[0]} without invocation`,()=>{
 const reads={count:0},args=variant[1](reads);
 const config=Object.hasOwn(args,'config')?args.config:{};
 assert.throws(()=>exactHandlerConfig(config,args.fields,args.defaults,args.errorCode),
  {message:'HANDLER_CONFIG_ARGUMENTS_INVALID'});
 assert.equal(reads.count,0);
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
 delete receiver.clock;delete receiver.timeoutMs;delete receiver.connectionTimeoutMs;delete receiver.transactionTimeoutMs;
 assert.equal(typeof createPodAuthorityHandler(authority),'function');
 assert.equal(typeof createPodEventHandler(receiver),'function');
});

for(const variant of [
 {name:'configuration Proxy',make:proxy},
 ...['pool','key','clock','timeoutMs','connectionTimeoutMs','transactionTimeoutMs'].map(name=>({name:`${name} accessor`,make:(value,reads)=>accessor(value,name,reads)})),
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

for(const [name,make] of [
 ['unknown string field',config=>({...config,transactionTimeuotMs:10})],
 ['unknown non-enumerable field',config=>{
  Object.defineProperty(config,'transactionTimeuotMs',{value:10});return config;
 }],
 ['unknown symbol field',config=>{
  Object.defineProperty(config,Symbol('transactionTimeoutMs'),{value:10});return config;
 }],
])test(`handlers reject ${name} instead of silently applying defaults`,()=>{
 assert.throws(()=>createPodAuthorityHandler(make(authorityConfig())),/AUTHORITY_CONFIG_INVALID/);
 assert.throws(()=>createPodEventHandler(make(eventConfig())),/EVENT_HANDLER_CONFIG_INVALID/);
});
