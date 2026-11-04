import test from 'node:test';
import assert from 'node:assert/strict';
import {signPodGrant} from './sign-grant.mjs';

const key='grant-envelope-signing-key-'.repeat(2);
const payload=()=>({schema_version:1,audience:'content-control:pod',job_id:'job',verified_facts:{source:'authority'}});

for(const variant of [
 {name:'payload Proxy',make(p,reads){return new Proxy(p,{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);}});}},
 {name:'schema accessor',make(p,reads){return Object.defineProperty({...p},'schema_version',{enumerable:true,get(){reads.count++;return 1;}});}},
 {name:'nested verified-facts Proxy',make(p,reads){return {...p,verified_facts:new Proxy(p.verified_facts,{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);},ownKeys(target){reads.count++;return Reflect.ownKeys(target);}})};}},
 {name:'nested field accessor',make(p,reads){return {...p,verified_facts:Object.defineProperty({},'source',{enumerable:true,get(){reads.count++;return 'authority';}})};}},
 {name:'toJSON accessor',make(p,reads){return Object.defineProperty({...p},'toJSON',{enumerable:true,get(){reads.count++;return ()=>p;}});}},
])test(`grant envelope signer rejects executable ${variant.name} without invocation`,()=>{
 const reads={count:0};
 assert.throws(()=>signPodGrant(variant.make(payload(),reads),key),/AUTHORITY_SNAPSHOT_UNVERIFIED/);
 assert.equal(reads.count,0);
});

test('grant envelope signer rejects unbounded property fanout',()=>{
 const p=payload();
 for(let index=0;index<8193;index++)p[`claim_${index}`]=index;
 assert.throws(()=>signPodGrant(p,key),/AUTHORITY_SNAPSHOT_UNVERIFIED/);
});

test('grant envelope signer rejects an oversized aggregate text budget',()=>{
 assert.throws(()=>signPodGrant({...payload(),claim:'x'.repeat(262145)},key),/AUTHORITY_SNAPSHOT_UNVERIFIED/);
});

test('grant envelope signer bounds escaped JSON text before HMAC',()=>{
 assert.throws(()=>signPodGrant({...payload(),claim:'\u0001'.repeat(43700)},key),/AUTHORITY_SNAPSHOT_UNVERIFIED/);
});

test('grant envelope signer retains bounded escaped JSON text',()=>{
 const claim='\u0001'.repeat(40000),signed=signPodGrant({...payload(),claim},key);
 assert.equal(JSON.parse(signed.payload).claim,claim);
});

test('grant envelope signer rejects negative zero before signing',()=>{
 assert.throws(()=>signPodGrant({...payload(),verified_facts:{score:-0}},key),/AUTHORITY_SNAPSHOT_UNVERIFIED/);
});

test('grant envelope signer retains canonical zero',()=>{
 const signed=signPodGrant({...payload(),verified_facts:{score:0}},key);
 assert.equal(JSON.parse(signed.payload).verified_facts.score,0);
});
