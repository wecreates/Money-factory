import fs from 'node:fs/promises';
import {runWorker, normalizeWatch, isMainEntry} from './worker.mjs';

// Two bounded observations verify cadence and health, not a 24-hour soak.
export function evaluateVerification(watches,before,mid,after,first,second){
  const active=watches.map(normalizeWatch).filter(w=>w.status==='active');
  if(new Set(active.map(w=>w.id)).size!==active.length) throw new Error('duplicate active watch id');
  const positiveTime=value=>typeof value==='number' && Number.isFinite(value) && value>0;
  const healthy=(state,cycle,id,targetUrl)=>{
    const results=cycle.results?.filter(r=>r.id===id)??[];
    const result=results[0];
    return cycle.ok===true && results.length===1 && result.checked===true && !result.error &&
      typeof result.status==='number' && result.status>=200 && result.status<300 &&
      state?.status==='active' && state.targetUrl===targetUrl && !state.last_error && state.last_status===result.status &&
      state.last_checked_at===result.last_checked_at;
  };
  const checks=active.map(({id,targetUrl})=>{
    const initial=before[id]?.last_checked_at??0;
    const one=mid[id]?.last_checked_at;
    const two=after[id]?.last_checked_at;
    const advancedFirst=typeof initial==='number' && Number.isFinite(initial) && initial>=0 && positiveTime(one) && one>initial;
    const advancedSecond=positiveTime(one) && positiveTime(two) && two>one;
    const firstHealthy=healthy(mid[id],first,id,targetUrl),secondHealthy=healthy(after[id],second,id,targetUrl);
    return {id,before_last_checked_at:initial,first_cycle_last_checked_at:one??null,
      second_cycle_last_checked_at:two??null,advanced_first_cycle:advancedFirst,
      advanced_second_cycle:advancedSecond,first_cycle_healthy:firstHealthy,
      second_cycle_healthy:secondHealthy,pass:advancedFirst && advancedSecond && firstHealthy && secondHealthy};
  });
  return {active_watch_count:active.length,watches:checks,
    pass:active.length>0 && checks.every(check=>check.pass)};
}

export async function runVerification({watchesPath='FREE_MONITOR_WATCHES.json',
  statePath='FREE_MONITOR_STATE.json',eventsPath='FREE_MONITOR_EVENTS.json',
  reportPath='FREE_MONITOR_VERIFICATION.json'}={}){
  let report;
  try{
  const watches=JSON.parse(await fs.readFile(watchesPath,'utf8'));
  const before=JSON.parse(await fs.readFile(statePath,'utf8').catch(()=> '{}'));
  const first=await runWorker({watchesPath,statePath,eventsPath,intervalMs:0});
  const mid=JSON.parse(await fs.readFile(statePath,'utf8'));
  await new Promise(r=>setTimeout(r,25));
  const second=await runWorker({watchesPath,statePath,eventsPath,intervalMs:0});
  const after=JSON.parse(await fs.readFile(statePath,'utf8'));
  report={checked_at:new Date().toISOString(),
    scope:'Two immediate checks of configured active targets; not continuous uptime or a 24-hour soak.',
    ...evaluateVerification(watches,before,mid,after,first,second),first_cycle:first,second_cycle:second};
  }catch(error){
    report={checked_at:new Date().toISOString(),pass:false,error:String(error),
      scope:'Verification could not complete; no cadence or health acceptance.'};
  }
  await fs.writeFile(reportPath,JSON.stringify(report,null,2)+'\n');
  return report;
}

if(isMainEntry(import.meta.url,process.argv[1])){
  const report=await runVerification();
  console.log(JSON.stringify(report,null,2));
  if(!report.pass) process.exitCode=1;
}
