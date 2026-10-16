import crypto from 'node:crypto';

// This inbox records downstream observations. It never upgrades readiness or
// manufactures a core verified-revenue event. Wire the existing authority separately.
export async function acceptPodEvent(pool,envelope,key,clock=Date.now,{expectedEventId}={}){
 if(typeof clock!=='function')throw Error('EVENT_CLOCK_INVALID');
 const now=clock();
 if(typeof key!=='string'||Buffer.byteLength(key)<32||typeof envelope?.payload!=='string'||Buffer.byteLength(envelope.payload)>262144||!/^[a-f0-9]{64}$/.test(envelope.signature||''))throw Error('EVENT_ENVELOPE_INVALID');
 const expected=crypto.createHmac('sha256',key).update(envelope.payload).digest();
 if(!crypto.timingSafeEqual(expected,Buffer.from(envelope.signature,'hex')))throw Error('EVENT_SIGNATURE_INVALID');
 const p=JSON.parse(envelope.payload),e=p?.event;
 if(!Number.isFinite(now)||p?.schema_version!==1||p.audience!=='money-factory:pod:event'||!Number.isFinite(p.issued_at_ms)||p.issued_at_ms>now||now-p.issued_at_ms>300000||
  !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(e?.id||'')||typeof e.kind!=='string'||!e.kind.startsWith('pod.')||
  (expectedEventId!==undefined&&expectedEventId!==e.id))throw Error('EVENT_SCOPE_INVALID');
 const hash=crypto.createHash('sha256').update(JSON.stringify(e)).digest('hex');
 const c=await pool.connect();let discard=false;
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
  if(!Number.isFinite(current)||p.issued_at_ms>current||current-p.issued_at_ms>300000)throw Error('EVENT_SCOPE_INVALID');
  await c.query('COMMIT');return {accepted_event_id:e.id};
 }catch(err){
  try{await c.query('ROLLBACK');}catch{discard=true;}
  throw err;
 }finally{c.release(discard);}
}
