import {acceptPodEvent,podEventClientFailureStatus,verifyPodEventPool} from './event-inbox.mjs';
import {exactHandlerConfig} from './handler-config.mjs';
import {parsePodRequestJSON} from './request-json.mjs';
import {types as utilTypes} from 'node:util';
import {validPodSharedKey} from './key-contract.mjs';

const REQUEST_TOO_LARGE=Symbol('REQUEST_TOO_LARGE');
const REQUEST_INVALID=Symbol('REQUEST_INVALID');
const REQUEST_TIMEOUT=Symbol('REQUEST_TIMEOUT');
const EVENT_ENVELOPE_INVALID=Symbol('EVENT_ENVELOPE_INVALID');
const pendingRequests=new WeakMap();
const MAX_PENDING_REQUESTS=32;

function admitRequest(pool){
 const pending=pendingRequests.get(pool)||0;
 if(pending>=MAX_PENDING_REQUESTS)return;
 pendingRequests.set(pool,pending+1);
 let released=false;
 return ()=>{
  if(released)return;
  released=true;
  const remaining=pendingRequests.get(pool)-1;
  if(remaining)pendingRequests.set(pool,remaining);else pendingRequests.delete(pool);
 };
}

// Mount on the existing internal Money Factory host, behind its TLS ingress.
// The signed envelope authenticates the sender; the transport cannot promote
// observations into verified revenue, rights, readiness, or publication authority.
export function createPodEventHandler(config){
 const {pool,key,clock,timeoutMs,connectionTimeoutMs,transactionTimeoutMs}=exactHandlerConfig(config,
  ['pool','key','clock','timeoutMs','connectionTimeoutMs','transactionTimeoutMs'],
  {clock:Date.now,timeoutMs:5000,connectionTimeoutMs:5000,transactionTimeoutMs:15000},'EVENT_HANDLER_CONFIG_INVALID');
 if(!pool||!validPodSharedKey(key)||
    typeof clock!=='function'||utilTypes.isProxy(clock)||
    !Number.isInteger(timeoutMs)||timeoutMs<1||timeoutMs>30000||
    !Number.isInteger(connectionTimeoutMs)||connectionTimeoutMs<1||connectionTimeoutMs>30000||
    !Number.isInteger(transactionTimeoutMs)||transactionTimeoutMs<1||transactionTimeoutMs>30000)throw Error('EVENT_HANDLER_CONFIG_INVALID');
 verifyPodEventPool(pool);
 return async function handle(req,res){
  let timer;
  const send=(status,value)=>{
   if(res.destroyed||res.writableEnded)return;
   res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});
   res.end(JSON.stringify(value));
  };
  if(req.method!=='POST')return send(405,{error:'METHOD_NOT_ALLOWED'});
  if((req.headers['content-type']||'').split(';')[0].trim().toLowerCase()!=='application/json')return send(415,{error:'JSON_REQUIRED'});
  const id=req.headers['idempotency-key'];
  if(typeof id!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(id))return send(400,{error:'EVENT_ID_REQUIRED'});
  // Outer JSON escapes the signed payload; cap both wire bytes and decoded body.
  const maximum=524288;
  if(Number(req.headers['content-length'])>maximum)return send(413,{error:'REQUEST_TOO_LARGE'});
  // Bound slow or concurrent bodies before allocating their buffers. The inbox
  // separately caps unresolved PostgreSQL acquisitions after authentication.
  const releaseAdmission=admitRequest(pool);
  if(!releaseAdmission)return send(503,{error:'EVENT_RECEIVER_UNAVAILABLE'});
  const readDeadline=performance.now()+timeoutMs;
  try{
   const read=async()=>{
    const chunks=[];let size=0;
    for await(const chunk of req){size+=chunk.length;if(size>maximum)throw REQUEST_TOO_LARGE;chunks.push(chunk);}
    try{return parsePodRequestJSON(Buffer.concat(chunks));}catch{throw REQUEST_INVALID;}
   };
   const envelope=await Promise.race([read(),new Promise((_,reject)=>{
    timer=setTimeout(()=>{send(408,{error:'REQUEST_TIMEOUT'});req.destroy();reject(REQUEST_TIMEOUT);},timeoutMs);
   })]);
   clearTimeout(timer);
   // Completing the stream/decoder can delay the timer callback. Do not let a
   // late body proceed to signature verification or acquire an inbox client.
   if(performance.now()>=readDeadline)return send(408,{error:'REQUEST_TIMEOUT'});
   if(!envelope||Array.isArray(envelope)||Object.keys(envelope).sort().join(',')!=='payload,signature')throw EVENT_ENVELOPE_INVALID;
   const ack=await acceptPodEvent(pool,envelope,key,clock,{expectedEventId:id,connectionTimeoutMs,transactionTimeoutMs});
   return send(200,ack);
  }catch(error){
   const status=error===REQUEST_TOO_LARGE?413:
    error===REQUEST_INVALID||error===EVENT_ENVELOPE_INVALID?400:
    error===REQUEST_TIMEOUT?408:podEventClientFailureStatus(error)||503;
   // Database errors can contain schema, connection, and event data. Never echo.
   return send(status,{error:status===503?'EVENT_RECEIVER_UNAVAILABLE':'EVENT_REJECTED'});
  }finally{clearTimeout(timer);releaseAdmission();}
 };
}
