import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {once} from 'node:events';
import {createPodEventHandler} from './event-handler.mjs';
import {acceptPodEvent} from './event-inbox.mjs';

const connectionString=process.env.POD_BRIDGE_TEST_DATABASE_URL;
test('PostgreSQL bridge recovers lost acknowledgments, serializes duplicates and rolls back failures',
 {skip:!connectionString,timeout:60000},async()=>{
 const url=new URL(connectionString);
 assert.ok(['localhost','127.0.0.1','[::1]'].includes(url.hostname),'disposable local database only');
 assert.equal(url.pathname,'/pod_bridge_test','dedicated disposable database required');
 assert.equal(process.env.PUBLICATION_ENABLED,'false');
 assert.equal(process.env.POD_PUBLICATION_ENABLED,'false');
 const root=path.resolve(process.env.CONTENT_CONTROL_ROOT||'content-control-test');
 const require=createRequire(path.join(root,'package.json'));
 const {Pool}=require('pg');
 const {deliverOutbox}=await import(pathToFileURL(path.join(root,'integrations/pod/outbox.mjs')));
 const {PodDB}=await import(pathToFileURL(path.join(root,'pod-db-bridge.js')));
 const {BRIDGE_RULES}=await import(pathToFileURL(path.join(root,'integrations/pod/policy.mjs')));
 const {monitorPodPool}=await import(pathToFileURL(path.join(root,'integrations/pod/pool-health.mjs')));
 const admin=new Pool({connectionString,max:1});
 const schema='pod_bridge_'+crypto.randomBytes(8).toString('hex');
 let pool,server;
 const key='test-only-outbox-key-'.repeat(3);
 try{
  await admin.query(`CREATE SCHEMA ${schema}`);
  pool=new Pool({connectionString,max:10,options:`-c search_path=${schema}`});
  const poolHealth=monitorPodPool(pool);
  await pool.query(await fs.readFile(new URL('./001_event_inbox.sql',import.meta.url),'utf8'));
  // Only sender event storage is a fixture; delivery and receipt are production modules.
  await pool.query(`CREATE TABLE pod_events(id uuid PRIMARY KEY,job_id uuid,kind text NOT NULL,
   payload jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),delivered_at timestamptz)`);
  const db={active(){},pool,async tx(fn){const c=await pool.connect();try{
   await c.query('BEGIN');const result=await fn(c);await c.query('COMMIT');return result;
  }catch(error){await c.query('ROLLBACK');throw error;}finally{c.release();}}};
  server=http.createServer(createPodEventHandler({pool,key}));
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const local='http://127.0.0.1:'+server.address().port;
  // Inject the test transport: no external endpoint or marketplace is contacted.
  const transport=async(endpoint,options)=>{assert.equal(endpoint.href,'https://authority.invalid/pod/events');return fetch(local,options);};
  const options={url:'https://authority.invalid/pod/events',key,fetchImpl:transport,continueOnError:true};
  const id=crypto.randomUUID(),job=crypto.randomUUID();
  await pool.query('INSERT INTO pod_events(id,job_id,kind,payload) VALUES($1,$2,$3,$4)',[id,job,'pod.production.review_required',{publication_enabled:false}]);
  // Interrupt only this fixture's idle backend after committing the sender event.
  // The event must survive reconnection, lost acknowledgement and unchanged-ID retry.
  const disconnectedPid=(await pool.query('SELECT pg_backend_pid() AS pid')).rows[0].pid;
  assert.equal(pool.totalCount,1);assert.equal(pool.idleCount,1);
  const idleError=once(pool,'error',{signal:AbortSignal.timeout(5000)});
  const [termination]=await Promise.all([
   admin.query('SELECT pg_terminate_backend($1) AS terminated',[disconnectedPid]),idleError]);
  assert.equal(termination.rows[0].terminated,true);
  assert.equal(poolHealth().idle_connection_failures,1);assert.equal(pool.totalCount,0);
  const lost=await deliverOutbox(db,{...options,fetchImpl:async(...args)=>{
   const response=await transport(...args);assert.equal(response.status,200);await response.arrayBuffer();
   throw Error('SIMULATED_LOST_ACK');
  }});
  assert.equal(lost.failed,1);assert.equal(lost.delivered,0);
  assert.equal((await pool.query('SELECT delivered_at FROM pod_events WHERE id=$1',[id])).rows[0].delivered_at,null);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox')).rows[0].n,1);
  const retried=await deliverOutbox(db,options);assert.equal(retried.delivered,1);assert.equal(retried.failed,0);
  assert.notEqual((await pool.query('SELECT pg_backend_pid() AS pid')).rows[0].pid,disconnectedPid);
  assert.equal(poolHealth().idle_connection_failures,1);
  assert.ok((await pool.query('SELECT delivered_at FROM pod_events WHERE id=$1',[id])).rows[0].delivered_at);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox')).rows[0].n,1);

  // Cross the sender's real storage cutoff after the receiver commits the first
  // event. The sender must retain both pending rows and never send the second.
  const cutoffIds=[crypto.randomUUID(),crypto.randomUUID()],cutoffSent=[];
  await pool.query(`INSERT INTO pod_events(id,job_id,kind,payload,created_at) VALUES
   ($1,$3,'pod.test.cutoff','{}','2026-01-01T00:00:00.000001Z'),
   ($2,$3,'pod.test.cutoff','{}','2026-01-01T00:00:00.000002Z')`,[...cutoffIds,job]);
  const cutoffDB=new PodDB({pool,bridge:{producer:'CYZOR Money Factory',consumer:'Content Control',contract:{fail_closed_rules:BRIDGE_RULES}},
   expiresAt:new Date(Date.now()+7*86400000).toISOString()});
  await assert.rejects(deliverOutbox(cutoffDB,{...options,fetchImpl:async(...args)=>{
   cutoffSent.push(args[1].headers['idempotency-key']);
   const response=await transport(...args);assert.equal(response.status,200);
   cutoffDB.expiresAt=Date.now()+3600000;return response;
  }}),/POD_STORAGE_EXPIRING/);
  assert.deepEqual(cutoffSent,[cutoffIds[0]]);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_events WHERE id=ANY($1::uuid[]) AND delivered_at IS NULL',[cutoffIds])).rows[0].n,2);
  assert.deepEqual((await pool.query('SELECT event_id FROM pod_content_event_inbox WHERE event_id=ANY($1::uuid[])',[cutoffIds])).rows.map(r=>r.event_id),[cutoffIds[0]]);
  // Restore only the disposable fixture's expiry, then retry unchanged IDs.
  // This is not a live provider expiry extension or authority approval.
  cutoffDB.expiresAt=Date.now()+7*86400000;
  const cutoffRetry=await deliverOutbox(cutoffDB,options);
  assert.equal(cutoffRetry.delivered,2);assert.equal(cutoffRetry.failed,0);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_events WHERE id=ANY($1::uuid[]) AND delivered_at IS NOT NULL',[cutoffIds])).rows[0].n,2);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=ANY($1::uuid[])',[cutoffIds])).rows[0].n,2);

  const sign=event=>{const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:Date.now(),event});
   return {payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')};};
  // Confirm the actual jsonb storage boundary, then reject the same signed
  // observations before acquiring a client rather than reporting a retryable
  // database outage. Only the isolated disposable schema is touched.
  let storageConnects=0;
  assert.equal((await pool.query('SHOW server_encoding')).rows[0].server_encoding,'UTF8');
  const storagePool={connect:()=>{storageConnects++;return pool.connect();}};
  for(const invalid of [{note:'\u0000'},{'\u0000':'value'},{note:'\ud800'},{'\udfff':'value'},
    {nested:[{note:'\udc00\ud800'}]}]){
   await assert.rejects(pool.query('SELECT $1::jsonb',[JSON.stringify(invalid)]),error=>error.code?.startsWith('22'));
   const badId=crypto.randomUUID();
   await assert.rejects(acceptPodEvent(storagePool,sign({id:badId,kind:'pod.test.storage',payload:invalid}),key),/EVENT_STORAGE_TEXT_INVALID/);
   assert.equal(storageConnects,0);
   assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[badId])).rows[0].n,0);
  }
  const unicodeId=crypto.randomUUID(),unicodeEvent={id:unicodeId,kind:'pod.test.storage',
   payload:{'🖨️':'café e\u0301 😀 \u0001\t\n\r \\u0000',boundaries:['\ud800\udc00','\udbff\udfff']}};
  assert.equal((await acceptPodEvent(storagePool,sign(unicodeEvent),key)).accepted_event_id,unicodeId);
  assert.equal(storageConnects,1);
  const saved=(await pool.query('SELECT event,event_sha256 FROM pod_content_event_inbox WHERE event_id=$1',[unicodeId])).rows[0];
  assert.deepEqual(saved.event,unicodeEvent);
  assert.equal(saved.event_sha256,crypto.createHash('sha256').update(JSON.stringify(unicodeEvent)).digest('hex'));

  // Saturate a real pg pool: the receiver must reject without acquiring a
  // transaction, release its late queued client, and allow an unchanged-ID retry.
  const single=new Pool({connectionString,max:1,options:`-c search_path=${schema}`});
  let held=await single.connect();
  const poolWaitId=crypto.randomUUID(),poolWaitEnvelope=sign({id:poolWaitId,kind:'pod.test.pool_wait',payload:{}});
  try{
   const waits=await Promise.allSettled(Array.from({length:32},()=>
    acceptPodEvent(single,poolWaitEnvelope,key,Date.now,{connectionTimeoutMs:30})));
   assert.ok(waits.every(x=>x.status==='rejected'&&x.reason.message==='EVENT_CONNECTION_TIMEOUT'));
   assert.equal(single.waitingCount,32);
   await assert.rejects(acceptPodEvent(single,poolWaitEnvelope,key),/EVENT_CONNECTION_BUSY/);
   assert.equal(single.waitingCount,32,'overload must not add a pg waiter');
   held.release();held=null;
   // Queued behind the timed-out receiver; completing this query proves that
   // receiver returned its eventual client rather than stranding the only slot.
   const rows=await single.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[poolWaitId]);
   assert.equal(rows.rows[0].n,0);
   assert.equal((await acceptPodEvent(single,poolWaitEnvelope,key)).accepted_event_id,poolWaitId);
   assert.equal((await single.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[poolWaitId])).rows[0].n,1);
  }finally{if(held)held.release();await single.end();}

  const duplicateId=crypto.randomUUID(),envelope=sign({id:duplicateId,kind:'pod.production.qa_failed',payload:{}});
  const acknowledgments=await Promise.all(Array.from({length:8},()=>acceptPodEvent(pool,envelope,key)));
  assert.ok(acknowledgments.every(a=>a.accepted_event_id===duplicateId));
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[duplicateId])).rows[0].n,1);
  await assert.rejects(()=>acceptPodEvent(pool,sign({id:duplicateId,kind:'pod.published',payload:{}}),key),/EVENT_REPLAY_CONFLICT/);
  assert.equal((await pool.query('SELECT event FROM pod_content_event_inbox WHERE event_id=$1',[duplicateId])).rows[0].event.kind,'pod.production.qa_failed');

  // Force the receiver to wait on an uncommitted duplicate event, then expire
  // its envelope or invalidate its clock. Rolling back the blocker frees the
  // insert; the receiver must roll back that row, then allow an unchanged-ID
  // retry with a valid fixture clock. No live clock or expiry is changed.
  for(const delayedClock of [issued=>issued+300001,issued=>issued+0.5,()=>NaN]){
  const expiryId=crypto.randomUUID(),expiryEvent={id:expiryId,kind:'pod.test.expiry',payload:{}};
  const expiryEnvelope=sign(expiryEvent),issued=JSON.parse(expiryEnvelope.payload).issued_at_ms;
  const expiryHash=crypto.createHash('sha256').update(JSON.stringify(expiryEvent)).digest('hex');
  const blocker=await pool.connect();let clockNow=issued,pending,workerPid;
  const waitingPool={connect:async()=>{const c=await pool.connect();workerPid=(await c.query('SELECT pg_backend_pid() AS pid')).rows[0].pid;return c;}};
  try{
   await blocker.query('BEGIN');
   await blocker.query('INSERT INTO pod_content_event_inbox(event_id,event_sha256,event) VALUES($1,$2,$3)',[expiryId,expiryHash,expiryEvent]);
   pending=acceptPodEvent(waitingPool,expiryEnvelope,key,()=>clockNow).then(value=>({value}),error=>({error}));
   let waiting=false;
   for(let attempt=0;attempt<100;attempt++){
    if(workerPid)waiting=(await pool.query('SELECT cardinality(pg_blocking_pids($1))>0 AS waiting',[workerPid])).rows[0].waiting;
    if(waiting)break;await new Promise(resolve=>setTimeout(resolve,10));
   }
   assert.equal(waiting,true,'receiver reached the held unique-key conflict');
   clockNow=delayedClock(issued);await blocker.query('ROLLBACK');
   assert.equal((await pending).error?.message,'EVENT_SCOPE_INVALID');
   assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[expiryId])).rows[0].n,0);
  }finally{await blocker.query('ROLLBACK');blocker.release();if(pending)await pending;}
  assert.equal((await acceptPodEvent(pool,expiryEnvelope,key,()=>issued)).accepted_event_id,expiryId);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[expiryId])).rows[0].n,1);
  }

  // A sender's HTTP timeout cannot release receiver-side database locks.
  // Verify the actual transaction-local lock deadline and retry after rollback.
  const lockId=crypto.randomUUID(),lockEnvelope=sign({id:lockId,kind:'pod.test.lock',payload:{}});
  const lockHolder=await pool.connect();
  try{
   await lockHolder.query('BEGIN');
   await lockHolder.query('LOCK TABLE pod_content_event_inbox IN ACCESS EXCLUSIVE MODE');
   await assert.rejects(acceptPodEvent(pool,lockEnvelope,key),error=>error.code==='55P03');
  }finally{await lockHolder.query('ROLLBACK');lockHolder.release();}
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[lockId])).rows[0].n,0);
  assert.equal((await acceptPodEvent(pool,lockEnvelope,key)).accepted_event_id,lockId);

  // This trigger exists only in the isolated disposable test schema. Sleeping
  // without lock contention exercises statement_timeout independently.
  await pool.query(`CREATE FUNCTION pod_test_delay() RETURNS trigger LANGUAGE plpgsql AS $$
   BEGIN IF NEW.event->>'kind'='pod.test.slow' THEN PERFORM pg_sleep(11); END IF; RETURN NEW; END; $$`);
  await pool.query('CREATE TRIGGER pod_test_delay BEFORE INSERT ON pod_content_event_inbox FOR EACH ROW EXECUTE FUNCTION pod_test_delay()');
  const slowId=crypto.randomUUID(),slowEnvelope=sign({id:slowId,kind:'pod.test.slow',payload:{}});
  try{
   await assert.rejects(acceptPodEvent(pool,slowEnvelope,key),error=>error.code==='57014');
  }finally{
   await pool.query('DROP TRIGGER pod_test_delay ON pod_content_event_inbox');
   await pool.query('DROP FUNCTION pod_test_delay()');
  }
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[slowId])).rows[0].n,0);
  assert.equal((await acceptPodEvent(pool,slowEnvelope,key)).accepted_event_id,slowId);

  await pool.query("ALTER TABLE pod_content_event_inbox ADD CONSTRAINT reject_test_event CHECK(event->>'kind' <> 'pod.test.reject')");
  const rejectedId=crypto.randomUUID();
  await pool.query('INSERT INTO pod_events(id,job_id,kind,payload) VALUES($1,$2,$3,$4)',[rejectedId,job,'pod.test.reject',{}]);
  const failed=await deliverOutbox(db,options);assert.equal(failed.failed,1);assert.equal(failed.delivered,0);
  assert.equal((await pool.query('SELECT delivered_at FROM pod_events WHERE id=$1',[rejectedId])).rows[0].delivered_at,null);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[rejectedId])).rows[0].n,0);
 }finally{
  if(server){server.closeAllConnections();await new Promise(r=>server.close(r));}
  if(pool)await pool.end();
  await admin.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`);await admin.end();
 }
});
