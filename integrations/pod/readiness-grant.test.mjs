import test from 'node:test';
import assert from 'node:assert/strict';
import {issuePodGrant} from './readiness-grant.mjs';
import {economicsFixture} from './economics-fixture.mjs';
const key='k'.repeat(48),now=Date.now();
const job={id:'job',business_id:'pod',account_id:'account',platform:'redbubble',destination_platform:'redbubble',mode:'PRELAUNCH'};
const readiness={businesses:[{id:'pod',content_production_ready:true,max_mode:'PRELAUNCH',launch_content_allowed:false}]};
const approval={job_id:'job',business_id:'pod',account_id:'account',platform:'redbubble',publication_permission:true,revoked:false,expires_at_ms:now+60000,evidence_event_id:'verified-approval'};
test('missing approval cannot create a grant',()=>assert.throws(()=>issuePodGrant({readiness,job,key,now}),/APPROVAL_REQUIRED/));
test('readiness ceiling is preserved',()=>assert.throws(()=>issuePodGrant({readiness,job:{...job,mode:'LAUNCH'},approval,key,now}),/READINESS_BLOCKED/));
test('signed scoped prelaunch grant cannot authorize launch',()=>{const g=JSON.parse(issuePodGrant({readiness,job,approval,key,now}).payload);assert.equal(g.max_mode,'PRELAUNCH');assert.equal(g.launch_content_allowed,false);assert.equal(g.approval_event_id,'verified-approval');});
test('Etsy is rejected',()=>assert.throws(()=>issuePodGrant({readiness,job:{...job,platform:'etsy',destination_platform:'etsy'},approval,key,now}),/READINESS_BLOCKED/));
test('production-only approval never grants publication',()=>{
 const a={...approval,publication_permission:false,production_permission:true};
 const g=JSON.parse(issuePodGrant({readiness,job,approval:a,key,now}).payload);
 assert.equal(g.production_permission,true);assert.equal(g.publication_permission,false);
});
test('production-only approval cannot grant LAUNCH',()=>{
 const r={businesses:[{...readiness.businesses[0],max_mode:'LAUNCH',launch_content_allowed:true}]};
 const j={...job,mode:'LAUNCH',package_sha256:'a'.repeat(64)};
 const a={...approval,publication_permission:false,production_permission:true,providers_healthy:true,package_sha256:j.package_sha256};
 assert.throws(()=>issuePodGrant({readiness:r,job:j,approval:a,key,now}),/LAUNCH_BLOCKED/);
});
test('task artifact requires exact upstream approval',()=>{
 const j={...job,task_sha256:'a'.repeat(64)};
 assert.throws(()=>issuePodGrant({readiness,job:j,approval,key,now}),/TASK_APPROVAL_REQUIRED/);
 const g=JSON.parse(issuePodGrant({readiness,job:j,approval:{...approval,task_sha256:j.task_sha256},key,now}).payload);
 assert.equal(g.task_sha256,j.task_sha256);
});

function launch(){
 const j={...job,mode:'LAUNCH',package_sha256:'a'.repeat(64)};
 return {job:j,readiness:{businesses:[{...readiness.businesses[0],max_mode:'LAUNCH',launch_content_allowed:true}]},
  approval:{...approval,providers_healthy:true,package_sha256:j.package_sha256,economics_event_id:'fixture-economics'},
  ...economicsFixture(j,now),key,now};
}
test('LAUNCH requires current scoped economics and approval of that exact economic event',()=>{
 for(const change of [s=>delete s.economics,s=>s.economics.variable_cost_minor=601,
  s=>s.economics.valid_until_ms=now,s=>s.economics.account_id='other',
  s=>delete s.approval.economics_event_id,s=>s.approval.economics_event_id='other']){
  const s=launch();change(s);assert.throws(()=>issuePodGrant(s),/ECONOMICS_/);
 }
});
test('LAUNCH grant carries recomputed economics and cannot outlive cost evidence',()=>{
 const s=launch();s.economics.valid_until_ms=now+1000;s.economics.contribution_minor=999999;
 const grant=JSON.parse(issuePodGrant(s).payload);
 assert.equal(grant.expires_at_ms,now+1000);assert.equal(grant.economics.contribution_minor,400);
 assert.equal(grant.economics.evidence_event_id,s.approval.economics_event_id);
});

