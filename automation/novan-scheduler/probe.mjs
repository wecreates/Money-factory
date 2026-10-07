import fs from 'node:fs/promises';
const urls=[
  'https://cyzorcreations.com/openapi.json',
  'https://cyzorcreations.com/api/v1/ext/watch?clientId=cyzor-probe-readonly'
];
async function get(url){
  const r=await fetch(url,{headers:{'accept':'application/json,text/plain,*/*'}});
  const text=await r.text();
  let data; try{data=JSON.parse(text)}catch{data={raw:text}};
  return {url,status:r.status,ok:r.ok,headers:Object.fromEntries(r.headers.entries()),data};
}
const [spec,watch]=await Promise.all(urls.map(get));
const paths=spec.data?.paths||{};
const interesting=Object.entries(paths).filter(([p,v])=>/(watch|sched|cron|monitor|job|worker|admin|task|queue|heartbeat|health)/i.test(p+' '+JSON.stringify(v))).map(([path,ops])=>({path,methods:Object.keys(ops||{}),ops}));
const out={
  checked_at:new Date().toISOString(),
  spec_status:spec.status,
  spec_title:spec.data?.info?.title||null,
  spec_version:spec.data?.info?.version||null,
  path_count:Object.keys(paths).length,
  interesting_routes:interesting,
  watch_probe:{status:watch.status,ok:watch.ok,data:watch.data},
  server_headers:spec.headers
};
await fs.writeFile('NOVAN_SCHEDULER_PROBE.json',JSON.stringify(out,null,2)+'\n');
console.log(JSON.stringify(out,null,2));
