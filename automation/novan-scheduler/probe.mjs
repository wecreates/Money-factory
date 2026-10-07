import fs from 'node:fs/promises';

async function get(url){
  const r=await fetch(url,{headers:{accept:'application/json,text/plain,*/*'}});
  const text=await r.text();
  let data; try{data=JSON.parse(text)}catch{data={raw:text.slice(0,2000)}};
  return {status:r.status,ok:r.ok,data,headers:Object.fromEntries(r.headers.entries())};
}

const spec=await get('https://cyzorcreations.com/openapi.json');
const watch=await get('https://cyzorcreations.com/api/v1/ext/watch?clientId=cyzor-probe-readonly');
const paths=spec.data?.paths||{};
const interesting=Object.entries(paths)
  .filter(([p,v])=>/(watch|sched|cron|monitor|job|worker|admin|task|queue|heartbeat|health)/i.test(p+' '+JSON.stringify(v)))
  .map(([path,ops])=>({
    path,
    methods:Object.entries(ops||{}).filter(([k])=>['get','post','put','patch','delete'].includes(k)).map(([method,op])=>({
      method,
      operationId:op?.operationId||null,
      summary:op?.summary||null
    }))
  }));

const out={
  checked_at:new Date().toISOString(),
  spec_status:spec.status,
  spec_title:spec.data?.info?.title||null,
  spec_version:spec.data?.info?.version||null,
  path_count:Object.keys(paths).length,
  interesting_routes:interesting.slice(0,100),
  watch_probe_status:watch.status,
  watch_probe_ok:watch.ok,
  watch_count:Array.isArray(watch.data?.watches)?watch.data.watches.length:null,
  server_hint:{
    server:spec.headers?.server||null,
    via:spec.headers?.via||null,
    powered_by:spec.headers?.['x-powered-by']||null
  }
};

await fs.writeFile('NOVAN_SCHEDULER_PROBE.json',JSON.stringify(out,null,2)+'\n');
await fs.writeFile('NOVAN_SCHEDULER_PROBE.txt',[
  'spec_status='+out.spec_status,
  'spec_title='+out.spec_title,
  'spec_version='+out.spec_version,
  'path_count='+out.path_count,
  'watch_probe_status='+out.watch_probe_status,
  'watch_count='+out.watch_count,
  ...out.interesting_routes.map(r=>r.path+' :: '+r.methods.map(m=>m.method+':'+(m.operationId||m.summary||'')).join(', '))
].join('\n')+'\n');
console.log(JSON.stringify(out,null,2));
