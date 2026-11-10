import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import http from 'node:http';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {once} from 'node:events';
import {createPodBridgeDispatcher} from './bridge-dispatcher.mjs';
import {acceptPodEvent} from './event-inbox.mjs';
import {createPodEventHandler} from './event-handler.mjs';

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
 const {recordFinancialEvent}=await import(pathToFileURL(path.join(root,'integrations/pod/finance.mjs')));
 const {metrics}=await import(pathToFileURL(path.join(root,'integrations/pod/metrics.mjs')));
 const {createGrantResolver}=await import(pathToFileURL(path.join(root,'integrations/pod/grant-client.mjs')));
 const {PodDB}=await import(pathToFileURL(path.join(root,'pod-db-bridge.js')));
 const {BRIDGE_RULES,verifyEnvelope}=await import(pathToFileURL(path.join(root,'integrations/pod/policy.mjs')));
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
  const db={active(){},pool,async read(sql,args){this.active();const c=await pool.connect();try{
   this.active();const result=await c.query(sql,args);this.active();return result;
  }finally{c.release();}},async tx(fn){const c=await pool.connect();try{
   await c.query('BEGIN');const result=await fn(c);await c.query('COMMIT');return result;
  }catch(error){await c.query('ROLLBACK');throw error;}finally{c.release();}}};
  const authKey='test-only-grant-bearer-'.repeat(3),signingKey='test-only-grant-signing-'.repeat(3);
  const grantPath='/pod/grant',eventPath='/pod/events',ackPath='/pod/ack-freshness';
  const brief={id:crypto.randomUUID(),business_id:'fixture-business',account_id:crypto.randomUUID(),
   platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH',task_sha256:'a'.repeat(64)};
  let revoked=false,loads=0;
  const dispatch=createPodBridgeDispatcher({grantPath,eventPath,pool,authKey,signingKey,outboxKey:key,loadSnapshot:async id=>{
   loads++;assert.equal(id,brief.id);
   return {job:brief,readiness:{businesses:[{id:brief.business_id,content_production_ready:true,max_mode:'PRELAUNCH'}]},
    approval:{job_id:id,business_id:brief.business_id,account_id:brief.account_id,platform:brief.platform,
     task_sha256:brief.task_sha256,revoked,production_permission:true,publication_permission:false,
     expires_at_ms:Date.now()+60000,evidence_event_id:'fixture-approval'}};
  }});
  let expireOnRelease=true,ackClockOffset=0,ackCommits=0,ackRollbacks=0;
  const ackHandler=createPodEventHandler({key,clock:()=>Date.now()+ackClockOffset,pool:{connect:async()=>{
   const client=await pool.connect();
   return {query:async(sql,args)=>{
    const result=await client.query(sql,args);
    if(sql==='COMMIT'&&result.command==='COMMIT')ackCommits++;
    if(sql==='ROLLBACK')ackRollbacks++;
    return result;
   },release:async discard=>{
    await Promise.resolve();client.release(discard);
    if(expireOnRelease)ackClockOffset=300001;
   }};
  }}});
  server=http.createServer(async(req,res)=>{
   if(req.url===ackPath)return ackHandler(req,res);
   if(await dispatch(req,res))return;
   res.writeHead(404);res.end();
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const local='http://127.0.0.1:'+server.address().port;
  // Inject the test transport: no external endpoint or marketplace is contacted.
  const transport=async(endpoint,options)=>{assert.equal(endpoint.href,'https://authority.invalid'+eventPath);return fetch(local+eventPath,options);};
  const resolveGrant=createGrantResolver({env:{POD_GRANT_URL:'https://authority.invalid'+grantPath,
   POD_GRANT_AUTH_KEY:authKey,POD_UPSTREAM_KEY:signingKey},fetchImpl:async(endpoint,options)=>{
    assert.equal(endpoint.href,'https://authority.invalid'+grantPath);return fetch(local+grantPath,options);
  }});
  const authorized=verifyEnvelope(await resolveGrant({id:brief.id,brief}),signingKey,'content-control:pod');
  assert.equal(authorized.task_sha256,brief.task_sha256);assert.equal(authorized.publication_permission,false);
  revoked=true;
  await assert.rejects(resolveGrant({id:brief.id,brief}),/^Error: GRANT_AUTHORITY_BLOCKED$/);
  assert.equal(loads,2,'renewal must fetch the revoked snapshot instead of reusing the grant');
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

  // The actual receiver commits, but expiry during cleanup withholds its
  // acknowledgement. The pinned sender retries the unchanged durable event.
  const ackId=crypto.randomUUID(),statuses=[],sentIds=[];
  await pool.query('INSERT INTO pod_events(id,job_id,kind,payload) VALUES($1,$2,$3,$4)',
   [ackId,job,'pod.test.ack_freshness',{publication_enabled:false}]);
  const ackOptions={...options,url:'https://authority.invalid'+ackPath,fetchImpl:async(endpoint,request)=>{
   assert.equal(endpoint.href,'https://authority.invalid'+ackPath);
   sentIds.push(request.headers['idempotency-key']);
   const response=await fetch(local+ackPath,request);statuses.push(response.status);
   if(response.status===400)assert.deepEqual(await response.clone().json(),{error:'EVENT_REJECTED'});
   return response;
  }};
  const withheld=await deliverOutbox(db,ackOptions);
  assert.equal(withheld.failed,1);assert.equal(withheld.delivered,0);
  assert.equal((await pool.query('SELECT delivered_at FROM pod_events WHERE id=$1',[ackId])).rows[0].delivered_at,null);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[ackId])).rows[0].n,1);
  expireOnRelease=false;ackClockOffset=0;
  const recoveredAck=await deliverOutbox(db,ackOptions);
  assert.equal(recoveredAck.delivered,1);assert.equal(recoveredAck.failed,0);
  assert.deepEqual(statuses,[400,200]);assert.deepEqual(sentIds,[ackId,ackId]);
  assert.equal(ackCommits,2);assert.equal(ackRollbacks,0);
  assert.ok((await pool.query('SELECT delivered_at FROM pod_events WHERE id=$1',[ackId])).rows[0].delivered_at);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[ackId])).rows[0].n,1);

  // Simulate a bad restore in the disposable receiver schema: the digest
  // remains correct but the content does not. A replay must not mark delivery.
  const mismatchId=crypto.randomUUID(),mismatchStatuses=[],mismatchSent=[];
  await pool.query('INSERT INTO pod_events(id,job_id,kind,payload) VALUES($1,$2,$3,$4)',
   [mismatchId,job,'pod.test.stored_content',{publication_enabled:false,nested:{long_key:2,a:1}}]);
  const loseReceipt=await deliverOutbox(db,{...options,fetchImpl:async(...args)=>{
   const response=await transport(...args);assert.equal(response.status,200);await response.arrayBuffer();
   throw Error('SIMULATED_LOST_ACK');
  }});
  assert.equal(loseReceipt.failed,1);
  const readInbox=async()=>(await pool.query('SELECT event,event_sha256 FROM pod_content_event_inbox WHERE event_id=$1',[mismatchId])).rows[0];
  const savedInbox=await readInbox();
  const altered=await pool.query("UPDATE pod_content_event_inbox SET event=jsonb_set(event,'{payload,nested,a}','0') WHERE event_id=$1",[mismatchId]);
  assert.equal(altered.rowCount,1);
  const mismatchedInbox=await readInbox();
  assert.equal(mismatchedInbox.event_sha256,savedInbox.event_sha256);
  assert.equal(mismatchedInbox.event.payload.nested.a,0);
  const mismatchOptions={...options,fetchImpl:async(endpoint,request)=>{
   mismatchSent.push(request.headers['idempotency-key']);
   const response=await transport(endpoint,request);mismatchStatuses.push(response.status);
   if(response.status===409)assert.deepEqual(await response.clone().json(),{error:'EVENT_REJECTED'});
   return response;
  }};
  const refused=await deliverOutbox(db,mismatchOptions);
  assert.equal(refused.failed,1);assert.equal(refused.delivered,0);
  assert.deepEqual(await readInbox(),mismatchedInbox);
  assert.equal((await pool.query('SELECT delivered_at FROM pod_events WHERE id=$1',[mismatchId])).rows[0].delivered_at,null);
  // Restore the deliberately altered fixture only. No runtime repair is implied.
  await pool.query('UPDATE pod_content_event_inbox SET event=$2::jsonb WHERE event_id=$1',[mismatchId,savedInbox.event]);
  const mismatchRecovered=await deliverOutbox(db,mismatchOptions);
  assert.equal(mismatchRecovered.failed,0);assert.equal(mismatchRecovered.delivered,1);
  assert.deepEqual(mismatchStatuses,[409,200]);assert.deepEqual(mismatchSent,[mismatchId,mismatchId]);
  assert.deepEqual(await readInbox(),savedInbox);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[mismatchId])).rows[0].n,1);

  // Synthetic financial evidence uses the pinned intake, managed transaction,
  // sender and HTTP receiver. The small tables are isolated test fixtures.
  await pool.query(`CREATE TABLE pod_artifacts(sha256 text PRIMARY KEY,media_type text NOT NULL,body bytea NOT NULL);
   CREATE TABLE pod_financial_events(id uuid PRIMARY KEY,job_id uuid NOT NULL,provider text NOT NULL,
    provider_event_id text NOT NULL,kind text NOT NULL,amount_minor bigint NOT NULL,currency char(3) NOT NULL,
    occurred_at timestamptz NOT NULL,evidence_sha256 text NOT NULL REFERENCES pod_artifacts(sha256),
    authority_event_id text UNIQUE NOT NULL,UNIQUE(provider,provider_event_id))`);
  const financeDB=new PodDB({pool,bridge:{producer:'CYZOR Money Factory',consumer:'Content Control',contract:{fail_closed_rules:BRIDGE_RULES}},
   expiresAt:new Date(Date.now()+7*86400000).toISOString()});
  const financeKey='test-only-bridge-finance-key-'.repeat(3),proof=Buffer.from('{"fixture_only":true}');
  const evidenceSha=crypto.createHash('sha256').update(proof).digest('hex');
  await pool.query("INSERT INTO pod_artifacts(sha256,media_type,body) VALUES($1,'application/json',$2)",[evidenceSha,proof]);
  const occurred_at='2026-01-01T00:00:00.123456Z',authorityId=crypto.randomUUID(),providerEventId=crypto.randomUUID();
  const signStatement=()=>{
   const issued_at_ms=Date.now()-1;
   const payload=JSON.stringify({schema_version:1,audience:'content-control:pod:finance',issued_at_ms,expires_at_ms:issued_at_ms+60000,
    verified:true,job_id:job,provider:'fixture-provider',provider_event_id:providerEventId,authority_event_id:authorityId,
    kind:'royalty',currency:'USD',amount_minor:1234,occurred_at,evidence_sha256:evidenceSha});
   return {payload,signature:crypto.createHmac('sha256',financeKey).update(payload).digest('hex')};
  };
  const statement=await recordFinancialEvent(financeDB,signStatement(),financeKey);
  assert.equal(statement.duplicate,false);
  assert.deepEqual(await recordFinancialEvent(financeDB,signStatement(),financeKey),{id:statement.id,duplicate:true});
  const readStatement=await pool.query('SELECT id,amount_minor,occurred_at=$1::timestamptz AS exact_time FROM pod_financial_events',[occurred_at]);
  assert.deepEqual(readStatement.rows,[{id:statement.id,amount_minor:'1234',exact_time:true}]);
  const financeRows=await pool.query("SELECT id,payload FROM pod_events WHERE kind='pod.finance.verified'");
  const financeEvent=financeRows.rows[0],financeLink={financial_event_id:statement.id,authority_event_id:authorityId};
  assert.equal(financeRows.rowCount,1);
  assert.deepEqual(financeEvent.payload,financeLink);
  const lostFinanceReceipt=await deliverOutbox(financeDB,{...options,fetchImpl:async(endpoint,request)=>{
   assert.equal(request.headers['idempotency-key'],financeEvent.id);
   const response=await transport(endpoint,request);assert.equal(response.status,200);await response.arrayBuffer();
   throw Error('SIMULATED_LOST_FINANCIAL_ACK');
  }});
  assert.equal(lostFinanceReceipt.failed,1);
  assert.equal((await pool.query('SELECT delivered_at FROM pod_events WHERE id=$1',[financeEvent.id])).rows[0].delivered_at,null);
  const recoveredFinanceReceipt=await deliverOutbox(financeDB,options);
  assert.deepEqual(recoveredFinanceReceipt,{delivered:1,failed:0,nextCursor:null});
  assert.ok((await pool.query('SELECT delivered_at FROM pod_events WHERE id=$1',[financeEvent.id])).rows[0].delivered_at);
  const financeInbox=await pool.query('SELECT event FROM pod_content_event_inbox WHERE event_id=$1',[financeEvent.id]);
  assert.equal(financeInbox.rowCount,1);
  assert.equal(financeInbox.rows[0].event.job_id,job);
  assert.equal(financeInbox.rows[0].event.kind,'pod.finance.verified');
  assert.deepEqual(financeInbox.rows[0].event.payload,financeLink);

  // A revoked authority snapshot must leave the failed attempt untouched.
  // With a fresh signed grant, follow the real repair archive to the inbox.
  await pool.query(`CREATE TABLE pod_concepts(id uuid PRIMARY KEY,rights_state text NOT NULL,permanently_unpublished boolean NOT NULL);
   CREATE TABLE pod_production_queue(id uuid PRIMARY KEY,concept_id uuid NOT NULL REFERENCES pod_concepts(id),platform text NOT NULL,
    brief jsonb NOT NULL,attempt integer NOT NULL,fencing_token bigint NOT NULL,manifest jsonb,qa_envelope jsonb,
    reason_code text,state text NOT NULL,provider_id text,lease_until timestamptz,upstream_envelope jsonb NOT NULL,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now())`);
  const conceptId=crypto.randomUUID(),oldManifest={package_sha256:'b'.repeat(64)},oldQA={fixture_only:'failed-attempt'};
  await pool.query("INSERT INTO pod_concepts VALUES($1,'PASS',false)",[conceptId]);
  await pool.query(`INSERT INTO pod_production_queue
   (id,concept_id,brief,attempt,fencing_token,manifest,qa_envelope,reason_code,state,upstream_envelope,platform)
   VALUES($1,$2,$3,1,7,$4,$5,'REVIEW_REQUIRED','qa_failed','{}',$6)`,[brief.id,conceptId,brief,oldManifest,oldQA,brief.platform]);
  const repairDB=new PodDB({pool,upstreamKey:signingKey,
   bridge:{producer:'CYZOR Money Factory',consumer:'Content Control',contract:{fail_closed_rules:BRIDGE_RULES}},
   expiresAt:new Date(Date.now()+7*86400000).toISOString()});
  const repair=async()=>repairDB.requeueRepair(brief.id,await resolveGrant({id:brief.id,brief}));
  const repairRow=async()=>(await pool.query('SELECT state,attempt,fencing_token,manifest,qa_envelope,reason_code,upstream_envelope FROM pod_production_queue WHERE id=$1',[brief.id])).rows[0];
  const archiveRows=async()=>(await pool.query("SELECT id,payload FROM pod_events WHERE job_id=$1 AND kind='pod.repair.archived'",[brief.id])).rows;
  await assert.rejects(repair(),/^Error: GRANT_AUTHORITY_BLOCKED$/);
  assert.deepEqual(await repairRow(),{state:'qa_failed',attempt:1,fencing_token:'7',manifest:oldManifest,
   qa_envelope:oldQA,reason_code:'REVIEW_REQUIRED',upstream_envelope:{}});
  assert.deepEqual(await archiveRows(),[]);
  revoked=false;
  const fresh=await resolveGrant({id:brief.id,brief});
  await repairDB.requeueRepair(brief.id,fresh);
  assert.deepEqual(await repairRow(),{state:'raw',attempt:1,fencing_token:'7',manifest:null,
   qa_envelope:null,reason_code:null,upstream_envelope:fresh});
  await assert.rejects(repair(),/^Error: REPAIR_BLOCKED$/);
  const archives=await archiveRows();
  assert.equal(archives.length,1);
  const repairArchive=archives[0],archivedAttempt={attempt:1,manifest:oldManifest,qa_envelope:oldQA,reason_code:'REVIEW_REQUIRED'};
  assert.deepEqual(repairArchive.payload,archivedAttempt);
  assert.deepEqual(await deliverOutbox(repairDB,options),{delivered:1,failed:0,nextCursor:null});
  const repairInbox=(await pool.query('SELECT event FROM pod_content_event_inbox WHERE event_id=$1',[repairArchive.id])).rows;
  assert.equal(repairInbox.length,1);
  assert.equal(repairInbox[0].event.job_id,brief.id);assert.equal(repairInbox[0].event.kind,'pod.repair.archived');
  assert.deepEqual(repairInbox[0].event.payload,archivedAttempt);

  // Even a current authority grant cannot turn an unverified deadline into
  // permission to requeue. Both held states remain visible to monitoring.
  for(const [active,lease,held,reason] of [
   ['processing',null,'blocked','PRODUCTION_LEASE_UNVERIFIED'],
   ['publishing','infinity','ambiguous','PUBLISH_LEASE_UNVERIFIED'],
  ]){
   await pool.query('UPDATE pod_production_queue SET state=$2,reason_code=NULL,lease_until=$3::timestamptz WHERE id=$1',[brief.id,active,lease]);
   const observe=async()=>{
    const report=await metrics(repairDB);
    assert.equal(report.health.expired_leases,'0');assert.equal(report.health.unverified_leases,'1');
    assert.ok(report.health.alerts.some(a=>a.code==='UNVERIFIED_WORKER_LEASES'&&a.severity==='critical'));
    assert.equal(report.health.acceptance_verified,false);
   };
   await observe();
   await repairDB.recover();
   await observe();
   await assert.rejects(repair(),/^Error: REPAIR_BLOCKED$/);
   assert.deepEqual((await pool.query('SELECT state,reason_code,lease_until::text,attempt,fencing_token FROM pod_production_queue WHERE id=$1',[brief.id])).rows,
    [{state:held,reason_code:reason,lease_until:lease,attempt:1,fencing_token:'7'}]);
   assert.deepEqual(await archiveRows(),archives);
  }

  // Exercise actual state export/restore before renewing authority, not just
  // recovery on an already running queue. The recovery receipt may be delivered
  // to the inbox, but it must not release an unverified restored job for retry.
  const {migrate}=await import(pathToFileURL(path.join(root,'scripts/pod_storage_init.mjs')));
  const {exportStateArchive,restoreStateArchive}=await import(pathToFileURL(path.join(root,'integrations/pod/state-archive.mjs')));
  const archiveRoot=await fs.mkdtemp(path.join(os.tmpdir(),'pod-bridge-restore-'));
  const databases=[],dbPools=[],role=`${schema}_archive`;
  let roleCreated=false;
  try{
   await admin.query(`CREATE ROLE ${role} NOLOGIN`);roleCreated=true;
   for(const suffix of ['source','target']){
    const name=`${role}_${suffix}`;await admin.query(`CREATE DATABASE ${name} TEMPLATE template0`);databases.push(name);
    const destination=new URL(url);destination.pathname=`/${name}`;
    const dbPool=new Pool({connectionString:destination.toString(),max:2});dbPools.push(dbPool);
    await migrate(dbPool,role);
   }
   const [source,target]=dbPools;
   await source.query("INSERT INTO pod_concepts(id,business_id,fingerprint,rights_state) VALUES($1,$2,$3,'PASS')",[conceptId,brief.business_id,crypto.randomUUID()]);
   await source.query("INSERT INTO pod_accounts(id,platform,state,daily_cap) VALUES($1,$2,'ACTIVE',10)",[brief.account_id,brief.platform]);
   await source.query(`INSERT INTO pod_production_queue
    (id,concept_id,account_id,platform,revision,brief,upstream_envelope,idempotency_key,state,attempt,fencing_token,lease_until)
    VALUES($1,$2,$3,$4,1,$5,'{}',$6,'processing',1,7,'infinity')`,
    [brief.id,conceptId,brief.account_id,brief.platform,brief,crypto.randomUUID()]);
   const restricted=owner=>({connect:async()=>{
    const c=await owner.connect();try{await c.query(`SET ROLE ${role}`);}catch(error){c.release(true);throw error;}
    return {query:(...args)=>c.query(...args),release:()=>c.release(true)};
   }});
   const restoredDB=new PodDB({pool:restricted(target),upstreamKey:signingKey,
    bridge:{producer:'CYZOR Money Factory',consumer:'Content Control',contract:{fail_closed_rules:BRIDGE_RULES}},
    expiresAt:new Date(Date.now()+7*86400000).toISOString()});
   const archive={directory:path.join(archiveRoot,'snapshot'),key:Buffer.alloc(32,18),env:{PUBLICATION_ENABLED:'false',
    POD_PUBLICATION_ENABLED:'false',POD_PRODUCTION_ENABLED:'false',POD_OUTBOX_ENABLED:'false'}};
   await exportStateArchive({pool:restricted(source)},archive);
   const receipt=await restoreStateArchive(restoredDB,archive);
   const recoveryId=(await target.query("SELECT id FROM pod_events WHERE kind='pod.recovery.restored'")).rows[0].id;
   assert.deepEqual(await deliverOutbox(restoredDB,options),{delivered:1,failed:0,nextCursor:null});
   assert.deepEqual(await deliverOutbox(restoredDB,options),{delivered:0,failed:0,nextCursor:null});
   assert.deepEqual((await pool.query('SELECT event->\'payload\' AS payload FROM pod_content_event_inbox WHERE event_id=$1',[recoveryId])).rows,[{payload:receipt}]);
   const restoredGrant=await resolveGrant({id:brief.id,brief});
   await assert.rejects(restoredDB.requeueRepair(brief.id,restoredGrant),/^Error: REPAIR_BLOCKED$/);
   const held=(await target.query('SELECT state,reason_code,lease_until::text,attempt,fencing_token FROM pod_production_queue WHERE id=$1',[brief.id])).rows;
   assert.deepEqual(held,[{state:'blocked',reason_code:'PRODUCTION_LEASE_UNVERIFIED',lease_until:'infinity',attempt:1,fencing_token:'8'}]);
   assert.equal((await metrics(restoredDB)).health.unverified_leases,'1');
   assert.equal((await target.query("SELECT id FROM pod_events WHERE kind='pod.repair.archived'")).rowCount,0);
  }finally{
   await Promise.all(dbPools.map(p=>p.end()));
   for(const name of databases.reverse())await admin.query(`DROP DATABASE ${name}`);
   if(roleCreated)await admin.query(`DROP ROLE ${role}`);
   await fs.rm(archiveRoot,{recursive:true,force:true});
  }

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

  const eventRecord=event=>({job_id:null,created_at:new Date().toISOString(),...event});
  const sign=event=>{event=eventRecord(event);
   const payload=JSON.stringify({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:Date.now(),event});
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
  const unicodeId=crypto.randomUUID(),unicodeEvent=eventRecord({id:unicodeId,kind:'pod.test.storage',
   payload:{'🖨️':'café e\u0301 😀 \u0001\t\n\r \\u0000',boundaries:['\ud800\udc00','\udbff\udfff']}});
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

   // A broken query capability on a checked-out connection must not strand
   // this one-slot pool. Verify no write, then retry the same signed event.
   const malformedId=crypto.randomUUID(),malformedEnvelope=sign({id:malformedId,kind:'pod.test.query_capability',payload:{}});
   let checkout,discards=[],queryReads=0,malformedPid;
   const malformedPool={connect:async()=>{
    checkout=await single.connect();malformedPid=checkout.processID;
    return {
     get query(){queryReads++;throw Error('query capability must not be invoked');},
     release:discard=>{discards.push(discard);const client=checkout;checkout=null;client.release(discard);}
    };
   }};
   try{
    await assert.rejects(acceptPodEvent(malformedPool,malformedEnvelope,key),/^Error: EVENT_DATABASE_CAPABILITY_UNVERIFIED$/);
    assert.equal(queryReads,0);assert.deepEqual(discards,[true]);assert.equal(single.totalCount,0);
    const before=await single.query('SELECT pg_backend_pid() AS pid, (SELECT count(*)::int FROM pod_content_event_inbox WHERE event_id=$1) AS n',[malformedId]);
    assert.notEqual(before.rows[0].pid,malformedPid);assert.equal(before.rows[0].n,0);
    assert.equal((await acceptPodEvent(single,malformedEnvelope,key)).accepted_event_id,malformedId);
    assert.equal((await single.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[malformedId])).rows[0].n,1);
   }finally{if(checkout)checkout.release(true);}
  }finally{if(held)held.release();await single.end();}

  const duplicateId=crypto.randomUUID(),envelope=sign({id:duplicateId,kind:'pod.production.qa_failed',payload:{}});
  const acknowledgments=await Promise.all(Array.from({length:8},()=>acceptPodEvent(pool,envelope,key)));
  assert.ok(acknowledgments.every(a=>a.accepted_event_id===duplicateId));
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[duplicateId])).rows[0].n,1);
  await assert.rejects(()=>acceptPodEvent(pool,sign({id:duplicateId,kind:'pod.published',payload:{}}),key),/EVENT_REPLAY_CONFLICT/);
  assert.equal((await pool.query('SELECT event FROM pod_content_event_inbox WHERE event_id=$1',[duplicateId])).rows[0].event.kind,'pod.production.qa_failed');

  // An aborted PostgreSQL transaction can resolve COMMIT with a ROLLBACK
  // command tag. Force that outcome only on this disposable connection.
  const abortedId=crypto.randomUUID(),abortedEnvelope=sign({id:abortedId,kind:'pod.test.aborted_commit',payload:{}});
  let commitTag,discarded;
  const abortedPool={connect:async()=>{
   const client=await pool.connect();
   return {release:discard=>{discarded=discard;client.release(discard);},query:async(sql,args)=>{
    if(sql==='COMMIT')await assert.rejects(client.query('SELECT 1/0'),error=>error.code==='22012');
    const result=await client.query(sql,args);
    if(sql==='COMMIT')commitTag=result.command;
    return result;
   }};
  }};
  await assert.rejects(acceptPodEvent(abortedPool,abortedEnvelope,key),/^Error: EVENT_COMMIT_UNVERIFIED$/);
  assert.equal(commitTag,'ROLLBACK');assert.equal(discarded,true);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[abortedId])).rows[0].n,0);
  assert.equal((await acceptPodEvent(pool,abortedEnvelope,key)).accepted_event_id,abortedId);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[abortedId])).rows[0].n,1);

  // A driver wrapper resolving BEGIN without opening a transaction must not
  // allow the INSERT to run in autocommit. Use real command-tag evidence from
  // an inert SELECT on a disposable connection, then retry the exact event.
  const noBeginId=crypto.randomUUID(),noBeginEnvelope=sign({id:noBeginId,kind:'pod.test.no_begin',payload:{}});
  const noBeginQueries=[];let noBeginTag,noBeginDiscarded;
  const noBeginPool={connect:async()=>{
   const client=await pool.connect();
   return {release:discard=>{noBeginDiscarded=discard;client.release(discard);},query:async(sql,args)=>{
    noBeginQueries.push(sql);
    if(sql==='BEGIN'){const result=await client.query('SELECT 1');noBeginTag=result.command;return result;}
    return client.query(sql,args);
   }};
  }};
  await assert.rejects(acceptPodEvent(noBeginPool,noBeginEnvelope,key),/^Error: EVENT_BEGIN_UNVERIFIED$/);
  assert.equal(noBeginTag,'SELECT');assert.equal(noBeginDiscarded,true);assert.deepEqual(noBeginQueries,['BEGIN']);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[noBeginId])).rows[0].n,0);
  assert.equal((await acceptPodEvent(pool,noBeginEnvelope,key)).accepted_event_id,noBeginId);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[noBeginId])).rows[0].n,1);

  // The signed event is inserted, then the fixture clock invalidates it.
  // Substitute an actual SELECT for ROLLBACK while the transaction is open.
  // The client must be destroyed, the insert lost, and the same ID retryable.
  const noRollbackId=crypto.randomUUID(),noRollbackEnvelope=sign({id:noRollbackId,kind:'pod.test.no_rollback',payload:{}});
  const noRollbackQueries=[];let noRollbackTag,noRollbackDiscarded,calls=0;
  const noRollbackPool={connect:async()=>{
   const client=await pool.connect();
   return {release:discard=>{noRollbackDiscarded=discard;client.release(discard);},query:async(sql,args)=>{
    noRollbackQueries.push(sql);
    if(sql==='ROLLBACK'){const result=await client.query('SELECT 1');noRollbackTag=result.command;return result;}
    return client.query(sql,args);
   }};
  }};
  await assert.rejects(acceptPodEvent(noRollbackPool,noRollbackEnvelope,key,()=>++calls===1?Date.now():NaN),/^Error: EVENT_SCOPE_INVALID$/);
  assert.equal(noRollbackTag,'SELECT');assert.equal(noRollbackDiscarded,true);
  assert.equal(noRollbackQueries.at(-1),'ROLLBACK');assert.equal(noRollbackQueries.includes('COMMIT'),false);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[noRollbackId])).rows[0].n,0);
  assert.equal((await acceptPodEvent(pool,noRollbackEnvelope,key)).accepted_event_id,noRollbackId);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM pod_content_event_inbox WHERE event_id=$1',[noRollbackId])).rows[0].n,1);

  // Force the receiver to wait on an uncommitted duplicate event, then expire
  // its envelope or invalidate its clock. Rolling back the blocker frees the
  // insert; the receiver must roll back that row, then allow an unchanged-ID
  // retry with a valid fixture clock. No live clock or expiry is changed.
  for(const delayedClock of [issued=>issued+300001,issued=>issued+0.5,()=>NaN]){
  const expiryId=crypto.randomUUID(),expiryEvent=eventRecord({id:expiryId,kind:'pod.test.expiry',payload:{}});
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
