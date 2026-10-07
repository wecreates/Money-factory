
import fs from 'node:fs/promises';
import path from 'node:path';
import {ARTIFACT_ROOT} from './config.mjs';

async function artifactDir(task){
  const d=path.join(ARTIFACT_ROOT,String(task.business),String(task.id));
  await fs.mkdir(d,{recursive:true});
  return d;
}

export async function handleTask(task,{page}){
  const out={id:task.id,business:task.business,type:task.type,started_at:new Date().toISOString()};
  const dir=await artifactDir(task);

  if(task.type==='goto'){
    await page.goto(task.url,{waitUntil:'domcontentloaded',timeout:60000});
    out.url=page.url();
    out.title=await page.title();
  }else if(task.type==='inspect'){
    await page.goto(task.url,{waitUntil:'domcontentloaded',timeout:60000});
    out.url=page.url();
    out.title=await page.title();
    out.text=(await page.locator('body').innerText()).slice(0,20000);
  }else if(task.type==='screenshot'){
    if(task.url) await page.goto(task.url,{waitUntil:'domcontentloaded',timeout:60000});
    const p=path.join(dir,'page.png');
    await page.screenshot({path:p,fullPage:true});
    out.url=page.url();
    out.screenshot=p;
  }else if(task.type==='etsy_update_listing'){
    await page.goto(`https://www.etsy.com/your/shops/me/listing-editor/edit/${task.listing_id}`,{waitUntil:'domcontentloaded',timeout:60000});
    if(/signin|login/i.test(page.url())) {
      return {...out,ok:false,login_required:true,url:page.url()};
    }
    const p=task.patch||{};
    const fill=async(labels,value)=>{
      if(value==null) return false;
      for(const label of labels){
        const loc=page.getByLabel(label,{exact:false}).first();
        if(await loc.count()){
          try{await loc.fill(String(value));return true}catch{}
        }
      }
      return false;
    };
    const clickText=async(texts)=>{
      for(const text of texts){
        const loc=page.getByText(text,{exact:false}).first();
        if(await loc.count()){
          try{await loc.click();return true}catch{}
        }
      }
      return false;
    };
    await fill(['Title'],p.title);
    await fill(['Description'],p.description);
    await fill(['Price'],p.price);
    if(p.type==='download') await clickText(['Digital files','Digital item','Digital']);

    if(Array.isArray(p.tags)){
      const input=page.getByLabel(/tag/i).first();
      if(await input.count()){
        const remove=page.locator('button[aria-label*="Remove"],button[title*="Remove"]');
        for(let i=(await remove.count())-1;i>=0;i--) await remove.nth(i).click().catch(()=>{});
        for(const tag of p.tags){await input.fill(tag);await input.press('Enter');}
      }
    }
    if(Array.isArray(p.images)&&p.images.length){
      const inputs=page.locator('input[type=file]');
      if(await inputs.count()) await inputs.first().setInputFiles(p.images);
    }
    if(Array.isArray(p.files)&&p.files.length){
      const inputs=page.locator('input[type=file]');
      const n=await inputs.count();
      if(n) await inputs.nth(n-1).setInputFiles(p.files);
    }
    if(task.commit===true) await clickText(['Save changes','Publish changes','Save']);
    out.url=page.url();
    out.committed=task.commit===true;
  }else{
    throw new Error('Unsupported task type: '+task.type);
  }

  out.finished_at=new Date().toISOString();
  if(out.ok!==false) out.ok=true;
  return out;
}
