import fs from 'node:fs/promises';
const API='https://cyzorcreations.com/api/v1/ext';
const clientId='cyzor-upsert-probe-'+Date.now();
const payload={clientId,kind:'change',targetUrl:'https://example.com/',label:'CYZOR upsert probe'};
async function req(url,options={}){
 const r=await fetch(url,options); const text=await r.text(); let data; try{data=JSON.parse(text)}catch{data={raw:text}};
 return {status:r.status,ok:r.ok,data};
}
const first=await req(API+'/watch',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
const list1=await req(API+'/watch?clientId='+encodeURIComponent(clientId));
await new Promise(r=>setTimeout(r,2500));
const second=await req(API+'/watch',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
const list2=await req(API+'/watch?clientId='+encodeURIComponent(clientId));
const before=list1.data?.watches?.[0]||null;
const after=list2.data?.watches?.[0]||null;
const ids=[...new Set((list2.data?.watches||[]).map(w=>w.id).filter(Boolean))];
const deleted=[];
for(const id of ids){
  const d=await req(API+'/watch/'+encodeURIComponent(id)+'?clientId='+encodeURIComponent(clientId),{method:'DELETE'});
  deleted.push({id,status:d.status,ok:d.ok});
}
const finalList=await req(API+'/watch?clientId='+encodeURIComponent(clientId));
const out={
 checked_at:new Date().toISOString(),clientId,
 first_create:first,second_create:second,
 first_watch_count:list1.data?.watches?.length??null,
 second_watch_count:list2.data?.watches?.length??null,
 before,after,
 same_id:before?.id&&after?.id?before.id===after.id:null,
 timestamp_advanced:before?.last_checked_at&&after?.last_checked_at?String(before.last_checked_at)!==String(after.last_checked_at):null,
 deleted,final_watch_count:finalList.data?.watches?.length??null
};
await fs.writeFile('WATCH_UPSERT_PROBE.json',JSON.stringify(out,null,2)+'\n');
console.log(JSON.stringify(out,null,2));
