import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import http from 'node:http';
import {pathToFileURL} from 'node:url';
import {issuePodGrant} from './readiness-grant.mjs';
import {createPodAuthorityHandler} from './authority-handler.mjs';

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
test('pinned Content Control resolver only receives a current grant after a fresh authority retry',async t=>{
 const f=input(),authKey='synthetic-authority-transport-'.repeat(2);
 const {createGrantResolver}=await import(pathToFileURL(path.join(process.env.CONTENT_CONTROL_ROOT,'integrations/pod/grant-client.mjs')).href);
 let mode='expiring',reads=0,loads=0;
 const handler=createPodAuthorityHandler({authKey,signingKey:f.key,
  clock:()=>++reads===2&&mode==='expiring'?f.approval.expires_at_ms:f.now,
  loadSnapshot:id=>{
   assert.equal(id,f.job.id);loads++;reads=0;
   return {job:f.job,readiness:f.readiness,approval:{...f.approval,revoked:mode==='revoked',evidence_event_id:'fixture-'+loads}};
  }});
 const server=http.createServer(handler);
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(()=>{server.closeAllConnections();return new Promise(resolve=>server.close(resolve));});
 const fixtureUrl='https://authority.example.invalid/pod/grant',responses=[];
 const resolve=createGrantResolver({env:{POD_GRANT_URL:fixtureUrl,POD_GRANT_AUTH_KEY:authKey,POD_UPSTREAM_KEY:f.key},
  fetchImpl:async (target,options)=>{
   assert.equal(target.href,fixtureUrl);
   const response=await fetch('http://127.0.0.1:'+server.address().port+'/pod/grant',options);
   responses.push(response.status);return response;
  }});
 const job={id:f.job.id,brief:f.job};
 await assert.rejects(resolve(job),/GRANT_AUTHORITY_BLOCKED/);
 mode='current';
 const grant=JSON.parse((await resolve(job)).payload);
 assert.equal(grant.approval_event_id,'fixture-2');assert.equal(grant.publication_permission,false);
 mode='revoked';await assert.rejects(resolve(job),/GRANT_AUTHORITY_BLOCKED/);
 assert.deepEqual(responses,[409,200,409]);assert.equal(loads,3);
});
test('a PRELAUNCH grant cannot be replayed for LAUNCH on the same package',async()=>{
 const {verifyEnvelope,enforceBrief}=await consumer(),f=input();
 Object.assign(f.readiness.businesses[0],{max_mode:'LAUNCH',launch_content_allowed:true});
 f.approval.publication_permission=true;
 f.job.package_sha256='a'.repeat(64);
 const grant=verifyEnvelope(issuePodGrant(f),f.key,'content-control:pod',f.now);
 assert.equal(enforceBrief(grant,f.job).mode,'PRELAUNCH');
 const launch={...f.job,mode:'LAUNCH'};
 assert.throws(()=>enforceBrief(grant,launch),/PUBLICATION_PERMISSION_REQUIRED/);
 assert.throws(()=>enforceBrief(grant,launch,{publishing:true}),/PUBLICATION_PERMISSION_REQUIRED/);
 assert.equal(grant.max_mode,'PRELAUNCH');assert.equal(grant.launch_content_allowed,false);
});
test('a RESEARCH grant cannot be replayed for PRELAUNCH under a broader business ceiling',async()=>{
 const {verifyEnvelope,enforceBrief}=await consumer(),f=input();
 f.job.mode='RESEARCH';
 const grant=verifyEnvelope(issuePodGrant(f),f.key,'content-control:pod',f.now);
 assert.equal(enforceBrief(grant,f.job).mode,'RESEARCH');
 assert.throws(()=>enforceBrief(grant,{...f.job,mode:'PRELAUNCH'}),/READINESS_CEILING/);
 assert.equal(grant.max_mode,'RESEARCH');
});
test('task-scoped approval stays bound from issuance to consumer verification',async()=>{
 const {verifyEnvelope,enforceBrief}=await consumer(),f=input(),digest='a'.repeat(64);
 f.approval.task_sha256=digest;
 assert.throws(()=>issuePodGrant(f),/^Error: TASK_APPROVAL_REQUIRED$/);
 for(const invalid of [null,'b'.repeat(64),[digest],digest.toUpperCase()]){
  f.job.task_sha256=invalid;
  assert.throws(()=>issuePodGrant(f),/^Error: TASK_APPROVAL_REQUIRED$/);
 }
 f.job.task_sha256=digest;
 const grant=verifyEnvelope(issuePodGrant(f),f.key,'content-control:pod',f.now);
 assert.equal(enforceBrief(grant,f.job).task_sha256,digest);
 assert.throws(()=>enforceBrief(grant,{...f.job,task_sha256:'b'.repeat(64)}),/TASK_SCOPE_MISMATCH/);
 const {task_sha256,...unbound}=f.job;
 assert.throws(()=>enforceBrief(grant,unbound),/TASK_SCOPE_MISMATCH/);
 assert.equal(grant.publication_permission,false);
});
test('issuer refuses numbers the pinned consumer cannot represent safely',async()=>{
 const {verifyEnvelope,enforceBrief}=await consumer(),f=input();
 f.verifiedFacts={title:{verified:true,value:'Fixture title',evidence_ids:['fixture-source'],score:9007199254740992}};
 assert.throws(()=>issuePodGrant(f),/^Error: AUTHORITY_SNAPSHOT_UNVERIFIED$/);
 for(const score of [Number.MIN_SAFE_INTEGER,Number.MAX_SAFE_INTEGER,0.125]){
  f.verifiedFacts.title.score=score;
  const grant=verifyEnvelope(issuePodGrant(f),f.key,'content-control:pod',f.now);
  assert.equal(enforceBrief(grant,f.job).facts.title.score,score);
 }
});
test('consumer omits malformed signed claim and price references from actual issuer output',async()=>{
 const {verifyEnvelope,enforceBrief}=await consumer(),f=input();
 f.verifiedFacts={title:{verified:true,value:'Fixture title',evidence_ids:['fixture-source']},
  shipping:{verified:true,provider_verified:true,value:'Fixture\0shipping',evidence_ids:['fixture-provider']},
  profit:{verified:true,money_factory_event_verified:true,value:'\ud800',evidence_ids:['fixture-ledger']}};
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
