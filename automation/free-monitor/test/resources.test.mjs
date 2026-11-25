import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {buildResourceObservation,collectResourceObservation,readCgroupV2Limits,
  declaredWorkflowWallLimit,requestEnvelopeMs,validateWallEnvelope,
  MAX_ACTIVE_WATCHES,MAX_WORKER_ENVELOPE_MS,RUNTIME_STATE_KEY} from '../resources.mjs';
import {runWorker} from '../worker.mjs';

const policy={maxAttempts:2,requestTimeoutMs:20_000,retryBackoffMs:250};
const root=fileURLToPath(new URL('../../../',import.meta.url));

test('request envelope bounds active watches and complete retry wait',()=>{
  assert.equal(requestEnvelopeMs(2,policy),80_500);
  assert.throws(()=>requestEnvelopeMs(MAX_ACTIVE_WATCHES+1,policy),/active watch count/);
  assert.throws(()=>requestEnvelopeMs(4,{maxAttempts:3,requestTimeoutMs:60_000,retryBackoffMs:5_000}),
    new RegExp(String(MAX_WORKER_ENVELOPE_MS)));
  assert.equal(declaredWorkflowWallLimit(undefined),null);
  assert.equal(declaredWorkflowWallLimit('300000'),300000);
  assert.throws(()=>declaredWorkflowWallLimit('five minutes'),/integer milliseconds/);
  assert.throws(()=>validateWallEnvelope(80_500,80_500),/must be below/);
});

test('resource observation binds host, cgroup, filesystem, process and explicit unknown quotas',()=>{
  const result=buildResourceObservation({
    startedAt:'2026-11-24T19:00:00.000Z',observedAt:'2026-11-24T19:00:01.250Z',activeWatches:2,policy,
    workflowWallLimitMs:300_000,
    host:{available_cpu_cores:8,total_memory_bytes:16_000,free_memory_bytes:8_000},
    cgroup:{cpu_quota_cores:2,memory_limit_bytes:10_000,memory_current_bytes:4_000,
      memory_available_bytes:6_000,warnings:[]},
    disk:{total_bytes:50_000,available_bytes:20_000},
    usage:{rss_bytes:1000,heap_used_bytes:500,max_rss_kib:1,user_cpu_microseconds:25,system_cpu_microseconds:10}
  });
  assert.equal(result.elapsed_ms,1250);
  assert.equal(result.cpu.effective_ceiling_cores,2);
  assert.equal(result.memory.effective_ceiling_bytes,10_000);
  assert.equal(result.memory.effective_available_bytes,6_000);
  assert.equal(result.request_budget.request_envelope_ms,80_500);
  assert.equal(result.hard_limits.cpu_quota_verified,true);
  assert.equal(result.hard_limits.memory_limit_verified,true);
  assert.equal(result.hard_limits.disk_quota_verified,false);
  assert.equal(result.hard_limits.workflow_wall_limit_declared,true);
  assert.equal(result.hard_limits.total_resource_ceiling_verified,false);
  assert.deepEqual(result.warnings,['per_process_disk_quota_unverified']);
  assert.equal(result.publication_enabled,false);
  assert.equal(result.external_delivery_performed,false);
});

test('missing cgroup limits remain explicit instead of turning host totals into hard enforcement',()=>{
  const result=buildResourceObservation({
    startedAt:'2026-11-24T19:00:00.000Z',observedAt:'2026-11-24T19:00:00.001Z',activeWatches:0,policy,
    host:{available_cpu_cores:4,total_memory_bytes:1000,free_memory_bytes:500},
    cgroup:{cpu_quota_cores:null,memory_limit_bytes:null,memory_current_bytes:null,
      warnings:['cgroup_v2_unavailable']},disk:{total_bytes:null,available_bytes:null},usage:{}
  });
  assert.equal(result.cpu.effective_ceiling_cores,4);
  assert.equal(result.memory.effective_ceiling_bytes,1000);
  assert.equal(result.hard_limits.total_resource_ceiling_verified,false);
  assert.deepEqual(result.warnings,[
    'cgroup_v2_unavailable','hard_cpu_quota_unverified','hard_memory_limit_unverified',
    'per_process_disk_quota_unverified','workflow_wall_limit_unverified']);
});

test('cgroup reader takes strictest CPU and memory ancestor limits',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-cgroup-'));
  const group=path.join(dir,'child'),membership=path.join(dir,'membership');
  try{
    await fs.mkdir(group);
    await fs.writeFile(path.join(dir,'cgroup.controllers'),'cpu memory');
    await fs.writeFile(path.join(dir,'cpu.max'),'400000 100000');
    await fs.writeFile(path.join(dir,'memory.max'),'10000');
    await fs.writeFile(path.join(dir,'memory.current'),'1000');
    await fs.writeFile(path.join(group,'cpu.max'),'200000 100000');
    await fs.writeFile(path.join(group,'memory.max'),'8000');
    await fs.writeFile(path.join(group,'memory.current'),'3000');
    await fs.writeFile(membership,'0::/child\n');
    const result=await readCgroupV2Limits({root:dir,membership});
    assert.equal(result.cpu_quota_cores,2);
    assert.equal(result.memory_limit_bytes,8000);
    assert.equal(result.memory_current_bytes,3000);
    assert.equal(result.memory_available_bytes,5000);
    assert.deepEqual(result.warnings,[]);
  }finally{await fs.rm(dir,{recursive:true,force:true});}
});

test('cgroup reader uses strictest remaining memory headroom even when a child has the smaller limit',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-cgroup-pressure-'));
  const group=path.join(dir,'child'),membership=path.join(dir,'membership');
  try{
    await fs.mkdir(group);
    await fs.writeFile(path.join(dir,'cgroup.controllers'),'cpu memory');
    await fs.writeFile(path.join(dir,'cpu.max'),'max 100000');
    await fs.writeFile(path.join(dir,'memory.max'),'10000');
    await fs.writeFile(path.join(dir,'memory.current'),'9500');
    await fs.writeFile(path.join(group,'cpu.max'),'max 100000');
    await fs.writeFile(path.join(group,'memory.max'),'8000');
    await fs.writeFile(path.join(group,'memory.current'),'1000');
    await fs.writeFile(membership,'0::/child\n');
    const cgroup=await readCgroupV2Limits({root:dir,membership});
    assert.equal(cgroup.memory_limit_bytes,8000);
    assert.equal(cgroup.memory_current_bytes,1000);
    assert.equal(cgroup.memory_available_bytes,500);
    const result=buildResourceObservation({
      startedAt:'2026-11-24T19:00:00.000Z',observedAt:'2026-11-24T19:00:00.001Z',
      activeWatches:0,policy,host:{available_cpu_cores:4,total_memory_bytes:20_000,free_memory_bytes:15_000},
      cgroup,disk:{total_bytes:50_000,available_bytes:20_000},usage:{}});
    assert.equal(result.memory.effective_ceiling_bytes,8000);
    assert.equal(result.memory.effective_available_bytes,500);
  }finally{await fs.rm(dir,{recursive:true,force:true});}
});

test('live collector is bounded evidence and never claims a complete total-resource ceiling',async()=>{
  const result=await collectResourceObservation({startedAt:new Date(Date.now()-1).toISOString(),activeWatches:0,policy});
  assert.equal(result.type,'monitor_runtime_resources');
  assert.equal(result.scope,'current_monitor_process_and_execution_host_only');
  assert.equal(result.hard_limits.total_resource_ceiling_verified,false);
  assert.equal(result.request_budget.max_active_watches,MAX_ACTIVE_WATCHES);
  assert.ok(result.disk.filesystem_total_bytes===null || result.disk.filesystem_total_bytes>0);
});

test('only the three five-minute monitor workflows declare the retained wall limit',async()=>{
  for(const name of ['free-monitor-worker.yml','free-monitor-diagnostic.yml','free-monitor-verify.yml']){
    const source=await fs.readFile(path.join(root,'.github/workflows',name),'utf8');
    assert.match(source,/MONITOR_WORKFLOW_WALL_LIMIT_MS: 300000/);
    assert.match(source,/timeout-minutes: 5/);
  }
});

test('worker retains current resource evidence in the atomic state pair without treating it as a watch',async t=>{
  // This test exercises a local invocation even when the suite runs in scheduled CI.
  const previousEventName=process.env.GITHUB_EVENT_NAME;
  t.after(()=>{
    if(previousEventName===undefined) delete process.env.GITHUB_EVENT_NAME;
    else process.env.GITHUB_EVENT_NAME=previousEventName;
  });
  process.env.GITHUB_EVENT_NAME='local';

  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-runtime-state-'));
  const options={watchesPath:path.join(dir,'watches.json'),statePath:path.join(dir,'state.json'),
    eventsPath:path.join(dir,'events.json'),intervalMs:0,maxAttempts:1};
  t.mock.method(globalThis,'fetch',async()=>new Response('healthy'));
  try{
    await fs.writeFile(options.watchesPath,JSON.stringify([{id:'fixture',targetUrl:'https://fixture.invalid/'}]));
    const first=await runWorker(options);
    const retained=JSON.parse(await fs.readFile(options.statePath,'utf8'));
    assert.deepEqual(first.resources,retained[RUNTIME_STATE_KEY]);
    assert.equal(retained[RUNTIME_STATE_KEY].type,'monitor_runtime_resources');
    assert.equal(retained[RUNTIME_STATE_KEY].cadence.invocation_source,'local');
    assert.equal(retained[RUNTIME_STATE_KEY].cadence.status,'non_scheduled_invocation_no_history');
    assert.equal(retained[RUNTIME_STATE_KEY].cadence.prerequisite_passed,false);
    assert.equal(retained.fixture.last_status,200);
    const second=await runWorker(options);
    assert.equal(second.ok,true);
    assert.equal(second.results.length,1);
    assert.equal(second.resources.cadence.status,'non_scheduled_invocation');
    assert.equal(second.resources.cadence.prerequisite_passed,false);
  }finally{await fs.rm(dir,{recursive:true,force:true});}
});

test('reserved runtime key is rejected as a watch before requests or persistence',async t=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-runtime-reserved-'));
  const options={watchesPath:path.join(dir,'watches.json'),statePath:path.join(dir,'state.json'),
    eventsPath:path.join(dir,'events.json')};
  let requests=0;
  t.mock.method(globalThis,'fetch',async()=>{requests++;return new Response('wrong');});
  try{
    await fs.writeFile(options.watchesPath,JSON.stringify([{id:RUNTIME_STATE_KEY,targetUrl:'https://fixture.invalid/'}]));
    await assert.rejects(runWorker(options),/reserved monitor runtime state id/);
    assert.equal(requests,0);
    await assert.rejects(fs.stat(options.statePath),{code:'ENOENT'});
    await assert.rejects(fs.stat(options.eventsPath),{code:'ENOENT'});
  }finally{await fs.rm(dir,{recursive:true,force:true});}
});
