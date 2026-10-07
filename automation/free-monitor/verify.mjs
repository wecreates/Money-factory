import fs from 'node:fs/promises';
import {runWorker} from './worker.mjs';

const statePath='FREE_MONITOR_STATE.json';
const eventsPath='FREE_MONITOR_EVENTS.json';

const before=JSON.parse(await fs.readFile(statePath,'utf8'));
const firstBefore=before['cyzor-free-monitor-smoke']?.last_checked_at ?? null;

const first=await runWorker({statePath,eventsPath,intervalMs:0});
const mid=JSON.parse(await fs.readFile(statePath,'utf8'));
const firstAfter=mid['cyzor-free-monitor-smoke']?.last_checked_at ?? null;

await new Promise(r=>setTimeout(r,25));

const second=await runWorker({statePath,eventsPath,intervalMs:0});
const after=JSON.parse(await fs.readFile(statePath,'utf8'));
const secondAfter=after['cyzor-free-monitor-smoke']?.last_checked_at ?? null;

const pass=Number(firstAfter)>Number(firstBefore||0) && Number(secondAfter)>Number(firstAfter);
const report={
  checked_at:new Date().toISOString(),
  before_last_checked_at:firstBefore,
  first_cycle_last_checked_at:firstAfter,
  second_cycle_last_checked_at:secondAfter,
  first_cycle:first,
  second_cycle:second,
  advanced_first_cycle:Number(firstAfter)>Number(firstBefore||0),
  advanced_second_cycle:Number(secondAfter)>Number(firstAfter),
  pass
};
await fs.writeFile('FREE_MONITOR_VERIFICATION.json',JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
if(!pass) process.exitCode=1;
