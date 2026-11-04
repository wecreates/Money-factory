import crypto from 'node:crypto';
import {types as utilTypes} from 'node:util';
import {parsePodJSON} from './request-json.mjs';
import {assertEventStorageText} from './event-storage.mjs';

// Shared across handlers using this pool. Timed-out callers still occupy a slot
// until pg settles their underlying request; otherwise retries grow its queue.
const pendingAcquisitions=new WeakMap();
const verifiedPoolConnections=new WeakMap();
const MAX_PENDING_ACQUISITIONS=32;
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const EVENT_KIND=/^pod\.[a-z0-9]+(?:[._][a-z0-9]+)*$/;
const ENVELOPE_FIELDS=['audience','event','issued_at_ms','schema_version'];
const EVENT_FIELDS=['created_at','id','job_id','kind','payload'];

const plainObject=value=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.getPrototypeOf(value)===Object.prototype;
function exactPlainObject(value,fields){return plainObject(value)&&Object.keys(value).sort().join('\0')===fields.join('\0');}

function exactInputEnvelope(value){
 const fail=()=>{throw Error('EVENT_ENVELOPE_INVALID');};
 if(!value||typeof value!=='object'||utilTypes.isProxy(value)||Object.getPrototypeOf(value)!==Object.prototype)fail();
 const keys=Reflect.ownKeys(value),fields=['payload','signature'];
 if(keys.length!==fields.length||keys.some(key=>typeof key!=='string'||!fields.includes(key)))fail();
 const snapshot=Object.create(null);
 for(const field of fields){
  const descriptor=Object.getOwnPropertyDescriptor(value,field);
  if(!descriptor||!descriptor.enumerable||!Object.hasOwn(descriptor,'value'))fail();
  snapshot[field]=descriptor.value;
 }
 return snapshot;
}

function exactAcceptOptions(value){
 const fail=()=>{throw Error('EVENT_CONNECTION_CONFIG_INVALID');};
 if(!value||typeof value!=='object'||utilTypes.isProxy(value))fail();
 const prototype=Object.getPrototypeOf(value);
 if(prototype!==Object.prototype&&prototype!==null)fail();
 const read=(name,fallback)=>{
  const descriptor=Object.getOwnPropertyDescriptor(value,name);
  if(!descriptor)return fallback;
  if(!Object.hasOwn(descriptor,'value'))fail();
  return descriptor.value;
 };
 return {expectedEventId:read('expectedEventId',undefined),connectionTimeoutMs:read('connectionTimeoutMs',5000)};
}

function exactQueryRow(result,fields){
 const fail=()=>{throw Error('EVENT_QUERY_UNVERIFIED');};
 if(!result||typeof result!=='object'||utilTypes.isProxy(result))fail();
 const rowsDescriptor=Object.getOwnPropertyDescriptor(result,'rows');
 if(!rowsDescriptor||!Object.hasOwn(rowsDescriptor,'value'))fail();
 const rows=rowsDescriptor.value;
 if(!Array.isArray(rows)||utilTypes.isProxy(rows)||rows.length!==1)fail();
 const element=Object.getOwnPropertyDescriptor(rows,'0');
 if(!element||!Object.hasOwn(element,'value'))fail();
 const row=element.value;
 if(!row||typeof row!=='object'||utilTypes.isProxy(row))fail();
 const prototype=Object.getPrototypeOf(row);
 if(prototype!==Object.prototype&&prototype!==null)fail();
 const keys=Reflect.ownKeys(row);
 if(keys.length!==fields.length||fields.some(field=>!keys.includes(field))||keys.some(key=>typeof key!=='string'||!fields.includes(key)))fail();
 const snapshot=Object.create(null);
 for(const field of fields){
  const descriptor=Object.getOwnPropertyDescriptor(row,field);
  if(!descriptor||!descriptor.enumerable||!Object.hasOwn(descriptor,'value'))fail();
  snapshot[field]=descriptor.value;
 }
 return snapshot;
}

function exactCapability(target,name){
 const fail=()=>{throw Error('EVENT_DATABASE_CAPABILITY_UNVERIFIED');};
 if(!target||typeof target!=='object'||utilTypes.isProxy(target))fail();
 for(let cursor=target;cursor!==null;cursor=Object.getPrototypeOf(cursor)){
  if(utilTypes.isProxy(cursor))fail();
  const descriptor=Object.getOwnPropertyDescriptor(cursor,name);
  if(!descriptor)continue;
  if(!Object.hasOwn(descriptor,'value')||typeof descriptor.value!=='function'||utilTypes.isProxy(descriptor.value))fail();
  // Do not read a caller-owned `bind` property from the verified function.
  // Ordinary functions can replace it with an accessor or executable value.
  return Function.prototype.bind.call(descriptor.value,target);
 }
 fail();
}

export function verifyPodEventPool(pool){
 if(!verifiedPoolConnections.has(pool))verifiedPoolConnections.set(pool,exactCapability(pool,'connect'));
 return pool;
}

async function acquireClient(pool,timeoutMs){
 const connect=verifiedPoolConnections.get(verifyPodEventPool(pool));
 const pending=pendingAcquisitions.get(pool)||0;
 if(pending>=MAX_PENDING_ACQUISITIONS)throw Error('EVENT_CONNECTION_BUSY');
 pendingAcquisitions.set(pool,pending+1);
 const deadline=performance.now()+timeoutMs;
 let timer,expired=false,handedOff=false,candidate;
 // pg's promise API cannot remove a queued waiter. If it eventually receives
 // a client after this caller has failed, return that unused client immediately.
 // Promise.race installs rejection handling even when the timeout wins first.
 const connecting=Promise.resolve().then(connect).finally(()=>{
  const remaining=pendingAcquisitions.get(pool)-1;
  if(remaining)pendingAcquisitions.set(pool,remaining);else pendingAcquisitions.delete(pool);
 }).then(client=>{
  const verified={query:exactCapability(client,'query'),release:exactCapability(client,'release')};
  candidate=verified;
  if(expired){candidate=undefined;verified.release();throw Error('EVENT_CONNECTION_TIMEOUT');}
  return verified;
 });
 try{
  const client=await Promise.race([connecting,new Promise((_,reject)=>{
   timer=setTimeout(()=>{expired=true;reject(Error('EVENT_CONNECTION_TIMEOUT'));},timeoutMs);
  })]);
  // A synchronous/delayed pool callback can finish before its overdue timer.
  if(expired||performance.now()>=deadline)throw Error('EVENT_CONNECTION_TIMEOUT');
  handedOff=true;return client;
 }finally{
  clearTimeout(timer);expired=true;
  if(!handedOff&&candidate){const client=candidate;candidate=undefined;client.release();}
 }
}

// This inbox records downstream observations. It never upgrades readiness or
// manufactures a core verified-revenue event. Wire the existing authority separately.
export async function acceptPodEvent(pool,envelope,key,clock=Date.now,options={}){
 const {expectedEventId,connectionTimeoutMs}=exactAcceptOptions(options);
 if(!Number.isInteger(connectionTimeoutMs)||connectionTimeoutMs<1||connectionTimeoutMs>30000)
  throw Error('EVENT_CONNECTION_CONFIG_INVALID');
 if(typeof clock!=='function'||utilTypes.isProxy(clock))throw Error('EVENT_CLOCK_INVALID');
 const now=clock();
 envelope=exactInputEnvelope(envelope);
 // RegExp.test coerces arrays to strings, while Buffer.from treats them as
 // bytes. Validate type and exact length before either operation. Exact length
 // also excludes the final line terminator accepted by a JavaScript $ anchor.
 if(typeof key!=='string'||Buffer.byteLength(key)<32||typeof envelope?.payload!=='string'||Buffer.byteLength(envelope.payload)>262144||
  typeof envelope.signature!=='string'||envelope.signature.length!==64||!/^[a-f0-9]{64}$/.test(envelope.signature))throw Error('EVENT_ENVELOPE_INVALID');
 const expected=crypto.createHmac('sha256',key).update(envelope.payload).digest();
 if(!crypto.timingSafeEqual(expected,Buffer.from(envelope.signature,'hex')))throw Error('EVENT_SIGNATURE_INVALID');
 const p=parsePodJSON(envelope.payload),e=p?.event,createdAt=Date.parse(e?.created_at);
 if(!Number.isSafeInteger(now)||now<0||!exactPlainObject(p,ENVELOPE_FIELDS)||p.schema_version!==1||p.audience!=='money-factory:pod:event'||!Number.isSafeInteger(p.issued_at_ms)||p.issued_at_ms<0||p.issued_at_ms>now||now-p.issued_at_ms>300000||
  !exactPlainObject(e,EVENT_FIELDS)||typeof e.id!=='string'||e.id.length!==36||!UUID.test(e.id)||
  !(e.job_id===null||typeof e.job_id==='string'&&e.job_id.length===36&&UUID.test(e.job_id))||
  typeof e.kind!=='string'||e.kind.length<5||e.kind.length>128||!EVENT_KIND.test(e.kind)||
  !plainObject(e.payload)||typeof e.created_at!=='string'||
  !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(e.created_at)||!Number.isSafeInteger(createdAt)||createdAt<0||
  new Date(createdAt).toISOString()!==e.created_at||createdAt-p.issued_at_ms>300000||
  (expectedEventId!==undefined&&expectedEventId!==e.id))throw Error('EVENT_SCOPE_INVALID');
 assertEventStorageText(e);
 const hash=crypto.createHash('sha256').update(JSON.stringify(e)).digest('hex');
 const c=await acquireClient(pool,connectionTimeoutMs);let discard=false,began=false,beginAttempted=false,commitAttempted=false;
 try{
  beginAttempted=true;await c.query('BEGIN');began=true;
  // Sender timeouts do not cancel PostgreSQL work. Bound lock and statement
  // waits locally so a blocked inbox cannot hold receiver capacity indefinitely.
  await c.query("SET LOCAL lock_timeout='2s'");
  await c.query("SET LOCAL statement_timeout='10s'");
  await c.query('INSERT INTO pod_content_event_inbox(event_id,event_sha256,event) VALUES($1,$2,$3) ON CONFLICT DO NOTHING',[e.id,hash,e]);
  const previous=exactQueryRow(await c.query('SELECT event_sha256 FROM pod_content_event_inbox WHERE event_id=$1',[e.id]),['event_sha256']);
  if(previous.event_sha256!==hash)throw Error('EVENT_REPLAY_CONFLICT');
  // A captured request timestamp is not authorization after connection, unique
  // index or row waits. Expiry must roll back rather than acknowledge delivery.
  const current=clock();
  if(!Number.isSafeInteger(current)||current<0||p.issued_at_ms>current||current-p.issued_at_ms>300000)throw Error('EVENT_SCOPE_INVALID');
  commitAttempted=true;await c.query('COMMIT');return {accepted_event_id:e.id};
 }catch(err){
  // Rejected transaction boundaries leave protocol or commit state uncertain.
  // Do not send more SQL on that client; destroy it. Between confirmed BEGIN
  // and attempted COMMIT, rollback remains the normal cleanup path.
  if(commitAttempted)discard=true;
  else if(began)try{await c.query('ROLLBACK');}catch{discard=true;}
  else if(beginAttempted)discard=true;
  throw err;
 }finally{c.release(discard);}
}

