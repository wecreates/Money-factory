import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {createPodAuthorityHandler} from './authority-handler.mjs';
const authKey='a'.repeat(32),signingKey='s'.repeat(32);
test('HTTP authority reloads approval and rejects injected authority data',async()=>{
 let revoked=false,loads=0;
 const handler=createPodAuthorityHandler({authKey,signingKey,loadSnapshot:async id=>{loads++;return {
  job:{id,business_id:'b',account_id:'a',platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH'},
  readiness:{businesses:[{id:'b',content_production_ready:true,max_mode:'PRELAUNCH',launch_content_allowed:false}]},
  approval:{job_id:id,business_id:'b',account_id:'a',platform:'kdp',revoked,production_permission:true,publication_permission:false,expires_at_ms:Date.now()+60000,evidence_event_id:'approval'}
 };}});
 const server=http.createServer(handler);await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const url='http://127.0.0.1:'+server.address().port;
 const post=(body,auth='Bearer '+authKey)=>fetch(url,{method:'POST',headers:{authorization:auth,'content-type':'application/json'},body:JSON.stringify(body)});
 try{
  let r=await post({job_id:'job'});assert.equal(r.status,200);assert.equal(JSON.parse((await r.json()).payload).publication_permission,false);
  revoked=true;r=await post({job_id:'job'});assert.equal(r.status,409);assert.equal(loads,2);
  assert.equal((await post({job_id:'job',approval:{revoked:false}})).status,409);assert.equal(loads,2);
  assert.equal((await post({job_id:'job'},'Bearer wrong')).status,401);assert.equal(loads,2);
 }finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
});
