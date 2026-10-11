
import fs from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';
import {sessionForBusiness} from './session.mjs';

const business=process.env.BUSINESS_ID;
const taskFile=process.env.TASK_FILE;
if(!business||!taskFile) throw new Error('BUSINESS_ID and TASK_FILE required');

const task=JSON.parse(await fs.readFile(taskFile,'utf8'));
const artifactDir=path.resolve('artifacts',business);
await fs.mkdir(artifactDir,{recursive:true});

// Keep credentials in memory only, never in the uploaded artifact directory.
const storageState=sessionForBusiness(process.env.BROWSER_SESSIONS_JSON,business);

const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
const context=await browser.newContext(storageState?{storageState}:{viewport:{width:1440,height:1000}});
const page=await context.newPage();

async function runStep(step){
  const out={action:step.action,ok:false};
  try{
    if(step.action==='goto'){
      await page.goto(step.url,{waitUntil:'domcontentloaded',timeout:60000});
      out.url=page.url();out.title=await page.title();
    }else if(step.action==='inspect'){
      await page.goto(step.url,{waitUntil:'domcontentloaded',timeout:60000});
      out.url=page.url();out.title=await page.title();
      out.text=(await page.locator('body').innerText()).slice(0,20000);
    }else if(step.action==='screenshot'){
      if(step.url) await page.goto(step.url,{waitUntil:'domcontentloaded',timeout:60000});
      const p=path.join(artifactDir,step.filename||'page.png');
      await page.screenshot({path:p,fullPage:true});
      out.file=p;
    }else if(step.action==='click_text'){
      if(step.url) await page.goto(step.url,{waitUntil:'domcontentloaded',timeout:60000});
      await page.getByText(step.text,{exact:false}).first().click();
      out.url=page.url();
    }else if(step.action==='fill_label'){
      if(step.url) await page.goto(step.url,{waitUntil:'domcontentloaded',timeout:60000});
      await page.getByLabel(step.label,{exact:false}).first().fill(String(step.value??''));
      out.url=page.url();
    }else if(step.action==='wait'){
      await page.waitForTimeout(Number(step.ms||1000));
    }else{
      throw new Error('Unsupported action '+step.action);
    }
    out.ok=true;
  }catch(e){
    out.error=String(e?.message||e);
  }
  return out;
}

const results=[];
for(const step of (task.steps||[])) results.push(await runStep(step));

const summary={
  business,
  ok:results.every(x=>x.ok),
  started_at:new Date().toISOString(),
  results
};
await fs.writeFile(path.join(artifactDir,'result.json'),JSON.stringify(summary,null,2));
console.log(JSON.stringify(summary,null,2));
await browser.close();
if(!summary.ok) process.exitCode=2;
