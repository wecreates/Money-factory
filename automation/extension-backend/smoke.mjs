import {API,VERIFY,KINDS,clientId,watchPayload} from './spec.mjs';

async function body(res){ const text=await res.text(); try{return JSON.parse(text)}catch{return {raw:text}} }
async function req(url,options={}){
 const res=await fetch(url,options); const data=await body(res);
 return {status:res.status,ok:res.ok,data};
}
const cid=clientId();
const report={clientId:cid,startedAt:new Date().toISOString(),reads:{},created:[],deleted:[],verify:null,success:false};
try {
 report.reads.watches=await req(`${API}/watch?clientId=${encodeURIComponent(cid)}`);
 report.reads.events=await req(`${API}/events?clientId=${encodeURIComponent(cid)}`);
 if(!report.reads.watches.ok || !Array.isArray(report.reads.watches.data?.watches)) throw new Error('watch list contract failed');
 if(!report.reads.events.ok || !Array.isArray(report.reads.events.data?.events)) throw new Error('events contract failed');

 for(const kind of KINDS){
   const created=await req(`${API}/watch`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(watchPayload(cid,kind))});
   report.created.push({kind,...created});
   if(!created.ok) throw new Error(`create ${kind} failed HTTP ${created.status}`);
 }
 const list=await req(`${API}/watch?clientId=${encodeURIComponent(cid)}`);
 report.afterCreate=list;
 if(!list.ok || !Array.isArray(list.data?.watches)) throw new Error('post-create list failed');
 const ids=list.data.watches.map(w=>w.id).filter(Boolean);
 if(ids.length < KINDS.length) throw new Error('created watches missing ids');

 report.verify=await req(VERIFY,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({key:'CYZOR-INVALID-SMOKE-KEY'})});
 if(report.verify.status===404) throw new Error('license verify route missing');

 for(const id of ids){
   const deleted=await req(`${API}/watch/${encodeURIComponent(id)}?clientId=${encodeURIComponent(cid)}`,{method:'DELETE'});
   report.deleted.push({id,...deleted});
   if(!deleted.ok) throw new Error(`delete ${id} failed HTTP ${deleted.status}`);
 }
 const finalList=await req(`${API}/watch?clientId=${encodeURIComponent(cid)}`);
 report.finalList=finalList;
 if(!finalList.ok || (finalList.data?.watches||[]).length!==0) throw new Error('cleanup did not return empty watch list');
 report.success=true;
} catch(e){
 report.error=String(e?.stack||e);
 // best-effort cleanup if any IDs can still be discovered
 try{
   const list=await req(`${API}/watch?clientId=${encodeURIComponent(cid)}`);
   for(const w of list.data?.watches||[]) if(w.id) await req(`${API}/watch/${encodeURIComponent(w.id)}?clientId=${encodeURIComponent(cid)}`,{method:'DELETE'});
 }catch{}
} finally {
 report.finishedAt=new Date().toISOString();
 console.log(JSON.stringify(report,null,2));
}
if(!report.success) process.exitCode=1;
