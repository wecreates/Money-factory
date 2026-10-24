import crypto from 'node:crypto';
import {issuePodGrant} from './readiness-grant.mjs';
import {parsePodRequestJSON} from './request-json.mjs';

// Share capacity across handlers wired to the same server-owned loader. An
// aborted HTTP request does not prove the loader stopped its backend work.
const pendingSnapshots=new WeakMap();
const MAX_PENDING_SNAPSHOTS=32;
const MAX_GRANT_RESPONSE_BYTES=262144;
async function loadBoundedSnapshot(loadSnapshot,id,signal){
 signal.throwIfAborted();
 const pending=pendingSnapshots.get(loadSnapshot)||0;
 if(pending>=MAX_PENDING_SNAPSHOTS)throw Error('SNAPSHOT_BUSY');
 pendingSnapshots.set(loadSnapshot,pending+1);
 return Promise.resolve().then(()=>{
  signal.throwIfAborted();
  return loadSnapshot(id,{signal});
 }).finally(()=>{
  const remaining=pendingSnapshots.get(loadSnapshot)-1;
  if(remaining)pendingSnapshots.set(loadSnapshot,remaining);else pendingSnapshots.delete(loadSnapshot);
 });
}

// Mount in the existing authoritative HTTP host, with a server-owned snapshot loader.
// Never accept readiness, approval, facts or price from the request.
export function createPodAuthorityHandler({loadSnapshot,authKey,signingKey,clock=Date.now,snapshotTimeoutMs=5000}){
 if(typeof loadSnapshot!=='function'||typeof clock!=='function'||!Number.isInteger(snapshotTimeoutMs)||snapshotTimeoutMs<1||snapshotTimeoutMs>10000||
  [authKey,signingKey].some(k=>typeof k!=='string'||Buffer.byteLength(k)<32)||
  Buffer.from(authKey).equals(Buffer.from(signingKey)))throw Error('AUTHORITY_CONFIG_INVALID');
 return async function handle(req,res){
  const sendBody=(status,body)=>{if(res.destroyed||res.writableEnded)return;
   res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});res.end(body);};
  const send=(status,value)=>sendBody(status,JSON.stringify(value));
  if(req.method!=='POST')return send(405,{error:'METHOD_NOT_ALLOWED'});
  const expected=Buffer.from('Bearer '+authKey),actual=Buffer.from(req.headers.authorization||'');
  if(actual.length!==expected.length||!crypto.timingSafeEqual(actual,expected))return send(401,{error:'AUTHORITY_AUTH_REQUIRED'});
  if((req.headers['content-type']||'').split(';')[0]!=='application/json')return send(415,{error:'JSON_REQUIRED'});
  let timer,snapshotTimer,onAbort;
  const controller=new AbortController(),onClose=()=>controller.abort();
  res.once('close',onClose);
  const readDeadline=performance.now()+5000;
  try{
   const read=async()=>{const chunks=[];let size=0;for await(const chunk of req){size+=chunk.length;if(size>4096)throw Error('REQUEST_TOO_LARGE');chunks.push(chunk);}return parsePodRequestJSON(Buffer.concat(chunks));};
   const request=await Promise.race([read(),new Promise((_,reject)=>{timer=setTimeout(()=>{req.destroy();reject(Error('TIMEOUT'));},5000);})]);
   clearTimeout(timer);
   // A delayed timer must not give a late body a fresh snapshot lookup window.
   if(performance.now()>=readDeadline)throw Error('TIMEOUT');
   if(!request||Object.keys(request).length!==1||typeof request.job_id!=='string'||!/^[-a-zA-Z0-9_]{1,100}$/.test(request.job_id))throw Error('REQUEST_INVALID');
   if(res.destroyed||req.aborted)controller.abort();
   // Bound the authority lookup separately from reading the request. A loader
   // must honor this signal and its own database deadlines to stop backend work.
   const aborted=new Promise((_,reject)=>{
    onAbort=()=>reject(Error('SNAPSHOT_ABORTED'));
    controller.signal.addEventListener('abort',onAbort,{once:true});
    if(controller.signal.aborted)onAbort();
   });
   const deadline=performance.now()+snapshotTimeoutMs;
   snapshotTimer=setTimeout(()=>controller.abort(),snapshotTimeoutMs);
   const snapshot=await Promise.race([aborted,loadBoundedSnapshot(loadSnapshot,request.job_id,controller.signal)]);
   // A synchronous loader can delay the timer callback. Elapsed monotonic time
   // still forbids signing its late result.
   if(performance.now()>=deadline)controller.abort();
   controller.signal.throwIfAborted();
   if(snapshot?.job?.id!==request.job_id)throw Error('JOB_NOT_FOUND');
   const now=clock();if(!Number.isSafeInteger(now)||now<0)throw Error('AUTHORITY_CLOCK_INVALID');
   const grant=issuePodGrant({...snapshot,key:signingKey,now});
   const body=JSON.stringify(grant);
   if(Buffer.byteLength(body)>MAX_GRANT_RESPONSE_BYTES)throw Error('GRANT_RESPONSE_TOO_LARGE');
   return sendBody(200,body);
  }catch{if(!res.destroyed)return send(409,{error:'GRANT_BLOCKED'});}
  finally{clearTimeout(timer);clearTimeout(snapshotTimer);res.removeListener('close',onClose);
   if(onAbort)controller.signal.removeEventListener('abort',onAbort);}
 };
}
