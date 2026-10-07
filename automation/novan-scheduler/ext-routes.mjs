import fs from 'node:fs/promises';
const r=await fetch('https://cyzorcreations.com/openapi.json');
const spec=await r.json();
const rows=[];
for(const [path,ops] of Object.entries(spec.paths||{})){
  if(!path.startsWith('/api/v1/ext')) continue;
  const methods=[];
  for(const [method,op] of Object.entries(ops||{})){
    if(!['get','post','put','patch','delete'].includes(method)) continue;
    methods.push({
      method,
      operationId:op?.operationId||null,
      summary:op?.summary||null,
      description:op?.description||null,
      security:op?.security||null,
      requestBody:op?.requestBody||null,
      parameters:op?.parameters||null
    });
  }
  rows.push({path,methods});
}
const out={checked_at:new Date().toISOString(),count:rows.length,routes:rows};
await fs.writeFile('EXT_API_ROUTES.json',JSON.stringify(out,null,2)+'\n');
await fs.writeFile('EXT_API_ROUTES.txt',rows.map(r=>r.path+' :: '+r.methods.map(m=>m.method+':'+(m.operationId||m.summary||'')).join(', ')).join('\n')+'\n');
console.log(JSON.stringify(out,null,2));
