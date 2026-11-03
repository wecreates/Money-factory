import crypto from 'node:crypto';
import {types as utilTypes} from 'node:util';
import {signPodGrant} from './sign-grant.mjs';
import {enforceReleaseEconomics} from './economics.mjs';
import {validOpaqueText} from './text-identity.mjs';
const platforms=new Set(['kdp','redbubble','teepublic','zazzle','spreadshirt']);
const modes={RESEARCH:0,PRELAUNCH:1,LAUNCH:2};
const id=validOpaqueText;
const MAX_SNAPSHOT_DEPTH=64;
const MAX_SNAPSHOT_OBJECTS=8192;

function copyAuthorityValue(value,state,depth){
 const fail=()=>{throw Error('AUTHORITY_SNAPSHOT_UNVERIFIED');};
 if(value===null||typeof value==='string'||typeof value==='boolean')return value;
 if(typeof value==='number'){if(!state.strict||Number.isFinite(value))return value;fail();}
 if(!state.strict&&['undefined','bigint','symbol','function'].includes(typeof value)){
  if(typeof value==='function'&&utilTypes.isProxy(value))fail();
  return value;
 }
 if(!value||typeof value!=='object'||utilTypes.isProxy(value)||depth>MAX_SNAPSHOT_DEPTH)fail();
 if(state.active.has(value))fail();
 if(state.copies.has(value))return state.copies.get(value);
 if(++state.objects>MAX_SNAPSHOT_OBJECTS)fail();
 state.active.add(value);
 let copy;
 if(Array.isArray(value)){
  if(Object.getPrototypeOf(value)!==Array.prototype)fail();
  const lengthDescriptor=Object.getOwnPropertyDescriptor(value,'length');
  if(!lengthDescriptor||!Object.hasOwn(lengthDescriptor,'value')||!Number.isSafeInteger(lengthDescriptor.value)||lengthDescriptor.value<0)fail();
  const length=lengthDescriptor.value,keys=Reflect.ownKeys(value);
  if(keys.length!==length+1||!keys.includes('length')||keys.some(key=>key!=='length'&&(typeof key!=='string'||!/^0$|^[1-9]\d*$/.test(key)||Number(key)>=length)))fail();
  copy=[];state.copies.set(value,copy);
  for(let index=0;index<length;index++){
   const descriptor=Object.getOwnPropertyDescriptor(value,String(index));
   if(!descriptor||!descriptor.enumerable||!Object.hasOwn(descriptor,'value'))fail();
   copy[index]=copyAuthorityValue(descriptor.value,state,depth+1);
  }
 }else{
  const prototype=Object.getPrototypeOf(value);
  if(!state.strict&&[String.prototype,Number.prototype,Boolean.prototype,BigInt.prototype,Symbol.prototype].includes(prototype)){
   if(Reflect.ownKeys(value).some(key=>{
    const descriptor=Object.getOwnPropertyDescriptor(value,key);
    return !descriptor||!Object.hasOwn(descriptor,'value');
   }))fail();
   state.active.delete(value);
   return value;
  }
  if(prototype!==Object.prototype&&prototype!==null)fail();
  copy=Object.create(null);state.copies.set(value,copy);
  for(const key of Reflect.ownKeys(value)){
   if(typeof key!=='string')fail();
   const descriptor=Object.getOwnPropertyDescriptor(value,key);
   if(!descriptor||!descriptor.enumerable||!Object.hasOwn(descriptor,'value'))fail();
   copy[key]=copyAuthorityValue(descriptor.value,state,depth+1);
  }
 }
 state.active.delete(value);
 return copy;
}

export function copyAuthoritySnapshot(value,strict=true){
 return copyAuthorityValue(value,{active:new WeakSet(),copies:new WeakMap(),objects:0,strict},0);
}

// Call from the authoritative MF process with server-loaded snapshots, never request-supplied approval data.
export function issuePodGrant(input){
 const {readiness,job,approval,verifiedFacts={},forbiddenClaims=[],price=null,economics=null,key,now=Date.now()}=copyAuthoritySnapshot(input,false);
 if(!Number.isSafeInteger(now)||now<0)throw Error('AUTHORITY_CLOCK_INVALID');
 if(![job?.id,job?.business_id,job?.account_id].every(id)||!Array.isArray(readiness?.businesses)||
  !readiness.businesses.every(b=>b&&typeof b==='object'&&!Array.isArray(b)&&id(b.id)))throw Error('READINESS_BLOCKED');
 // A duplicated business cannot choose its authority decision by row order.
 const matches=readiness.businesses.filter(b=>b.id===job.business_id);
 if(matches.length!==1)throw Error('READINESS_BLOCKED');
 const business=matches[0];
 if(!business||business.content_production_ready!==true||!platforms.has(job.platform)||job.destination_platform!==job.platform||
  typeof business.max_mode!=='string'||typeof job.mode!=='string'||
  !Object.hasOwn(modes,business.max_mode)||!Object.hasOwn(modes,job.mode)||modes[job.mode]>modes[business.max_mode])throw Error('READINESS_BLOCKED');
 if((approval?.production_permission!==true&&approval?.publication_permission!==true)||approval.revoked!==false||approval.business_id!==job.business_id||
  approval.job_id!==job.id||approval.account_id!==job.account_id||approval.platform!==job.platform||
  !Number.isSafeInteger(approval.expires_at_ms)||approval.expires_at_ms<0||approval.expires_at_ms<=now||!id(approval.evidence_event_id))throw Error('APPROVAL_REQUIRED');
 if(job.mode==='LAUNCH'&&(approval.publication_permission!==true||business.launch_content_allowed!==true||approval.providers_healthy!==true||approval.package_sha256!==job.package_sha256||!/^[a-f0-9]{64}$/.test(job.package_sha256||'')))throw Error('LAUNCH_BLOCKED');
 if(job.task_sha256!==undefined&&(!/^[a-f0-9]{64}$/.test(job.task_sha256)||approval.task_sha256!==job.task_sha256))throw Error('TASK_APPROVAL_REQUIRED');
 const budget=job.mode==='LAUNCH'?enforceReleaseEconomics({price,economics},job,now):null;
 if(budget&&approval.economics_event_id!==budget.evidence_event_id)throw Error('ECONOMICS_APPROVAL_REQUIRED');
 const payload={schema_version:1,audience:'content-control:pod',issued_at_ms:now,expires_at_ms:Math.min(now+300000,approval.expires_at_ms,budget?.valid_until_ms??Infinity),
  job_id:job.id,business_id:job.business_id,account_id:job.account_id,platform:job.platform,max_mode:business.max_mode,
  launch_content_allowed:business.launch_content_allowed===true,production_permission:true,publication_permission:approval.publication_permission===true,revoked:false,
  package_sha256:job.package_sha256,...(job.task_sha256?{task_sha256:job.task_sha256}:{}),approval_event_id:approval.evidence_event_id,
  readiness_sha256:crypto.createHash('sha256').update(JSON.stringify(readiness)).digest('hex'),
  verified_facts:verifiedFacts,forbidden_claims:forbiddenClaims,price,economics:budget};
 return signPodGrant(payload,key);
}

