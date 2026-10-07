
import fs from 'node:fs/promises';
import path from 'node:path';
import {enqueue} from './queue.mjs';

const token=process.env.GITHUB_TOKEN;
const repo=process.env.GITHUB_REPOSITORY||'wecreates/Money-factory';
const branch=process.env.GITHUB_BRANCH||'main';
const queuePath=process.env.GITHUB_QUEUE_PATH||'automation/browser-farm/cloud-queue';
const pollMs=Math.max(5000,Number(process.env.GITHUB_POLL_MS||15000));

if(!token) throw new Error('GITHUB_TOKEN is required');

const headers={
  authorization:`Bearer ${token}`,
  accept:'application/vnd.github+json',
  'x-github-api-version':'2022-11-28'
};

async function api(url,opts={}){
  const r=await fetch(url,{...opts,headers:{...headers,...(opts.headers||{})}});
  if(!r.ok) throw new Error(`GitHub ${r.status}: ${await r.text()}`);
  return r.status===204?null:r.json();
}
async function listQueue(){
  const url=`https://api.github.com/repos/${repo}/contents/${queuePath}?ref=${encodeURIComponent(branch)}`;
  try{
    const v=await api(url);
    return Array.isArray(v)?v.filter(x=>x.type==='file'&&x.name.endsWith('.json')):[];
  }catch(e){
    if(String(e).includes('GitHub 404')) return [];
    throw e;
  }
}
async function fetchTask(item){
  const r=await fetch(item.download_url);
  if(!r.ok) throw new Error('Cannot fetch queued task '+item.name);
  return r.json();
}
async function deleteQueueItem(item,message){
  await api(`https://api.github.com/repos/${repo}/contents/${item.path}`,{
    method:'DELETE',
    headers:{'content-type':'application/json'},
    body:JSON.stringify({message,sha:item.sha,branch})
  });
}

console.log('GitHub queue poller started for',repo,queuePath);
for(;;){
  try{
    const items=await listQueue();
    for(const item of items){
      try{
        const task=await fetchTask(item);
        const id=await enqueue(task);
        await deleteQueueItem(item,`Claim browser-farm task ${id}`);
        console.log('claimed',item.name,'as',id);
      }catch(e){
        console.error('queue item failed',item.name,e);
      }
    }
  }catch(e){
    console.error('poll error',e);
  }
  await new Promise(r=>setTimeout(r,pollMs));
}
