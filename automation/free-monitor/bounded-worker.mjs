import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {runBoundedProcess} from './resource-supervisor.mjs';

function integerEnvironment(name){
  const raw=process.env[name];
  if(!/^\d+$/.test(raw??'')) throw new Error(`${name} must be an explicit positive integer`);
  const value=Number(raw);
  if(!Number.isSafeInteger(value) || value<1) throw new Error(`${name} must be an explicit positive integer`);
  return value;
}

function optionalIntegerEnvironment(name){
  return process.env[name]===undefined?undefined:integerEnvironment(name);
}

const outputRoot=process.env.MONITOR_OUTPUT_ROOT;
if(!outputRoot) throw new Error('MONITOR_OUTPUT_ROOT is required for bounded monitor execution');
const worker=fileURLToPath(new URL('./worker.mjs',import.meta.url));
const receipt=await runBoundedProcess({command:process.execPath,args:[worker,...process.argv.slice(2)],
  cwd:path.resolve(outputRoot),outputRoot:path.resolve(outputRoot),limits:{
    cpuSeconds:integerEnvironment('MONITOR_CPU_SECONDS'),
    addressSpaceBytes:integerEnvironment('MONITOR_ADDRESS_SPACE_BYTES'),
    fileSizeBytes:integerEnvironment('MONITOR_FILE_SIZE_BYTES'),
    totalOutputBytes:integerEnvironment('MONITOR_TOTAL_OUTPUT_BYTES'),
    totalCpuSeconds:optionalIntegerEnvironment('MONITOR_TOTAL_CPU_SECONDS'),
    totalMemoryBytes:optionalIntegerEnvironment('MONITOR_TOTAL_MEMORY_BYTES'),
    wallMs:integerEnvironment('MONITOR_BOUND_WALL_MS')}});
console.log(JSON.stringify(receipt,null,2));
if(!receipt.success) process.exitCode=2;
