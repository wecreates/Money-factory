import test from 'node:test';
import assert from 'node:assert/strict';
import {issuePodGrant} from './readiness-grant.mjs';
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
