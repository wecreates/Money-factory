
import fs from 'node:fs/promises';

export async function loadBusinesses(file='businesses.json'){
  const raw=JSON.parse(await fs.readFile(file,'utf8'));
  const businesses=(raw.businesses||[]).filter(x=>x&&x.id);
  return {...raw,businesses};
}
export function selectBusinesses(config,{group='all',only=''}={}){
  let rows=config.businesses.filter(x=>x.enabled);
  if(group!=='all') rows=rows.filter(x=>x.schedule_group===group);
  if(only) rows=rows.filter(x=>x.id===only);
  return rows;
}
