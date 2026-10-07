
import fs from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';
import {PROFILE_ROOT,HEADLESS} from './config.mjs';

const contexts=new Map();
const locks=new Map();

async function withLock(key,fn){
  const previous=locks.get(key)||Promise.resolve();
  let release;
  const current=new Promise(r=>release=r);
  locks.set(key,previous.then(()=>current));
  await previous;
  try{return await fn();}
  finally{
    release();
    if(locks.get(key)===current) locks.delete(key);
  }
}

export async function getContext(business){
  const safe=String(business).replace(/[^A-Za-z0-9._-]/g,'_');
  if(contexts.has(safe)) return contexts.get(safe);
  const profile=path.join(PROFILE_ROOT,safe);
  await fs.mkdir(profile,{recursive:true});
  const ctx=await chromium.launchPersistentContext(profile,{
    headless:HEADLESS,
    args:['--no-sandbox','--disable-dev-shm-usage'],
    viewport:{width:1440,height:1000}
  });
  contexts.set(safe,ctx);
  return ctx;
}

export async function runForBusiness(business,fn){
  return withLock(business,async()=>{
    const ctx=await getContext(business);
    let page=ctx.pages()[0];
    if(!page) page=await ctx.newPage();
    return fn({context:ctx,page});
  });
}

export async function closeAll(){
  await Promise.allSettled([...contexts.values()].map(x=>x.close()));
  contexts.clear();
}
