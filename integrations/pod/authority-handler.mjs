import crypto from 'node:crypto';
import {types as utilTypes} from 'node:util';
import {copyAuthoritySnapshot} from './authority-evidence.mjs';
import {exactHandlerConfig} from './handler-config.mjs';
import {issuePodGrant} from './readiness-grant.mjs';
import {parsePodRequestJSON} from './request-json.mjs';
import {validPodBearerKey,validPodSharedKey} from './key-contract.mjs';

// Share capacity across handlers wired to the same server-owned loader. An
// aborted HTTP request does not prove the loader stopped its backend work.
const pendingSnapshots=new WeakMap();
const pendingRequests=new WeakMap();
const MAX_PENDING_SNAPSHOTS=32;
const MAX_PENDING_REQUESTS=32;
const MAX_REQUEST_BYTES=4096;
const MAX_GRANT_RESPONSE_BYTES=262144;
const REQUEST_TOO_LARGE=Symbol('REQUEST_TOO_LARGE');

function admitRequest(loadSnapshot){
 const pending=pendingRequests.get(loadSnapshot)||0;
 if(pending>=MAX_PENDING_REQUESTS)return;
 pendingRequests.set(loadSnapshot,pending+1);
 let released=false;
 return ()=>{
  if(released)return;
  released=true;
  const remaining=pendingRequests.get(loadSnapshot)-1;
  if(remaining)pendingRequests.set(loadSnapshot,remaining);else pendingRequests.delete(loadSnapshot);
 };
}

async function loadBoundedSnapshot(loadSnapshot,id,signal){
 signal.throwIfAborted();
 const pending=pendingSnapshots.get(loadSnapshot)||0;
 if(pending>=MAX_PENDING_SNAPSHOTS)throw Error('SNAPSHOT_BUSY');
 pendingSnapshots.set(loadSnapshot,pending+1);
 return Promise.resolve().then(()=>{
  signal.throwIfAborted();
  const loaded=loadSnapshot(id,{signal});
  // A synchronous snapshot is authority data, not a Promise resolution
  // procedure. Wrap it so an executable own `then` member cannot run or
  // replace the snapshot before the fail-closed evidence copier validates it.
  // Preserve ordinary native Promise loaders without reading caller-owned
  // `then` or `bind` properties.
  return utilTypes.isPromise(loaded)
   ?Promise.prototype.then.call(loaded,snapshot=>({snapshot}))
   :{snapshot:loaded};
 }).finally(()=>{
  const remaining=pendingSnapshots.get(loadSnapshot)-1;
  if(remaining)pendingSnapshots.set(loadSnapshot,remaining);else pendingSnapshots.delete(loadSnapshot);
 });
}

// Mount in the existing authoritative HTTP host, with a server-owned snapshot loader.
// Never accept readiness, approval, facts or price from the request.
export function createPodAuthorityHandler(config){
 const {loadSnapshot,authKey,signingKey,clock,snapshotTimeoutMs}=exactHandlerConfig(config,
  ['loadSnapshot','authKey','signingKey','clock','snapshotTimeoutMs'],{clock:Date.now,snapshotTimeoutMs:5000},'AUTHORITY_CONFIG_INVALID');
 if(typeof loadSnapshot!=='function'||utilTypes.isProxy(loadSnapshot)||
  typeof clock!=='function'||utilTypes.isProxy(clock)||
  !Number.isInteger(snapshotTimeoutMs)||snapshotTimeoutMs<1||snapshotTimeoutMs>10000||
  !validPodBearerKey(authKey)||!validPodSharedKey(signingKey)||
  Buffer.from(authKey).equals(Buffer.from(signingKey)))throw Error('AUTHORITY_CONFIG_INVALID');
 return async function handle(req,res){
  const sendBody=(status,body)=>{if(res.destroyed||res.writableEnded)return;
   res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});res.end(body);};
  const send=(status,value)=>sendBody(status,JSON.stringify(value));
  if(req.method!=='POST')return send(405,{error:'METHOD_NOT_ALLOWED'});
  const authorization=req.headers.authorization;
  if(typeof authorization!=='string'||authorization.length<8||
   authorization.slice(0,6).toLowerCase()!=='bearer'||authorization[6]!==' ')
   return send(401,{error:'AUTHORITY_AUTH_REQUIRED'});
  let tokenStart=7;while(authorization[tokenStart]===' ')tokenStart++;
  const expected=Buffer.from(authKey),actual=Buffer.from(authorization.slice(tokenStart));
  if(actual.length!==expected.length||!crypto.timingSafeEqual(actual,expected))return send(401,{error:'AUTHORITY_AUTH_REQUIRED'});
  if((req.headers['content-type']||'').split(';')[0].trim().toLowerCase()!=='application/json')
   return send(415,{error:'JSON_REQUIRED'});
  if(Number(req.headers['content-length'])>MAX_REQUEST_BYTES)
   return send(413,{error:'REQUEST_TOO_LARGE'});
  // Bound slow or concurrent request bodies before allocating their buffers.
  // Snapshot lookup retains its own separately bounded backend capacity.
  const releaseAdmission=admitRequest(loadSnapshot);
  if(!releaseAdmission)return send(409,{error:'GRANT_BLOCKED'});
  let timer,snapshotTimer,onAbort,bodySettled=false,handlerSettled=false;
  // A timed-out handler can return before a custom/wrapped request stream
  // settles after destroy(). Keep that body admission occupied until both
  // lifetimes have ended so detached reads cannot grow past the shared cap.
  const releaseIfSettled=()=>{if(bodySettled&&handlerSettled)releaseAdmission();};
  const controller=new AbortController(),onClose=()=>controller.abort();
  res.once('close',onClose);
  const readDeadline=performance.now()+5000;
  try{
   const read=async()=>{const chunks=[];let size=0;for await(const chunk of req){size+=chunk.length;if(size>MAX_REQUEST_BYTES)throw REQUEST_TOO_LARGE;chunks.push(chunk);}return parsePodRequestJSON(Buffer.concat(chunks));};
   const reading=read();
   reading.then(()=>{bodySettled=true;releaseIfSettled();},()=>{bodySettled=true;releaseIfSettled();});
   const request=await Promise.race([reading,new Promise((_,reject)=>{timer=setTimeout(()=>{
    // Request destruction is best effort. A wrapped stream can throw here;
    // that must not prevent the server-owned timeout from settling or allow a
    // later body to reach authority lookup and grant signing.
    try{req.destroy();}catch{}
    reject(Error('TIMEOUT'));
   },5000);})]);
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
   const loaded=await Promise.race([aborted,loadBoundedSnapshot(loadSnapshot,request.job_id,controller.signal)]);
   const loadedSnapshot=loaded.snapshot;
   // A synchronous loader can delay the timer callback. Elapsed monotonic time
   // still forbids signing its late result.
   if(performance.now()>=deadline)controller.abort();
   controller.signal.throwIfAborted();
   const snapshot=copyAuthoritySnapshot(loadedSnapshot);
   if(snapshot?.job?.id!==request.job_id)throw Error('JOB_NOT_FOUND');
   const now=clock();if(!Number.isSafeInteger(now)||now<0)throw Error('AUTHORITY_CLOCK_INVALID');
   const grant=issuePodGrant({...snapshot,key:signingKey,now});
   const body=JSON.stringify(grant);
   if(Buffer.byteLength(body)>MAX_GRANT_RESPONSE_BYTES)throw Error('GRANT_RESPONSE_TOO_LARGE');
   return sendBody(200,body);
  }catch(error){if(!res.destroyed)return error===REQUEST_TOO_LARGE
   ?send(413,{error:'REQUEST_TOO_LARGE'}):send(409,{error:'GRANT_BLOCKED'});}
  finally{clearTimeout(timer);clearTimeout(snapshotTimer);res.removeListener('close',onClose);
   if(onAbort)controller.signal.removeEventListener('abort',onAbort);
   handlerSettled=true;releaseIfSettled();}
 };
}
