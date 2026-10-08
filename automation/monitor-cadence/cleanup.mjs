import fs from 'node:fs/promises';

const API=process.env.CYZOR_MONITOR_API||'https://content-control-render-worker.onrender.com/api/v1/ext';
const state=JSON.parse(await fs.readFile('MONITOR_CADENCE_TEST.json','utf8'));
const previous=JSON.parse(await fs.readFile('MONITOR_CADENCE_RESULT.json','utf8').catch(()=> '{}'));

async function req(url,options={}){
  const res=await fetch(url,options);
  const text=await res.text();
  let data;
  try{data=JSON.parse(text)}catch{data={raw:text}};
  return {status:res.status,ok:res.ok,data};
}

const listBefore=await req(`${API}/watch?clientId=${encodeURIComponent(state.clientId)}`);
if(!listBefore.ok || !Array.isArray(listBefore.data?.watches)) throw new Error('watch list failed');
const stored=listBefore.data.watches.find(w=>w.id===state.watchId);
const currentLastChecked=stored?.last_checked_at ?? previous.current_last_checked_at ?? null;
const advanced=stored ? String(currentLastChecked)!==String(state.initial_last_checked_at) : Boolean(previous.scheduled_backend_check_advanced);

let deletion={attempted:false,completed:false,status:null};
if(stored){
  deletion.attempted=true;
  const del=await req(`${API}/watch/${encodeURIComponent(state.watchId)}?clientId=${encodeURIComponent(state.clientId)}`,{method:'DELETE'});
  deletion={attempted:true,completed:del.ok,status:del.status,response:del.data};
  if(!del.ok) throw new Error(`delete failed HTTP ${del.status}`);
}

const finalList=await req(`${API}/watch?clientId=${encodeURIComponent(state.clientId)}`);
if(!finalList.ok || !Array.isArray(finalList.data?.watches)) throw new Error('final watch list failed');

const result={
  checked_at:new Date().toISOString(),
  clientId:state.clientId,
  stored_watchId:state.watchId,
  watch_found_before_cleanup:Boolean(stored),
  production_get_status:listBefore.status,
  initial_last_checked_at:String(state.initial_last_checked_at),
  current_last_checked_at:currentLastChecked==null?null:String(currentLastChecked),
  scheduled_backend_check_advanced:advanced,
  cadence_result:advanced?'PASS':'FAIL',
  delete_attempted:deletion.attempted,
  delete_completed:deletion.completed || !stored,
  delete_status:deletion.status,
  final_watch_count:finalList.data.watches.length,
  final_watch_list_empty:finalList.data.watches.length===0,
  overall_pass:advanced && finalList.data.watches.length===0,
  remaining_backend_blocker:advanced?null:'Production scheduler still has not advanced last_checked_at; cleanup is fixed, but the cadence worker itself remains unproven/broken.',
  evidence:{watch_status:stored?.status??state.status,kind:stored?.kind??'change',target_url:stored?.target_url??state.targetUrl,label:stored?.label??'CYZOR cadence smoke test'}
};
await fs.writeFile('MONITOR_CADENCE_RESULT.json',JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result,null,2));
if(!result.final_watch_list_empty) process.exitCode=1;
