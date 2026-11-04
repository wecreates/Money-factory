import test from 'node:test';
import assert from 'node:assert/strict';
import {issuePodGrant} from './readiness-grant.mjs';

const key='authority-grant-signing-key-'.repeat(2),now=1800000000000;
const snapshot=()=>({
 key,now,
 job:{id:'job',business_id:'business',account_id:'account',platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH'},
 readiness:{businesses:[{id:'business',content_production_ready:true,max_mode:'PRELAUNCH',launch_content_allowed:false}]},
 approval:{job_id:'job',business_id:'business',account_id:'account',platform:'kdp',revoked:false,production_permission:true,
  publication_permission:false,expires_at_ms:now+60000,evidence_event_id:'approval'},
 verifiedFacts:{},forbiddenClaims:[],price:null,economics:null
});

for(const variant of [
 {name:'input Proxy',make(s,reads){return new Proxy(s,{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);}});}},
 {name:'top-level job accessor',make(s,reads){return Object.defineProperty({...s},'job',{enumerable:true,get(){reads.count++;return s.job;}});}},
 {name:'job Proxy',make(s,reads){return {...s,job:new Proxy(s.job,{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);}})};}},
 {name:'readiness businesses accessor',make(s,reads){return {...s,readiness:Object.defineProperty({},'businesses',{enumerable:true,get(){reads.count++;return s.readiness.businesses;}})};}},
 {name:'readiness toJSON function',make(s,reads){const readiness=s.readiness;return {...s,readiness:{...readiness,toJSON(){reads.count++;return readiness;}}};}},
 {name:'business toJSON function',make(s,reads){const business=s.readiness.businesses[0];return {...s,readiness:{businesses:[{...business,toJSON(){reads.count++;return business;}}]}};}},
 {name:'boxed readiness value toJSON function',make(s,reads){const note=new String('note');Object.defineProperty(note,'toJSON',{enumerable:true,value(){reads.count++;return 'note';}});return {...s,readiness:{...s.readiness,note}};}},
 {name:'boxed business value toJSON function',make(s,reads){const score=new Number(1);Object.defineProperty(score,'toJSON',{enumerable:true,value(){reads.count++;return 1;}});return {...s,readiness:{businesses:[{...s.readiness.businesses[0],score}]}};}},
 {name:'approval Proxy',make(s,reads){return {...s,approval:new Proxy(s.approval,{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);}})};}},
 {name:'verified facts Proxy',make(s,reads){return {...s,verifiedFacts:new Proxy(s.verifiedFacts,{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);},ownKeys(target){reads.count++;return Reflect.ownKeys(target);}})};}},
])test(`grant signer rejects executable ${variant.name} without invocation`,()=>{
 const reads={count:0};
 assert.throws(()=>issuePodGrant(variant.make(snapshot(),reads)),/AUTHORITY_SNAPSHOT_UNVERIFIED/);
 assert.equal(reads.count,0);
});

test('grant signer rejects boxed text beyond the snapshot budget before hashing',()=>{
 const s=snapshot();s.readiness.note=new String('x'.repeat(262145));
 assert.throws(()=>issuePodGrant(s),/AUTHORITY_SNAPSHOT_UNVERIFIED/);
});
