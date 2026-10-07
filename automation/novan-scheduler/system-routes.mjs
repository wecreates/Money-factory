import fs from 'node:fs/promises';
const r=await fetch('https://cyzorcreations.com/openapi.json');
const spec=await r.json();
const paths=spec.paths||{};
const rx=/(shell|ssh|deploy|server|system|process|service|file|repo|git|cron|sched|worker|daemon|exec|command|host|infra|ops|admin)/i;
const rows=[];
for(const [path,ops] of Object.entries(paths)){
  const blob=path+' '+JSON.stringify(ops);
  if(!rx.test(blob)) continue;
  const methods=[];
  for(const [method,op] of Object.entries(ops||{})){
    if(!['get','post','put','patch','delete'].includes(method)) continue;
    methods.push({method,operationId:op?.operationId||null,summary:op?.summary||null});
  }
  rows.push({path,methods});
}
const out={checked_at:new Date().toISOString(),count:rows.length,routes:rows.slice(0,300)};
await fs.writeFile('NOVAN_SYSTEM_ROUTES.json',JSON.stringify(out,null,2)+'\n');
await fs.writeFile('NOVAN_SYSTEM_ROUTES.txt',rows.slice(0,300).map(r=>r.path+' :: '+r.methods.map(m=>m.method+':'+(m.operationId||m.summary||'')).join(', ')).join('\n')+'\n');
console.log(out.count);
