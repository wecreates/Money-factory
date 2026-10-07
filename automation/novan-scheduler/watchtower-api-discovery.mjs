import fs from 'node:fs/promises';
const base='https://cyzorcreations.com';
const html=await (await fetch(base+'/watchtower')).text();
const srcs=[...html.matchAll(/<script[^>]+src=["']([^"']+)["']/gi)].map(m=>new URL(m[1],base).toString());
const hrefs=[...html.matchAll(/<link[^>]+href=["']([^"']+)["']/gi)].map(m=>new URL(m[1],base).toString());
const urls=[...new Set([...srcs,...hrefs])].filter(u=>u.startsWith(base));
const findings=[];
const rx=/\/api\/v1\/ext\/[A-Za-z0-9_?=&%{}$.:/\-]*/g;
const scan=(name,text)=>{
  const hits=[...new Set(text.match(rx)||[])];
  if(hits.length) findings.push({source:name,hits});
};
scan('/watchtower',html);
for(const u of urls.slice(0,80)){
  try{
    const r=await fetch(u);
    const ct=r.headers.get('content-type')||'';
    if(!/javascript|text|css|json/.test(ct)) continue;
    const t=await r.text();
    scan(u,t);
  }catch{}
}
const out={checked_at:new Date().toISOString(),asset_count:urls.length,findings};
await fs.writeFile('WATCHTOWER_API_DISCOVERY.json',JSON.stringify(out,null,2)+'\n');
await fs.writeFile('WATCHTOWER_API_DISCOVERY.txt',findings.flatMap(f=>f.hits.map(h=>f.source+' :: '+h)).join('\n')+'\n');
console.log(JSON.stringify(out,null,2));
