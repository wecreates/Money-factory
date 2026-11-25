import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';

const PRLIMIT='/usr/bin/prlimit';
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
  safePositive(pollMs,'poll milliseconds');
  const before=await directoryBytes(output);
  if(before>totalOutputBytes) throw new Error('bounded output root already exceeds total-output limit');

  const startedAt=new Date().toISOString(),started=Date.now();
  const child=spawn(PRLIMIT,[`--cpu=${cpuSeconds}:${cpuSeconds}`,
    `--as=${addressSpaceBytes}:${addressSpaceBytes}`,`--fsize=${fileSizeBytes}:${fileSizeBytes}`,
    '--',executablePath,...args],{cwd:work,env,detached:true,stdio:'ignore'});
  let closed=false,closedAt=null,termination=null,peakDisk=before,peakRss=0,peakUserTicks=0,peakSystemTicks=0;
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
        const [disk,sample]=await Promise.all([directoryBytes(output),processSample(child.pid)]);
        peakDisk=Math.max(peakDisk,disk);
        if(sample){
          peakRss=Math.max(peakRss,sample.rss_bytes);
          peakUserTicks=Math.max(peakUserTicks,sample.user_cpu_ticks);
          peakSystemTicks=Math.max(peakSystemTicks,sample.system_cpu_ticks);
        }
        if(disk>totalOutputBytes && !termination){termination='total_output_limit';killGroup(child.pid);}
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
      total_output_bytes:totalOutputBytes,wall_ms:wallMs},
    observed:{output_before_bytes:before,peak_output_bytes:peakDisk,output_after_bytes:after,
      peak_rss_bytes:peakRss,peak_user_cpu_ticks:peakUserTicks,peak_system_cpu_ticks:peakSystemTicks},
    enforcement:{cpu_time_rlimit_per_process:true,address_space_rlimit_per_process:true,
      file_size_rlimit_per_process:true,aggregate_output_process_group_watchdog:true,
      wall_process_group_watchdog:true,total_cpu_tree_quota:false,total_memory_tree_quota:false},
    publication_enabled:false,paid_inference_enabled:false,
    external_delivery_performed:false};
}

