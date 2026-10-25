import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {issuePodGrant} from './readiness-grant.mjs';

async function consumer(){
 if(!process.env.CONTENT_CONTROL_ROOT)throw Error('CONTENT_CONTROL_ROOT_REQUIRED');
 return import(pathToFileURL(path.join(process.env.CONTENT_CONTROL_ROOT,'integrations/pod/policy.mjs')).href);
}
function input(){
 const now=Date.now(),job={id:'fixture-job',business_id:'fixture-business',account_id:'fixture-account',
  platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH'};
 return {job,now,key:'synthetic-cross-repository-claims-'.repeat(2),
  readiness:{businesses:[{id:job.business_id,content_production_ready:true,max_mode:'PRELAUNCH'}]},
  approval:{job_id:job.id,business_id:job.business_id,account_id:job.account_id,platform:job.platform,
   production_permission:true,publication_permission:false,revoked:false,evidence_event_id:'fixture-approval',expires_at_ms:now+60000}};
}
test('consumer omits malformed signed claim and price references from actual issuer output',async()=>{
 const {verifyEnvelope,enforceBrief}=await consumer(),f=input();
 f.verifiedFacts={title:{verified:true,value:'Fixture title',evidence_ids:['fixture-source']},
  shipping:{verified:true,provider_verified:true,value:'Fixture shipping',evidence_ids:['provider\0source']},
  profit:{verified:true,money_factory_event_verified:true,value:'Fixture profit',evidence_ids:['\ud800']}};
 f.price={verified:true,amount_minor:100,currency:'USD',evidence_id:'price\0source'};
 const grant=verifyEnvelope(issuePodGrant(f),f.key,'content-control:pod',f.now);
 assert.equal(grant.publication_permission,false);
 const brief=enforceBrief(grant,f.job);
 assert.deepEqual(brief.facts,{title:f.verifiedFacts.title});assert.equal(brief.price,null);
 assert.throws(()=>enforceBrief(grant,f.job,{publishing:true}),/PUBLICATION_PERMISSION_REQUIRED/);
});
test('valid issuer references survive consumer filtering while forbidden claims remain omitted',async()=>{
 const {verifyEnvelope,enforceBrief}=await consumer(),f=input();
 f.verifiedFacts={title:{verified:true,value:'Café 雪',evidence_ids:['é'.repeat(256)]},
  shipping:{verified:true,provider_verified:true,value:'Fixture shipping',evidence_ids:['fixture-provider']},
  profit:{verified:true,money_factory_event_verified:true,value:'Fixture profit',evidence_ids:['fixture-ledger']}};
 f.forbiddenClaims=['profit'];f.price={verified:true,amount_minor:100,currency:'USD',evidence_id:'fixture-price'};
 const grant=verifyEnvelope(issuePodGrant(f),f.key,'content-control:pod',f.now),brief=enforceBrief(grant,f.job);
 assert.deepEqual(brief.facts,{title:f.verifiedFacts.title,shipping:f.verifiedFacts.shipping});
 assert.deepEqual(brief.price,f.price);assert.equal(grant.publication_permission,false);
});
