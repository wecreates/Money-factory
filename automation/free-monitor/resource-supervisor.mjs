import fs from 'node:fs/promises';
import path from 'node:path';
import {execFile,spawn} from 'node:child_process';

const PRLIMIT='/usr/bin/prlimit';
const GETCONF='/usr/bin/getconf';
const safePositive=(value,label)=>{
  if(!Number.isSafeInteger(value) || value<1) throw new Error(`${label} must be a positive safe integer`);
  return value;
};

async function executable(file){
  const absolute=path.resolve(file);
  const stat=await fs.stat(absolute);
  if(!stat.isFile()) throw new Error('bounded command must be a regular file');
  await fs.access(absolute,fs.constants.X_OK);
  return absolute;
}
async function directoryBytesOnce(root,{entryLimit=10_000}={}){
  const pending=[root];
  let bytes=0,entries=0;
  while(pending.length){
    const current=pending.pop();
    const stat=await fs.lstat(current);
    if(stat.isSymbolicLink()) throw new Error('bounded output root cannot contain symbolic links');
    if(stat.isDirectory()){
      for(const name of await fs.readdir(current)){
        if(++entries>entryLimit) throw new Error(`bounded output root exceeds ${entryLimit} entry limit`);
        pending.push(path.join(current,name));
      }
    }else if(stat.isFile()) bytes+=stat.size;
    else throw new Error('bounded output root contains unsupported file type');
  }
  return bytes;
}

async function directoryBytes(root,{entryLimit=10_000,transientRetries=4}={}){
  for(let attempt=0;;attempt++){
    try{return await directoryBytesOnce(root,{entryLimit});}
    catch(error){
      // Atomic writers can rename or remove a child after readdir but before
      // lstat. Retry only that transient missing-path snapshot race. Symlinks,
      // special files and every other error continue to fail closed at once.
      if(error.code!=='ENOENT' || attempt>=transientRetries) throw error;
      await new Promise(resolve=>setTimeout(resolve,1));
    }
  }
}

async function processSample(pid){
  try{
    const [status,stat]=await Promise.all([
      fs.readFile(`/proc/${pid}/status`,'utf8'),fs.readFile(`/proc/${pid}/stat`,'utf8')]);
    const rss=Number(status.match(/^VmRSS:\s+(\d+)\s+kB$/m)?.[1]??0)*1024;
    const fields=stat.slice(stat.lastIndexOf(') ')+2).trim().split(/\s+/);
    return {rss_bytes:rss,user_cpu_ticks:Number(fields[11]??0),system_cpu_ticks:Number(fields[12]??0)};
  }catch(error){
    if(error.code==='ENOENT' || error.code==='ESRCH') return null;
    throw error;
  }
}

async function clockTicksPerSecond(){
  await executable(GETCONF);
  return new Promise((resolve,reject)=>{
    execFile(GETCONF,['CLK_TCK'],{encoding:'utf8',timeout:1_000,maxBuffer:256},(error,stdout)=>{
      if(error) return reject(error);
      const value=Number(String(stdout).trim());
      if(!Number.isSafeInteger(value) || value<1) return reject(new Error('invalid CLK_TCK value'));
      resolve(value);
    });
  });
}

async function processGroupMember(pid,processGroup){
  try{
    const statPath=`/proc/${pid}/stat`;
    const stat=await fs.readFile(statPath,'utf8');
    const fields=stat.slice(stat.lastIndexOf(') ')+2).trim().split(/\s+/);
    if(Number(fields[2])!==processGroup) return null;
    const status=await fs.readFile(`/proc/${pid}/status`,'utf8');
    const finalStat=await fs.readFile(statPath,'utf8');
    const finalFields=finalStat.slice(finalStat.lastIndexOf(') ')+2).trim().split(/\s+/);
    if(Number(finalFields[2])!==processGroup || finalFields[19]!==fields[19]) return null;
    return {state:finalFields[0],rss_bytes:Number(status.match(/^VmRSS:\s+(\d+)\s+kB$/m)?.[1]??0)*1024,
      user_cpu_ticks:Number(finalFields[11]??0),system_cpu_ticks:Number(finalFields[12]??0)};
  }catch(error){
    if(error.code==='ENOENT' || error.code==='ESRCH') return null;
    throw error;
  }
}

async function processGroupSample(processGroup,{processLimit=4_096}={}){
  const entries=(await fs.readdir('/proc',{withFileTypes:true}))
    .filter(entry=>entry.isDirectory() && /^\d+$/.test(entry.name));
  if(entries.length>processLimit) throw new Error(`process table exceeds ${processLimit} entry limit`);
  const samples=(await Promise.all(entries.map(entry=>processGroupMember(entry.name,processGroup))))
    .filter(Boolean);
  return {process_count:samples.length,
    live_process_count:samples.filter(item=>item.state!=='Z').length,
    rss_bytes:samples.reduce((total,item)=>total+item.rss_bytes,0),
    user_cpu_ticks:samples.reduce((total,item)=>total+item.user_cpu_ticks,0),
    system_cpu_ticks:samples.reduce((total,item)=>total+item.system_cpu_ticks,0)};
}

function killGroup(pid){
  try{process.kill(-pid,'SIGKILL');}
  catch{
    try{process.kill(pid,'SIGKILL');}catch{}
  }
}

export async function runBoundedProcess({command,args=[],cwd,outputRoot=cwd,limits,
  env=process.env,pollMs=20}={}){
  if(process.platform!=='linux') throw new Error('bounded resource supervisor requires Linux');
  if(!Array.isArray(args) || !args.every(item=>typeof item==='string')) throw new Error('bounded args must be strings');
  const executablePath=await executable(command);
  await executable(PRLIMIT);
  const work=path.resolve(cwd??'.'),output=path.resolve(outputRoot??work);
  const [workStat,outputStat]=await Promise.all([fs.stat(work),fs.stat(output)]);
  if(!workStat.isDirectory() || !outputStat.isDirectory()) throw new Error('bounded work and output roots must be directories');
  const cpuSeconds=safePositive(limits?.cpuSeconds,'CPU seconds');
  const addressSpaceBytes=safePositive(limits?.addressSpaceBytes,'address-space bytes');
  const fileSizeBytes=safePositive(limits?.fileSizeBytes,'file-size bytes');
  const totalOutputBytes=safePositive(limits?.totalOutputBytes,'total-output bytes');
  const wallMs=safePositive(limits?.wallMs,'wall milliseconds');
  const totalCpuSeconds=limits?.totalCpuSeconds===undefined?null:
    safePositive(limits.totalCpuSeconds,'total CPU seconds');
  const totalMemoryBytes=limits?.totalMemoryBytes===undefined?null:
    safePositive(limits.totalMemoryBytes,'total memory bytes');
  safePositive(pollMs,'poll milliseconds');
  const before=await directoryBytes(output);
  if(before>totalOutputBytes) throw new Error('bounded output root already exceeds total-output limit');

  const ticksPerSecond=totalCpuSeconds===null?null:await clockTicksPerSecond();
  const startedAt=new Date().toISOString(),started=Date.now();
  const child=spawn(PRLIMIT,[`--cpu=${cpuSeconds}:${cpuSeconds}`,
    `--as=${addressSpaceBytes}:${addressSpaceBytes}`,`--fsize=${fileSizeBytes}:${fileSizeBytes}`,
    '--',executablePath,...args],{cwd:work,env,detached:true,stdio:'ignore'});
  let closed=false,closedAt=null,termination=null,peakDisk=before,peakRss=0,peakUserTicks=0,peakSystemTicks=0,
    peakTreeRss=0,peakTreeUserTicks=0,peakTreeSystemTicks=0,peakTreeCpuTicks=0,peakTreeProcesses=0;
  const close=new Promise((resolve,reject)=>{
    child.once('error',error=>{closedAt=Date.now();closed=true;reject(error);});
    child.once('close',(code,signal)=>{closedAt=Date.now();closed=true;resolve({code,signal});});
  });
  const wallTimer=setTimeout(()=>{
    if(!closed && !termination){termination='wall_limit';killGroup(child.pid);}
  },wallMs);
  const monitor=(async()=>{
    while(!closed){
      try{
        const [disk,sample,tree]=await Promise.all([directoryBytes(output),processSample(child.pid),
          totalCpuSeconds!==null || totalMemoryBytes!==null?processGroupSample(child.pid):null]);
        peakDisk=Math.max(peakDisk,disk);
        if(sample){
          peakRss=Math.max(peakRss,sample.rss_bytes);
          peakUserTicks=Math.max(peakUserTicks,sample.user_cpu_ticks);
          peakSystemTicks=Math.max(peakSystemTicks,sample.system_cpu_ticks);
        }
        if(tree){
          peakTreeRss=Math.max(peakTreeRss,tree.rss_bytes);
          peakTreeUserTicks=Math.max(peakTreeUserTicks,tree.user_cpu_ticks);
          peakTreeSystemTicks=Math.max(peakTreeSystemTicks,tree.system_cpu_ticks);
          peakTreeCpuTicks=Math.max(peakTreeCpuTicks,tree.user_cpu_ticks+tree.system_cpu_ticks);
          peakTreeProcesses=Math.max(peakTreeProcesses,tree.process_count);
        }
        if(disk>totalOutputBytes && !termination){termination='total_output_limit';killGroup(child.pid);}
        if(totalMemoryBytes!==null && tree?.rss_bytes>totalMemoryBytes && !termination){
          termination='total_memory_limit';killGroup(child.pid);
        }
        if(totalCpuSeconds!==null
            && (tree?.user_cpu_ticks??0)+(tree?.system_cpu_ticks??0)>totalCpuSeconds*ticksPerSecond
            && !termination){
          termination='total_cpu_limit';killGroup(child.pid);
        }
        if(Date.now()-started>wallMs && !termination){termination='wall_limit';killGroup(child.pid);}
      }catch(error){
        if(!termination){termination=`measurement_failed:${error.message}`;killGroup(child.pid);}
      }
      await new Promise(resolve=>setTimeout(resolve,pollMs));
    }
  })();
  let result,closeError;
  try{result=await close;}catch(error){closeError=error;}
  finally{clearTimeout(wallTimer);}
  await monitor;
  if(closeError) throw closeError;
  let residualTree=await processGroupSample(child.pid);
  const residualBeforeKill=residualTree.live_process_count;
  if(residualBeforeKill>0){
    if(!termination) termination='orphaned_process_group';
    killGroup(child.pid);
    for(let attempt=0;attempt<200 && residualTree.live_process_count>0;attempt++){
      await new Promise(resolve=>setTimeout(resolve,5));
      residualTree=await processGroupSample(child.pid);
    }
  }
  const after=await directoryBytes(output);
  peakDisk=Math.max(peakDisk,after);
  const elapsed=closedAt-started;
  // A short process can finish between watchdog polls. Recheck both aggregate
  // output and wall time after close so that fast limit violations cannot
  // retain a successful receipt.
  if(after>totalOutputBytes && !termination) termination='total_output_limit_post_exit';
  if(elapsed>wallMs && !termination) termination='wall_limit_post_exit';
  const succeeded=result.code===0 && result.signal===null && termination===null;
  return {schema_version:1,type:'bounded_process_resource_receipt',started_at:startedAt,
    finished_at:new Date(closedAt).toISOString(),elapsed_ms:elapsed,command:path.basename(executablePath),
    success:succeeded,
    exit_code:result.code,signal:result.signal,termination:termination??(result.signal?'limit_signal':'process_exit'),
    limits:{cpu_seconds:cpuSeconds,address_space_bytes:addressSpaceBytes,file_size_bytes:fileSizeBytes,
      total_output_bytes:totalOutputBytes,wall_ms:wallMs,total_cpu_seconds:totalCpuSeconds,
      total_memory_bytes:totalMemoryBytes,clock_ticks_per_second:ticksPerSecond},
    observed:{output_before_bytes:before,peak_output_bytes:peakDisk,output_after_bytes:after,
      peak_rss_bytes:peakRss,peak_user_cpu_ticks:peakUserTicks,peak_system_cpu_ticks:peakSystemTicks,
      peak_tree_rss_bytes:peakTreeRss,peak_tree_user_cpu_ticks:peakTreeUserTicks,
      peak_tree_system_cpu_ticks:peakTreeSystemTicks,peak_tree_cpu_ticks:peakTreeCpuTicks,
      peak_tree_processes:peakTreeProcesses,residual_live_processes_before_kill:residualBeforeKill,
      residual_live_processes_after_kill:residualTree.live_process_count},
    enforcement:{cpu_time_rlimit_per_process:true,address_space_rlimit_per_process:true,
      file_size_rlimit_per_process:true,aggregate_output_process_group_watchdog:true,
      wall_process_group_watchdog:true,aggregate_cpu_process_group_watchdog:totalCpuSeconds!==null,
      aggregate_memory_process_group_watchdog:totalMemoryBytes!==null,
      total_cpu_tree_quota:false,total_memory_tree_quota:false},
    publication_enabled:false,paid_inference_enabled:false,
    external_delivery_performed:false};
}

