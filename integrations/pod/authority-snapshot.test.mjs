import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import http from 'node:http';
import {issuePodGrant} from './readiness-grant.mjs';
import {createPodAuthorityHandler} from './authority-handler.mjs';
const key='fixture-signing-key'.repeat(3),authKey='fixture-auth-key'.repeat(3),now=1700000000000;
function fixture(){return {key,now,
 job:{id:'job',business_id:'business',account_id:'account',platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH'},
 readiness:{businesses:[{id:'business',content_production_ready:true,max_mode:'PRELAUNCH',launch_content_allowed:false}]},
 approval:{job_id:'job',business_id:'business',account_id:'account',platform:'kdp',production_permission:true,
  publication_permission:false,revoked:false,expires_at_ms:now+60000,evidence_event_id:'fixture-approval'}};}
test('duplicate target businesses cannot select a readiness decision by row order',()=>{
 for(const conflict of [{content_production_ready:false},{max_mode:'RESEARCH'},{}])for(const reverse of [false,true]){
  const s=fixture(),first=s.readiness.businesses[0];
  s.readiness.businesses=[first,{...first,...conflict}];if(reverse)s.readiness.businesses.reverse();
  assert.throws(()=>issuePodGrant(s),/READINESS_BLOCKED/);
 }
});
test('readiness requires an array containing exactly one target business',()=>{
 for(const businesses of [undefined,null,{},[],[{id:'other',content_production_ready:true}],
  [null,...fixture().readiness.businesses],[{id:''},...fixture().readiness.businesses],
  {find:()=>fixture().readiness.businesses[0]}]){
  const s=fixture();s.readiness.businesses=businesses;assert.throws(()=>issuePodGrant(s),/^Error: READINESS_BLOCKED$/);
 }
});
test('matching malformed job and approval scope IDs cannot create a grant',()=>{
 for(const field of ['id','business_id','account_id'])for(const value of [undefined,null,'',' \t\n',0,true,[],{},'a'.repeat(257)]){
  const s=fixture();s.job[field]=value;s.approval[field==='id'?'job_id':field]=value;
  if(field==='business_id')s.readiness.businesses[0].id=value;
  assert.throws(()=>issuePodGrant(s),/READINESS_BLOCKED/);
 }
});
test('approval evidence reference must be a nonblank bounded primitive string',()=>{
 for(const value of [undefined,null,'',' \t\n',0,true,[],{},['event'],new String('event'),'a'.repeat(257)]){
  const s=fixture();s.approval.evidence_event_id=value;
  assert.throws(()=>issuePodGrant(s),/APPROVAL_REQUIRED/);
 }
});
test('unique valid business preserves exact identities, readiness hash and permissions',()=>{
 const s=fixture();s.job.account_id=s.approval.account_id='é'.repeat(256);
 s.approval.evidence_event_id='a'.repeat(256);
 s.readiness.businesses.unshift({id:'other',content_production_ready:false});
 const grant=JSON.parse(issuePodGrant(s).payload);
 assert.equal(grant.job_id,s.job.id);assert.equal(grant.business_id,s.job.business_id);
 assert.equal(grant.account_id,s.job.account_id);assert.equal(grant.approval_event_id,s.approval.evidence_event_id);
 assert.equal(grant.readiness_sha256,crypto.createHash('sha256').update(JSON.stringify(s.readiness)).digest('hex'));
 assert.equal(grant.production_permission,true);assert.equal(grant.publication_permission,false);
});
test('HTTP authority redacts ambiguous snapshots and can recover on a corrected snapshot',async t=>{
 let duplicate=true;
 const server=http.createServer(createPodAuthorityHandler({authKey,signingKey:key,clock:()=>now,loadSnapshot:async()=>{
  const s=fixture();if(duplicate)s.readiness.businesses.push({...s.readiness.businesses[0],content_production_ready:false});return s;
 }}));
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 t.after(async()=>{server.closeAllConnections();await new Promise(r=>server.close(r));});
 const post=()=>fetch('http://127.0.0.1:'+server.address().port,{method:'POST',
  headers:{authorization:'Bearer '+authKey,'content-type':'application/json'},body:'{"job_id":"job"}'});
 const blocked=await post();assert.equal(blocked.status,409);assert.deepEqual(await blocked.json(),{error:'GRANT_BLOCKED'});
 duplicate=false;const accepted=await post();assert.equal(accepted.status,200);
 assert.equal(JSON.parse((await accepted.json()).payload).publication_permission,false);
});
