
import fs from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';
import {validateTask} from './task.mjs';

const taskPath=process.argv[2];
if(!taskPath) throw new Error('Usage: node src/run.mjs <task.json>');
const task=validateTask(JSON.parse(await fs.readFile(taskPath,'utf8')));

const profile=process.env.ETSY_CHROME_PROFILE || path.resolve('.etsy-profile');
const browser=await chromium.launchPersistentContext(profile,{
  headless:false,
  channel:process.env.ETSY_CHROME_CHANNEL || 'chrome',
  viewport:{width:1440,height:1000}
});
const page=browser.pages()[0] || await browser.newPage();

async function ensureLogin(){
  await page.goto('https://www.etsy.com/your/shops/me/tools/listings',{waitUntil:'domcontentloaded'});
  if(/signin|login/i.test(page.url())){
    console.log('LOGIN_REQUIRED: Sign in to Etsy in the opened Chrome window, complete any 2FA/CAPTCHA, then rerun the task.');
    process.exitCode=10;
    return false;
  }
  return true;
}
async function fillByLabel(labels,value){
  for(const label of labels){
    const loc=page.getByLabel(label,{exact:false}).first();
    if(await loc.count()){
      try{ await loc.fill(String(value)); return true; }catch{}
    }
  }
  return false;
}
async function clickText(texts){
  for(const t of texts){
    const loc=page.getByText(t,{exact:false}).first();
    if(await loc.count()){
      try{ await loc.click(); return true; }catch{}
    }
  }
  return false;
}

let result={id:task.id,type:task.type,success:false};
try{
  if(task.type==='verify_public'){
    await page.goto(task.url,{waitUntil:'domcontentloaded'});
    result={...result,success:true,url:page.url(),title:await page.title(),text:(await page.locator('body').innerText()).slice(0,12000)};
  } else {
    if(!(await ensureLogin())) throw new Error('login required');

    if(task.type==='update_listing'){
      await page.goto(`https://www.etsy.com/your/shops/me/listing-editor/edit/${task.listing_id}`,{waitUntil:'domcontentloaded'});
      const p=task.patch;
      if(p.title) await fillByLabel(['Title'],p.title);
      if(p.description) await fillByLabel(['Description'],p.description);
      if(p.price!=null) await fillByLabel(['Price'],p.price);

      if(p.type==='download'){
        await clickText(['Digital files','Digital']);
      }

      if(Array.isArray(p.tags)){
        const tagInput=page.getByLabel(/tag/i).first();
        if(await tagInput.count()){
          const existing=page.locator('[data-tag], .wt-tag, [class*="tag"] button');
          const n=await existing.count();
          for(let i=n-1;i>=0;i--){ try{await existing.nth(i).click();}catch{} }
          for(const tag of p.tags){ try{await tagInput.fill(tag);await tagInput.press('Enter');}catch{} }
        }
      }

      // Optional uploads: local paths supplied in patch.images / patch.files.
      if(Array.isArray(p.images) && p.images.length){
        const imgs=page.locator('input[type=file]').first();
        if(await imgs.count()) await imgs.setInputFiles(p.images);
      }
      if(Array.isArray(p.files) && p.files.length){
        const inputs=page.locator('input[type=file]');
        const c=await inputs.count();
        if(c>1) await inputs.nth(c-1).setInputFiles(p.files);
      }

      await clickText(['Save changes','Publish changes','Save']);
      await page.waitForTimeout(1200);
      result={...result,success:true,listing_id:task.listing_id,url:page.url()};
    }

    if(task.type==='update_shop'){
      await page.goto('https://www.etsy.com/your/shops/me/appearance',{waitUntil:'domcontentloaded'});
      if(task.patch.title) await fillByLabel(['Shop title','Title'],task.patch.title);
      if(task.patch.announcement) await fillByLabel(['Announcement'],task.patch.announcement);
      await clickText(['Save changes','Save']);
      result={...result,success:true,url:page.url()};
    }

    if(task.type==='create_section'){
      await page.goto('https://www.etsy.com/your/shops/me/tools/listings',{waitUntil:'domcontentloaded'});
      await clickText(['Manage sections','Sections']);
      await clickText(['Add section','New section']);
      await fillByLabel(['Section name','Name'],task.title);
      await clickText(['Save','Create']);
      result={...result,success:true,title:task.title};
    }
  }
}catch(e){
  result.error=String(e?.stack||e);
}
console.log(JSON.stringify(result,null,2));
await browser.close();
if(!result.success && process.exitCode!==10) process.exitCode=1;
