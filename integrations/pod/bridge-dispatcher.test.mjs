import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import crypto from 'node:crypto';
import {createPodBridgeDispatcher} from './bridge-dispatcher.mjs';

const config=()=>({grantPath:'/pod/grant',eventPath:'/pod/events',authKey:'a'.repeat(40),
 signingKey:'s'.repeat(40),outboxKey:'o'.repeat(40),loadSnapshot:async()=>null,pool:{connect:async()=>null}});

test('bridge rejects path ambiguity and cross-role credential reuse at construction',()=>{
 for(const path of ['/','/pod//grant','/pod/grant/','/pod/%67rant','/pod/../grant','/pod/grant?x=1',
  '/pod/grant#fragment','https://example.invalid/pod/grant','/pod/grant\n','/'+ 'x'.repeat(128),null]){
  assert.throws(()=>createPodBridgeDispatcher({...config(),grantPath:path}),/^Error: POD_BRIDGE_CONFIG_INVALID$/);
 }
 const f=config();
 for(const patch of [{eventPath:f.grantPath},{outboxKey:f.signingKey},{outboxKey:f.authKey},{authKey:f.signingKey}])
  assert.throws(()=>createPodBridgeDispatcher({...f,...patch}),/^Error: POD_BRIDGE_CONFIG_INVALID$/);
 let reads=0;
 const executable=Object.defineProperty(config(),'outboxKey',{get(){reads++;return f.outboxKey;}});
 assert.throws(()=>createPodBridgeDispatcher(executable),/^Error: POD_BRIDGE_CONFIG_INVALID$/);
 assert.equal(reads,0);
});

test('bridge owns exact routes only and never crosses authentication roles',async t=>{
 const f=config();let loads=0,connects=0,fallbacks=0;
 f.loadSnapshot=async()=>{loads++;return null;};
 f.pool.connect=async()=>{connects++;throw Error('fixture inbox unavailable');};
 const dispatch=createPodBridgeDispatcher(f);
 const server=http.createServer(async(req,res)=>{
  if(await dispatch(req,res))return;
  fallbacks++;res.writeHead(404);res.end();
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 t.after(()=>{server.closeAllConnections();return new Promise(r=>server.close(r));});
 const post=(target,body,headers={})=>fetch('http://127.0.0.1:'+server.address().port+target,
  {method:'POST',headers:{'content-type':'application/json',...headers},body:JSON.stringify(body)});
 const request={job_id:'job'},auth={authorization:'Bearer '+f.authKey};
 for(const path of ['/other','/pod/grant?x=1','/pod/grant/','/pod/%67rant','/POD/grant','/pod/events?x=1'])
  assert.equal((await post(path,request,auth)).status,404);
 for(const credential of [f.outboxKey,f.signingKey])
  assert.equal((await post(f.grantPath,request,{authorization:'Bearer '+credential})).status,401);
 const id=crypto.randomUUID(),payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',
  issued_at_ms:Date.now(),event:{id,job_id:null,kind:'pod.test.router',payload:{},created_at:new Date().toISOString()}});
 const sendEvent=key=>post(f.eventPath,{payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')},
  {'idempotency-key':id,...auth});
 for(const credential of [f.authKey,f.signingKey])assert.equal((await sendEvent(credential)).status,401);
 assert.equal((await post(f.eventPath,request,auth)).status,400);
 assert.deepEqual({loads,connects,fallbacks},{loads:0,connects:0,fallbacks:6});
 assert.equal((await post(f.grantPath,request,auth)).status,409);
 const refused=await sendEvent(f.outboxKey);assert.equal(refused.status,503);
 assert.deepEqual(await refused.json(),{error:'EVENT_RECEIVER_UNAVAILABLE'});
 assert.deepEqual({loads,connects,fallbacks},{loads:1,connects:1,fallbacks:6});
});
