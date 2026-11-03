import test from 'node:test';
import assert from 'node:assert/strict';
import {enforceReleaseEconomics} from './economics.mjs';
import {economicsFixture} from './economics-fixture.mjs';

const now=5000000;
const baseJob={id:'fixture-job',business_id:'fixture-business',account_id:'fixture-account',
 platform:'redbubble',package_sha256:'a'.repeat(64)};

function observedProxy(value){
 let reads=0;
 return {value:new Proxy(value,{get(target,key,receiver){reads++;return Reflect.get(target,key,receiver);}}),reads:()=>reads};
}

const cases=[
 ['input Proxy',()=>{
  const observed=observedProxy(economicsFixture(baseJob,now));
  return {input:observed.value,job:baseJob,reads:observed.reads};
 }],
 ['price accessor',()=>{
  const input=economicsFixture(baseJob,now);let reads=0,price=input.price;
  Object.defineProperty(input,'price',{enumerable:true,get(){reads++;return price;}});
  return {input,job:baseJob,reads:()=>reads};
 }],
 ['economics Proxy',()=>{
  const input=economicsFixture(baseJob,now),observed=observedProxy(input.economics);
  input.economics=observed.value;
  return {input,job:baseJob,reads:observed.reads};
 }],
 ['job Proxy',()=>{
  const observed=observedProxy({...baseJob});
  return {input:economicsFixture(baseJob,now),job:observed.value,reads:observed.reads};
 }],
 ['source evidence accessor',()=>{
  const input=economicsFixture(baseJob,now);let reads=0,value=input.economics.source_evidence_ids[0];
  Object.defineProperty(input.economics.source_evidence_ids,'0',{enumerable:true,get(){reads++;return value;}});
  return {input,job:baseJob,reads:()=>reads};
 }]
];

for(const [name,make] of cases)test(`economic authority rejects executable ${name} without reading it`,()=>{
 const {input,job,reads}=make();
 assert.throws(()=>enforceReleaseEconomics(input,job,now),/AUTHORITY_SNAPSHOT_UNVERIFIED/);
 assert.equal(reads(),0);
});
