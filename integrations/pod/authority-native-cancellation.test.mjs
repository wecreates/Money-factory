import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter,getEventListeners} from 'node:events';
import {createPodAuthorityHandler} from './authority-handler.mjs';
const authKey='a'.repeat(32),signingKey='s'.repeat(32);
const snapshot=()=>({job:{id:'job',business_id:'b',account_id:'a',platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH'},
 readiness:{businesses:[{id:'b',content_production_ready:true,max_mode:'PRELAUNCH'}]},
 approval:{job_id:'job',business_id:'b',account_id:'a',platform:'kdp',revoked:false,production_permission:true,
  publication_permission:false,expires_at_ms:Date.now()+60000,evidence_event_id:'fixture'}});
function transport(){
 const res=new EventEmitter();res.writeHead=status=>{res.status=status;};
 res.end=body=>{res.body=JSON.parse(body);res.writableEnded=true;};
 const req={method:'POST',headers:{authorization:'Bearer '+authKey,'content-type':'application/json'},
  async *[Symbol.asyncIterator](){yield Buffer.from('{"job_id":"job"}');}};
 return {req,res};
}

test('shadowed throwIfAborted cannot waive the elapsed lookup deadline',async t=>{
 let elapsed=0,reads=0,clocks=0,signal;
 t.mock.method(performance,'now',()=>elapsed);
 const {req,res}=transport();
 await createPodAuthorityHandler({authKey,signingKey,snapshotTimeoutMs:10,clock:()=>{clocks++;return Date.now();},
  loadSnapshot:(_id,options)=>{signal=options.signal;
   Object.defineProperty(signal,'throwIfAborted',{value:()=>{reads++;}});
   elapsed=10;return snapshot();
  }})(req,res);
 assert.equal(res.status,409);assert.deepEqual(res.body,{error:'GRANT_BLOCKED'});
 assert.equal(reads,0);assert.equal(clocks,0);assert.equal(getEventListeners(signal,'abort').length,0);
});

test('signal property accessors cannot interfere with grant cleanup',async()=>{
 let reads=0,signal;const {req,res}=transport();
 await createPodAuthorityHandler({authKey,signingKey,loadSnapshot:(_id,options)=>{
  signal=options.signal;
  for(const key of ['aborted','throwIfAborted','removeEventListener'])
   Object.defineProperty(signal,key,{get(){reads++;throw Error('private signal getter');}});
  return snapshot();
 }})(req,res);
 assert.equal(res.status,200);assert.equal(reads,0);assert.equal(getEventListeners(signal,'abort').length,0);
 assert.equal(JSON.parse(res.body.payload).publication_permission,false);
});

test('synthetic abort cannot consume authority timeout cancellation',{timeout:3000},async()=>{
 let signal;const {req,res}=transport();
 await createPodAuthorityHandler({authKey,signingKey,snapshotTimeoutMs:20,loadSnapshot:(_id,options)=>{
  signal=options.signal;signal.dispatchEvent(new Event('abort'));return new Promise(()=>{});
 }})(req,res);
 assert.equal(res.status,409);assert.deepEqual(res.body,{error:'GRANT_BLOCKED'});
 assert.equal(signal.aborted,true);assert.equal(getEventListeners(signal,'abort').length,0);
});

test('synthetic abort cannot reject a current valid authority snapshot',async()=>{
 let signal;const {req,res}=transport();
 await createPodAuthorityHandler({authKey,signingKey,loadSnapshot:(_id,options)=>{
  signal=options.signal;signal.dispatchEvent(new Event('abort'));return snapshot();
 }})(req,res);
 assert.equal(res.status,200);assert.equal(signal.aborted,false);
 assert.equal(JSON.parse(res.body.payload).publication_permission,false);
 assert.equal(getEventListeners(signal,'abort').length,0);
});
