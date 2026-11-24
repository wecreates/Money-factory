import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

export const RUNTIME_STATE_KEY='_monitor_runtime';
export const MAX_ACTIVE_WATCHES=4;
export const MAX_WORKER_ENVELOPE_MS=240_000;
export const MAX_DECLARED_WORKFLOW_WALL_MS=300_000;

const safeInteger=(value,minimum=0)=>Number.isSafeInteger(value) && value>=minimum;
const finitePositive=value=>typeof value==='number' && Number.isFinite(value) && value>0;

export function requestEnvelopeMs(activeWatches,{maxAttempts,requestTimeoutMs,retryBackoffMs}){
  if(!Number.isInteger(activeWatches) || activeWatches<0 || activeWatches>MAX_ACTIVE_WATCHES){
    throw new Error(`active watch count must be between 0 and ${MAX_ACTIVE_WATCHES}`);
  }
  const retryWaits=maxAttempts*(maxAttempts-1)/2;
  const envelope=activeWatches*(maxAttempts*requestTimeoutMs+retryWaits*retryBackoffMs);
  if(!Number.isSafeInteger(envelope) || envelope>MAX_WORKER_ENVELOPE_MS){
    throw new Error(`configured request envelope exceeds ${MAX_WORKER_ENVELOPE_MS} ms worker limit`);
  }
  return envelope;
}

export function declaredWorkflowWallLimit(value){
  if(value===undefined || value===null || value==='') return null;
  if(typeof value==='string' && !/^\d+$/.test(value)) throw new Error('workflow wall limit must be integer milliseconds');
  const limit=Number(value);
  if(!safeInteger(limit,1) || limit>MAX_DECLARED_WORKFLOW_WALL_MS){
    throw new Error(`workflow wall limit must be between 1 and ${MAX_DECLARED_WORKFLOW_WALL_MS} ms`);
  }
  return limit;
}

export function validateWallEnvelope(workflowWallLimitMs,requestEnvelope){
  const wall=declaredWorkflowWallLimit(workflowWallLimitMs);
  if(wall!==null && requestEnvelope>=wall){
    throw new Error('configured request envelope must be below declared workflow wall limit');
  }
  return wall;
}

async function readSmall(file,limit=4096){
  const handle=await fs.open(file,'r');
  try{
    const buffer=Buffer.alloc(limit+1);
    const {bytesRead}=await handle.read(buffer,0,buffer.length,0);
    if(bytesRead>limit) throw new Error('resource control file exceeds size limit');
    return buffer.subarray(0,bytesRead).toString('utf8').trim();
  }finally{await handle.close();}
}

function inside(root,current){return current===root || current.startsWith(root+path.sep);}

export async function readCgroupV2Limits({root='/sys/fs/cgroup',membership='/proc/self/cgroup'}={}){
  root=path.resolve(root);
  const warnings=[];
  try{await fs.access(path.join(root,'cgroup.controllers'));}
  catch{return {cpu_quota_cores:null,memory_limit_bytes:null,memory_current_bytes:null,warnings:['cgroup_v2_unavailable']};}
  let relative='/';
  try{
    const line=(await readSmall(membership)).split('\n').find(item=>item.startsWith('0::'));
    if(line) relative=line.slice(3);
  }catch{warnings.push('cgroup_membership_unreadable');}
  let current=path.resolve(root,relative.replace(/^\/+/,''));
  if(!inside(root,current)){
    return {cpu_quota_cores:null,memory_limit_bytes:null,memory_current_bytes:null,
      warnings:['cgroup_membership_outside_mount']};
  }
  try{if(!(await fs.stat(current)).isDirectory()) current=root;}
  catch{current=root;warnings.push('cgroup_membership_missing');}
  const cpu=[],memory=[];
  for(let directory=current;inside(root,directory);directory=path.dirname(directory)){
    try{
      const [quota,period]=String(await readSmall(path.join(directory,'cpu.max'))).split(/\s+/);
      if(quota!=='max'){
        const value=Number(quota)/Number(period);
        if(!finitePositive(value)) throw new Error('invalid cpu quota');
        cpu.push(value);
      }
    }catch(error){if(error.code!=='ENOENT') warnings.push('cgroup_cpu_unreadable');}
    try{
      const maximum=await readSmall(path.join(directory,'memory.max'));
      if(maximum!=='max'){
        const limit=Number(maximum);
        const used=Number(await readSmall(path.join(directory,'memory.current')));
        if(!safeInteger(limit,1) || !safeInteger(used)) throw new Error('invalid memory limit');
        memory.push({limit,current:used});
      }
    }catch(error){if(error.code!=='ENOENT') warnings.push('cgroup_memory_unreadable');}
    if(directory===root) break;
  }
  const memoryLimit=memory.length?Math.min(...memory.map(item=>item.limit)):null;
  const memoryAvailable=memory.length?Math.min(...memory.map(item=>Math.max(0,item.limit-item.current))):null;
  const limitingMemory=memory.find(item=>item.limit===memoryLimit);
  return {cpu_quota_cores:cpu.length?Math.min(...cpu):null,memory_limit_bytes:memoryLimit,
    memory_current_bytes:limitingMemory?.current??null,memory_available_bytes:memoryAvailable,
    warnings:[...new Set(warnings)].sort()};
}

function integerOrNull(value){return safeInteger(value)?value:null;}

export function buildResourceObservation({observedAt,startedAt,activeWatches,policy,workflowWallLimitMs=null,
  host,cgroup,disk,usage}){
  const requestEnvelope=requestEnvelopeMs(activeWatches,policy);
  const workflowWallLimit=validateWallEnvelope(workflowWallLimitMs,requestEnvelope);
  const availableCpu=finitePositive(host.available_cpu_cores)?host.available_cpu_cores:null;
  const quotaCpu=finitePositive(cgroup.cpu_quota_cores)?cgroup.cpu_quota_cores:null;
  const effectiveCpu=availableCpu===null?quotaCpu:quotaCpu===null?availableCpu:Math.min(availableCpu,quotaCpu);
  const hostMemory=integerOrNull(host.total_memory_bytes),cgroupMemory=integerOrNull(cgroup.memory_limit_bytes);
  const memoryCeiling=hostMemory===null?cgroupMemory:cgroupMemory===null?hostMemory:Math.min(hostMemory,cgroupMemory);
  const hostAvailable=integerOrNull(host.free_memory_bytes);
  const cgroupRemaining=integerOrNull(cgroup.memory_available_bytes);
  const memoryAvailable=hostAvailable===null?cgroupRemaining:cgroupRemaining===null
    ? hostAvailable:Math.min(hostAvailable,cgroupRemaining);
  const warnings=[...(cgroup.warnings??[])];
  if(quotaCpu===null) warnings.push('hard_cpu_quota_unverified');
  if(cgroupMemory===null) warnings.push('hard_memory_limit_unverified');
  if(workflowWallLimit===null) warnings.push('workflow_wall_limit_unverified');
  warnings.push('per_process_disk_quota_unverified');
  const observedMs=Date.parse(observedAt),startedMs=Date.parse(startedAt);
  if(!safeInteger(observedMs,1) || !safeInteger(startedMs,1) || observedMs<startedMs){
    throw new Error('valid ordered resource observation timestamps required');
  }
  return {schema_version:1,type:'monitor_runtime_resources',observed_at:new Date(observedMs).toISOString(),
    started_at:new Date(startedMs).toISOString(),elapsed_ms:observedMs-startedMs,
    scope:'current_monitor_process_and_execution_host_only',
    cpu:{available_cores:availableCpu,cgroup_quota_cores:quotaCpu,effective_ceiling_cores:effectiveCpu},
    memory:{host_total_bytes:hostMemory,host_available_bytes:hostAvailable,cgroup_limit_bytes:cgroupMemory,
      cgroup_current_bytes:integerOrNull(cgroup.memory_current_bytes),effective_ceiling_bytes:memoryCeiling,
      cgroup_available_bytes:cgroupRemaining,effective_available_bytes:memoryAvailable},
    disk:{filesystem_total_bytes:integerOrNull(disk.total_bytes),filesystem_available_bytes:integerOrNull(disk.available_bytes),
      per_process_quota_bytes:null},
    process:{rss_bytes:integerOrNull(usage.rss_bytes),heap_used_bytes:integerOrNull(usage.heap_used_bytes),
      max_rss_kib:integerOrNull(usage.max_rss_kib),user_cpu_microseconds:integerOrNull(usage.user_cpu_microseconds),
      system_cpu_microseconds:integerOrNull(usage.system_cpu_microseconds)},
    request_budget:{active_watches:activeWatches,max_active_watches:MAX_ACTIVE_WATCHES,max_attempts:policy.maxAttempts,
      request_timeout_ms:policy.requestTimeoutMs,retry_backoff_ms:policy.retryBackoffMs,
      request_envelope_ms:requestEnvelope,worker_envelope_limit_ms:MAX_WORKER_ENVELOPE_MS,
      workflow_wall_limit_ms:workflowWallLimit},
    hard_limits:{cpu_quota_verified:quotaCpu!==null,memory_limit_verified:cgroupMemory!==null,
      disk_quota_verified:false,workflow_wall_limit_declared:workflowWallLimit!==null,
      total_resource_ceiling_verified:false},
    warnings:[...new Set(warnings)].sort(),publication_enabled:false,external_delivery_performed:false};
}

export async function collectResourceObservation({startedAt,activeWatches,policy,workflowWallLimitMs=null,
  cwd=process.cwd()}={}){
  const observedAt=new Date().toISOString();
  let cgroup;
  try{cgroup=await readCgroupV2Limits();}
  catch{cgroup={cpu_quota_cores:null,memory_limit_bytes:null,memory_current_bytes:null,
    warnings:['cgroup_limits_unavailable']};}
  let disk={total_bytes:null,available_bytes:null};
  try{
    const stat=await fs.statfs(cwd,{bigint:true});
    const total=stat.blocks*stat.bsize,available=stat.bavail*stat.bsize;
    disk={total_bytes:total<=BigInt(Number.MAX_SAFE_INTEGER)?Number(total):null,
      available_bytes:available<=BigInt(Number.MAX_SAFE_INTEGER)?Number(available):null};
  }catch{cgroup.warnings=[...(cgroup.warnings??[]),'filesystem_capacity_unavailable'];}
  const usage=process.resourceUsage(),memory=process.memoryUsage();
  return buildResourceObservation({observedAt,startedAt,activeWatches,policy,
    workflowWallLimitMs,host:{available_cpu_cores:os.availableParallelism(),
      total_memory_bytes:os.totalmem(),free_memory_bytes:os.freemem()},
    cgroup,disk,usage:{rss_bytes:memory.rss,heap_used_bytes:memory.heapUsed,max_rss_kib:usage.maxRSS,
      user_cpu_microseconds:usage.userCPUTime,system_cpu_microseconds:usage.systemCPUTime}});
}
