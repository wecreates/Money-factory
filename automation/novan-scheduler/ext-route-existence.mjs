import fs from 'node:fs/promises';
const base='https://cyzorcreations.com/api/v1/ext';
const candidates=[
  '/check','/tick','/run','/poll','/health','/cron','/worker',
  '/watch/check','/watch/tick','/watch/run','/watch/poll','/watch/check-now','/watch/check_now',
  '/watcher/check','/monitor/check','/monitor/tick','/monitor/run'
];
const out={checked_at:new Date().toISOString(),results:[]};
for(const p of candidates){
  for(const method of ['GET','OPTIONS']){
    try{
      const r=await fetch(base+p,{method,redirect:'manual'});
      const text=await r.text();
      out.results.push({path:p,method,status:r.status,allow:r.headers.get('allow'),body:text.slice(0,300)});
    }catch(e){
      out.results.push({path:p,method,error:String(e)});
    }
  }
}
await fs.writeFile('EXT_ROUTE_EXISTENCE_PROBE.json',JSON.stringify(out,null,2)+'\n');
console.log(JSON.stringify(out,null,2));
