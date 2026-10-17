import crypto from 'node:crypto';
import {issuePodGrant} from './readiness-grant.mjs';

// Mount in the existing authoritative HTTP host, with a server-owned snapshot loader.
// Never accept readiness, approval, facts or price from the request.
export function createPodAuthorityHandler({loadSnapshot,authKey,signingKey,clock=Date.now,snapshotTimeoutMs=5000}){
 if(typeof loadSnapshot!=='function'||typeof clock!=='function'||!Number.isInteger(snapshotTimeoutMs)||snapshotTimeoutMs<1||snapshotTimeoutMs>10000||
  [authKey,signingKey].some(k=>typeof k!=='string'||Buffer.byteLength(k)<32)||authKey===signingKey)throw Error('AUTHORITY_CONFIG_INVALID');
 return async function handle(req,res){
  const send=(status,value)=>{if(res.destroyed||res.writableEnded)return;
   res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(value));};
  if(req.method!=='POST')return send(405,{error:'METHOD_NOT_ALLOWED'});
  const expected=Buffer.from('Bearer '+authKey),actual=Buffer.from(req.headers.authorization||'');
  if(actual.length!==expected.length||!crypto.timingSafeEqual(actual,expected))return send(401,{error:'AUTHORITY_AUTH_REQUIRED'});
  if((req.headers['content-type']||'').split(';')[0]!=='application/json')return send(415,{error:'JSON_REQUIRED'});
  let timer,snapshotTimer,onAbort;
  const controller=new AbortController(),onClose=()=>controller.abort();
  res.once('close',onClose);
  try{
   const read=async()=>{const chunks=[];let size=0;for await(const chunk of req){size+=chunk.length;if(size>4096)throw Error('REQUEST_TOO_LARGE');chunks.push(chunk);}return JSON.parse(Buffer.concat(chunks).toString('utf8'));};
   const request=await Promise.race([read(),new Promise((_,reject)=>{timer=setTimeout(()=>{req.destroy();reject(Error('TIMEOUT'));},5000);})]);
   clearTimeout(timer);
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
   const snapshot=await Promise.race([aborted,Promise.resolve().then(()=>{
    controller.signal.throwIfAborted();
    return loadSnapshot(request.job_id,{signal:controller.signal});
   })]);
   // A synchronous loader can delay the timer callback. Elapsed monotonic time
   // still forbids signing its late result.
   if(performance.now()>=deadline)controller.abort();
   controller.signal.throwIfAborted();
   if(snapshot?.job?.id!==request.job_id)throw Error('JOB_NOT_FOUND');
   const now=clock();if(!Number.isFinite(now))throw Error('AUTHORITY_CLOCK_INVALID');
   const grant=issuePodGrant({...snapshot,key:signingKey,now});
   return send(200,grant);
  }catch{if(!res.destroyed)return send(409,{error:'GRANT_BLOCKED'});}
  finally{clearTimeout(timer);clearTimeout(snapshotTimer);res.removeListener('close',onClose);
   if(onAbort)controller.signal.removeEventListener('abort',onAbort);}
 };
}
