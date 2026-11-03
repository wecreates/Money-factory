import crypto from 'node:crypto';
import test from 'node:test';
import assert from 'node:assert/strict';
import {acceptPodEvent} from './event-inbox.mjs';

const key='k'.repeat(48),payload='{}';
const signature=crypto.createHmac('sha256',key).update(payload).digest('hex');
const pool={connect(){throw Error('MUST_NOT_CONNECT');}};

function observedProxy(value){
 let reads=0;
 return {value:new Proxy(value,{get(target,name,receiver){reads++;return Reflect.get(target,name,receiver);}}),reads:()=>reads};
}

const cases=[
 ['envelope Proxy','EVENT_ENVELOPE_INVALID',()=>{
  const observed=observedProxy({payload,signature});
  return {envelope:observed.value,options:undefined,reads:observed.reads};
 }],
 ['payload accessor','EVENT_ENVELOPE_INVALID',()=>{
  let reads=0;const envelope={signature};
  Object.defineProperty(envelope,'payload',{enumerable:true,get(){reads++;return payload;}});
  return {envelope,options:undefined,reads:()=>reads};
 }],
 ['signature accessor','EVENT_ENVELOPE_INVALID',()=>{
  let reads=0;const envelope={payload};
  Object.defineProperty(envelope,'signature',{enumerable:true,get(){reads++;return signature;}});
  return {envelope,options:undefined,reads:()=>reads};
 }],
 ['options Proxy','EVENT_CONNECTION_CONFIG_INVALID',()=>{
  const observed=observedProxy({connectionTimeoutMs:5000});
  return {envelope:{payload,signature},options:observed.value,reads:observed.reads};
 }],
 ['connection timeout accessor','EVENT_CONNECTION_CONFIG_INVALID',()=>{
  let reads=0,options={};
  Object.defineProperty(options,'connectionTimeoutMs',{enumerable:true,get(){reads++;return 5000;}});
  return {envelope:{payload,signature},options,reads:()=>reads};
 }]
];

for(const [name,code,make] of cases)test(`event inbox rejects executable ${name} without invocation`,async()=>{
 const {envelope,options,reads}=make();
 await assert.rejects(acceptPodEvent(pool,envelope,key,Date.now,options),new RegExp(code));
 assert.equal(reads(),0);
});
