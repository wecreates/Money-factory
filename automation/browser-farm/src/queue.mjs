
import fs from 'node:fs/promises';
import path from 'node:path';
import {QUEUE_ROOT} from './config.mjs';

const pending=path.join(QUEUE_ROOT,'pending');
const running=path.join(QUEUE_ROOT,'running');
const done=path.join(QUEUE_ROOT,'done');
const failed=path.join(QUEUE_ROOT,'failed');

export async function ensureQueue(){
  for(const p of [pending,running,done,failed]) await fs.mkdir(p,{recursive:true});
}
export async function enqueue(task){
  await ensureQueue();
  const id=String(task.id||Date.now());
  const safe=id.replace(/[^A-Za-z0-9._-]/g,'_');
  const file=path.join(pending,safe+'.json');
  await fs.writeFile(file,JSON.stringify({...task,id:safe,created_at:new Date().toISOString()},null,2));
  return safe;
}
export async function claim(){
  await ensureQueue();
  const files=(await fs.readdir(pending)).filter(x=>x.endsWith('.json')).sort();
  if(!files.length) return null;
  for(const f of files){
    const from=path.join(pending,f), to=path.join(running,f);
    try{
      await fs.rename(from,to);
      return {file:to,task:JSON.parse(await fs.readFile(to,'utf8'))};
    }catch{}
  }
  return null;
}
export async function finish(file,result,ok=true){
  const base=path.basename(file);
  const target=path.join(ok?done:failed,base);
  await fs.writeFile(file,JSON.stringify(result,null,2));
  await fs.rename(file,target);
}
export async function counts(){
  await ensureQueue();
  const out={};
  for(const [k,p] of Object.entries({pending,running,done,failed})) out[k]=(await fs.readdir(p)).filter(x=>x.endsWith('.json')).length;
  return out;
}
