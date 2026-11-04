import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {createPodAuthorityHandler} from './authority-handler.mjs';

const authKey='authority-snapshot-auth-key-'.repeat(2),signingKey='authority-snapshot-signing-key-'.repeat(2),now=1800000000000;
const snapshot=()=>({
 job:{id:'job',business_id:'business',account_id:'account',platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH'},
 readiness:{businesses:[{id:'business',content_production_ready:true,max_mode:'PRELAUNCH',launch_content_allowed:false}]},
 approval:{job_id:'job',business_id:'business',account_id:'account',platform:'kdp',revoked:false,production_permission:true,
  publication_permission:false,expires_at_ms:now+60000,evidence_event_id:'approval'},
 verifiedFacts:{},forbiddenClaims:[],price:null,economics:null
});

async function invoke(value){
 const handle=createPodAuthorityHandler({authKey,signingKey,clock:()=>now,loadSnapshot:()=>value});
 const res=new EventEmitter();
 res.writeHead=status=>{res.status=status;};res.end=body=>{res.body=JSON.parse(body);res.writableEnded=true;};
 const req={method:'POST',headers:{authorization:'Bearer '+authKey,'content-type':'application/json'},
  destroy(){this.destroyed=true;},async *[Symbol.asyncIterator](){yield Buffer.from('{"job_id":"job"}');}};
 await handle(req,res);return res;
}

for(const variant of [
 {name:'top-level then accessor',make(s,reads){return Object.defineProperty({...s},'then',{enumerable:true,get(){reads.count++;return undefined;}});}},
 {name:'top-level then function',make(s,reads){return Object.defineProperty({...s},'then',{enumerable:true,value(resolve){reads.count++;resolve(snapshot());}});}},
 {name:'top-level job accessor',make(s,reads){return Object.defineProperty({...s},'job',{enumerable:true,get(){reads.count++;return s.job;}});}},
 {name:'job Proxy',make(s,reads){return {...s,job:new Proxy(s.job,{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);}})};}},
 {name:'job field accessor',make(s,reads){return {...s,job:Object.defineProperty({...s.job},'business_id',{enumerable:true,get(){reads.count++;return s.job.business_id;}})};}},
 {name:'top-level readiness accessor',make(s,reads){return Object.defineProperty({...s},'readiness',{enumerable:true,get(){reads.count++;return s.readiness;}});}},
 {name:'readiness Proxy',make(s,reads){return {...s,readiness:new Proxy(s.readiness,{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);}})};}},
 {name:'businesses accessor',make(s,reads){return {...s,readiness:Object.defineProperty({},'businesses',{enumerable:true,get(){reads.count++;return s.readiness.businesses;}})};}},
 {name:'approval Proxy',make(s,reads){return {...s,approval:new Proxy(s.approval,{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);}})};}},
 {name:'verified facts Proxy',make(s,reads){return {...s,verifiedFacts:new Proxy(s.verifiedFacts,{get(target,key,receiver){reads.count++;return Reflect.get(target,key,receiver);},ownKeys(target){reads.count++;return Reflect.ownKeys(target);}})};}},
])test(`authority rejects executable ${variant.name} without invocation`,async()=>{
 const reads={count:0},res=await invoke(variant.make(snapshot(),reads));
 assert.equal(res.status,409);
 assert.deepEqual(res.body,{error:'GRANT_BLOCKED'});
 assert.equal(reads.count,0);
});
