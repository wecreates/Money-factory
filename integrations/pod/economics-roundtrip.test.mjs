import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {issuePodGrant} from './readiness-grant.mjs';
import {economicsFixture} from './economics-fixture.mjs';

test('Money Factory signed economic budget is revalidated by the pinned Content Control release contract',async()=>{
 if(!process.env.CONTENT_CONTROL_ROOT)throw Error('CONTENT_CONTROL_ROOT_REQUIRED');
 const moduleURL=name=>pathToFileURL(path.join(process.env.CONTENT_CONTROL_ROOT,'integrations/pod',name)).href;
 const {verifyEnvelope,enforceBrief}=await import(moduleURL('policy.mjs'));
 const {enforceReleaseEconomics}=await import(moduleURL('economics.mjs'));
 const now=Date.now(),key='synthetic-cross-repository-economics-'.repeat(2);
 const job={id:'fixture-job',business_id:'fixture-business',account_id:'fixture-account',platform:'redbubble',
  destination_platform:'redbubble',mode:'LAUNCH',package_sha256:'a'.repeat(64)};
 const input={job,key,now,...economicsFixture(job,now),
  readiness:{businesses:[{id:job.business_id,content_production_ready:true,max_mode:'LAUNCH',launch_content_allowed:true}]},
  approval:{job_id:job.id,business_id:job.business_id,account_id:job.account_id,platform:job.platform,
   publication_permission:true,revoked:false,providers_healthy:true,package_sha256:job.package_sha256,
   evidence_event_id:'fixture-approval',economics_event_id:'fixture-economics',expires_at_ms:now+60000}};
 const envelope=issuePodGrant(input),release=verifyEnvelope(envelope,key,'content-control:pod',now);
 const brief=enforceBrief(release,job,{publishing:true});
 assert.deepEqual(enforceReleaseEconomics(release,brief,now),release.economics);
 assert.throws(()=>enforceReleaseEconomics(release,brief,release.economics.valid_until_ms),/ECONOMICS_EXPIRED_OR_INVALID/);
 assert.throws(()=>verifyEnvelope({...envelope,payload:envelope.payload+' '},key,'content-control:pod',now),/SIGNATURE_INVALID/);
});
