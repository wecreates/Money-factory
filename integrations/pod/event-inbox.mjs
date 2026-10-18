import crypto from 'node:crypto';

async function acquireClient(pool,timeoutMs){
 const deadline=performance.now()+timeoutMs;
 let timer,expired=false,handedOff=false,candidate;
 // pg's promise API cannot remove a queued waiter. If it eventually receives
 // a client after this caller has failed, return that unused client immediately.
 // Promise.race installs rejection handling even when the timeout wins first.
 const connecting=Promise.resolve().then(()=>pool.connect()).then(client=>{
  candidate=client;
  if(expired){candidate=undefined;client.release();throw Error('EVENT_CONNECTION_TIMEOUT');}
  return client;
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
export async function acceptPodEvent(pool,envelope,key,clock=Date.now,{expectedEventId,connectionTimeoutMs=5000}={}){
 if(!Number.isInteger(connectionTimeoutMs)||connectionTimeoutMs<1||connectionTimeoutMs>30000)
  throw Error('EVENT_CONNECTION_CONFIG_INVALID');
 if(typeof clock!=='function')throw Error('EVENT_CLOCK_INVALID');
 const now=clock();
 if(typeof key!=='string'||Buffer.byteLength(key)<32||typeof envelope?.payload!=='string'||Buffer.byteLength(envelope.payload)>262144||!/^[a-f0-9]{64}$/.test(envelope.signature||''))throw Error('EVENT_ENVELOPE_INVALID');
 const expected=crypto.createHmac('sha256',key).update(envelope.payload).digest();
 if(!crypto.timingSafeEqual(expected,Buffer.from(envelope.signature,'hex')))throw Error('EVENT_SIGNATURE_INVALID');
 const p=JSON.parse(envelope.payload),e=p?.event;
 if(!Number.isSafeInteger(now)||now<0||p?.schema_version!==1||p.audience!=='money-factory:pod:event'||!Number.isSafeInteger(p.issued_at_ms)||p.issued_at_ms<0||p.issued_at_ms>now||now-p.issued_at_ms>300000||
  !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(e?.id||'')||typeof e.kind!=='string'||!e.kind.startsWith('pod.')||
  (expectedEventId!==undefined&&expectedEventId!==e.id))throw Error('EVENT_SCOPE_INVALID');
 const hash=crypto.createHash('sha256').update(JSON.stringify(e)).digest('hex');
 const c=await acquireClient(pool,connectionTimeoutMs);let discard=false;
 try{
  await c.query('BEGIN');
  // Sender timeouts do not cancel PostgreSQL work. Bound lock and statement
  // waits locally so a blocked inbox cannot hold receiver capacity indefinitely.
  await c.query("SET LOCAL lock_timeout='2s'");
  await c.query("SET LOCAL statement_timeout='10s'");
  await c.query('INSERT INTO pod_content_event_inbox(event_id,event_sha256,event) VALUES($1,$2,$3) ON CONFLICT DO NOTHING',[e.id,hash,e]);
  const previous=(await c.query('SELECT event_sha256 FROM pod_content_event_inbox WHERE event_id=$1',[e.id])).rows[0];
  if(previous.event_sha256!==hash)throw Error('EVENT_REPLAY_CONFLICT');
  // A captured request timestamp is not authorization after connection, unique
  // index or row waits. Expiry must roll back rather than acknowledge delivery.
  const current=clock();
  if(!Number.isSafeInteger(current)||current<0||p.issued_at_ms>current||current-p.issued_at_ms>300000)throw Error('EVENT_SCOPE_INVALID');
  await c.query('COMMIT');return {accepted_event_id:e.id};
 }catch(err){
  try{await c.query('ROLLBACK');}catch{discard=true;}
  throw err;
 }finally{c.release(discard);}
}
