import fs from 'node:fs/promises';
const API='https://cyzorcreations.com/api/v1/ext';
const clientId='cyzor-cadence-smoke-'+Date.now();
const payload={clientId,kind:'change',targetUrl:'https://example.com/',label:'CYZOR cadence smoke test'};
async function req(url,options={}){
 const r=await fetch(url,options); const text=await r.text(); let data; try{data=JSON.parse(text)}catch{data={raw:text}};
 if(!r.ok) throw new Error('HTTP '+r.status+' '+text);
 return data;
}
const created=await req(API+'/watch',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
const list=await req(API+'/watch?clientId='+encodeURIComponent(clientId));
const watch=(list.watches||[]).find(w=>w.id===created.id);
if(!watch) throw new Error('created watch not found');
const out={started_at:new Date().toISOString(),clientId,watchId:created.id,initial_last_checked_at:watch.last_checked_at,targetUrl:watch.target_url,status:watch.status};
console.log(JSON.stringify(out,null,2));
await fs.writeFile('cadence-test.json',JSON.stringify(out,null,2));
