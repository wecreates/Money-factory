import crypto from 'node:crypto';
import {issuePodGrant} from './readiness-grant.mjs';

// Mount in the existing authoritative HTTP host, with a server-owned snapshot loader.
// Never accept readiness, approval, facts or price from the request.
export function createPodAuthorityHandler({loadSnapshot,authKey,signingKey,clock=Date.now}){
 if(typeof loadSnapshot!=='function'||[authKey,signingKey].some(k=>typeof k!=='string'||Buffer.byteLength(k)<32)||authKey===signingKey)throw Error('AUTHORITY_CONFIG_INVALID');
 return async function handle(req,res){
  const send=(status,value)=>{res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(value));};
  if(req.method!=='POST')return send(405,{error:'METHOD_NOT_ALLOWED'});
  const expected=Buffer.from('Bearer '+authKey),actual=Buffer.from(req.headers.authorization||'');
  if(actual.length!==expected.length||!crypto.timingSafeEqual(actual,expected))return send(401,{error:'AUTHORITY_AUTH_REQUIRED'});
  if((req.headers['content-type']||'').split(';')[0]!=='application/json')return send(415,{error:'JSON_REQUIRED'});
  let timer;
  try{
   const read=async()=>{const chunks=[];let size=0;for await(const chunk of req){size+=chunk.length;if(size>4096)throw Error('REQUEST_TOO_LARGE');chunks.push(chunk);}return JSON.parse(Buffer.concat(chunks).toString('utf8'));};
   const request=await Promise.race([read(),new Promise((_,reject)=>{timer=setTimeout(()=>{req.destroy();reject(Error('TIMEOUT'));},5000);})]);
   clearTimeout(timer);
   if(!request||Object.keys(request).length!==1||typeof request.job_id!=='string'||!/^[-a-zA-Z0-9_]{1,100}$/.test(request.job_id))throw Error('REQUEST_INVALID');
   const snapshot=await loadSnapshot(request.job_id);
   if(snapshot?.job?.id!==request.job_id)throw Error('JOB_NOT_FOUND');
   const grant=issuePodGrant({...snapshot,key:signingKey,now:clock()});
   return send(200,grant);
  }catch{if(!res.destroyed)return send(409,{error:'GRANT_BLOCKED'});}
  finally{clearTimeout(timer);}
 };
}
