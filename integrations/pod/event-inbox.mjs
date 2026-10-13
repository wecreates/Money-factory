import crypto from 'node:crypto';

// This inbox records downstream observations. It never upgrades readiness or
// manufactures a core verified-revenue event. Wire the existing authority separately.
export async function acceptPodEvent(pool,envelope,key,now=Date.now()){
 if(typeof key!=='string'||Buffer.byteLength(key)<32||typeof envelope?.payload!=='string'||Buffer.byteLength(envelope.payload)>262144||!/^[a-f0-9]{64}$/.test(envelope.signature||''))throw Error('EVENT_ENVELOPE_INVALID');
 const expected=crypto.createHmac('sha256',key).update(envelope.payload).digest();
 if(!crypto.timingSafeEqual(expected,Buffer.from(envelope.signature,'hex')))throw Error('EVENT_SIGNATURE_INVALID');
 const p=JSON.parse(envelope.payload),e=p.event;
 if(p.schema_version!==1||p.audience!=='money-factory:pod:event'||!Number.isFinite(p.issued_at_ms)||p.issued_at_ms>now||now-p.issued_at_ms>300000||
  !e?.id||typeof e.kind!=='string'||!e.kind.startsWith('pod.'))throw Error('EVENT_SCOPE_INVALID');
 const hash=crypto.createHash('sha256').update(JSON.stringify(e)).digest('hex');
 const c=await pool.connect();
 try{
  await c.query('BEGIN');
  await c.query('INSERT INTO pod_content_event_inbox(event_id,event_sha256,event) VALUES($1,$2,$3) ON CONFLICT DO NOTHING',[e.id,hash,e]);
  const previous=(await c.query('SELECT event_sha256 FROM pod_content_event_inbox WHERE event_id=$1',[e.id])).rows[0];
  if(previous.event_sha256!==hash)throw Error('EVENT_REPLAY_CONFLICT');
  await c.query('COMMIT');return {accepted_event_id:e.id};
 }catch(err){await c.query('ROLLBACK').catch(()=>{});throw err;}finally{c.release();}
}
