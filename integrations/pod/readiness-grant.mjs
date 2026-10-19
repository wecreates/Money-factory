import crypto from 'node:crypto';
import {signPodGrant} from './sign-grant.mjs';
import {enforceReleaseEconomics} from './economics.mjs';
const platforms=new Set(['kdp','redbubble','teepublic','zazzle','spreadshirt']);
const modes={RESEARCH:0,PRELAUNCH:1,LAUNCH:2};
const id=value=>typeof value==='string'&&value.trim().length>0&&value.length<=256;

// Call from the authoritative MF process with server-loaded snapshots, never request-supplied approval data.
export function issuePodGrant({readiness,job,approval,verifiedFacts={},forbiddenClaims=[],price=null,economics=null,key,now=Date.now()}){
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

