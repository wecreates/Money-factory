import {acceptPodEvent} from './event-inbox.mjs';
import {parsePodRequestJSON} from './request-json.mjs';

// Mount on the existing internal Money Factory host, behind its TLS ingress.
// The signed envelope authenticates the sender; the transport cannot promote
// observations into verified revenue, rights, readiness, or publication authority.
export function createPodEventHandler({pool,key,clock=Date.now,timeoutMs=5000}){
 if(!pool||typeof pool.connect!=='function'||typeof key!=='string'||Buffer.byteLength(key)<32||
    typeof clock!=='function'||!Number.isInteger(timeoutMs)||timeoutMs<1||timeoutMs>30000)throw Error('EVENT_HANDLER_CONFIG_INVALID');
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
  const readDeadline=performance.now()+timeoutMs;
  try{
   const read=async()=>{
    const chunks=[];let size=0;
    for await(const chunk of req){size+=chunk.length;if(size>maximum)throw Error('REQUEST_TOO_LARGE');chunks.push(chunk);}
    return parsePodRequestJSON(Buffer.concat(chunks));
   };
   const envelope=await Promise.race([read(),new Promise((_,reject)=>{
    timer=setTimeout(()=>{send(408,{error:'REQUEST_TIMEOUT'});req.destroy();reject(Error('REQUEST_TIMEOUT'));},timeoutMs);
   })]);
   clearTimeout(timer);
   // Completing the stream/decoder can delay the timer callback. Do not let a
   // late body proceed to signature verification or acquire an inbox client.
   if(performance.now()>=readDeadline)return send(408,{error:'REQUEST_TIMEOUT'});
   if(!envelope||Array.isArray(envelope)||Object.keys(envelope).sort().join(',')!=='payload,signature')throw Error('EVENT_ENVELOPE_INVALID');
   const ack=await acceptPodEvent(pool,envelope,key,clock,{expectedEventId:id});
   return send(200,ack);
  }catch(error){
   const code=error?.message;
   const status=code==='REQUEST_TOO_LARGE'?413:code==='EVENT_SIGNATURE_INVALID'?401:
    code==='EVENT_REPLAY_CONFLICT'?409:
    ['EVENT_ENVELOPE_INVALID','EVENT_SCOPE_INVALID'].includes(code)||error instanceof SyntaxError?400:503;
   // Database errors can contain schema, connection, and event data. Never echo.
   return send(status,{error:status===503?'EVENT_RECEIVER_UNAVAILABLE':'EVENT_REJECTED'});
  }finally{clearTimeout(timer);}
 };
}
