
import fs from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';
import {validateTask} from './task.mjs';
import {validateShopPatch,validateSectionTitle,updateShop,createSection} from './shop-actions.mjs';
import {validateListingUploads,uploadAndSaveListing} from './listing-actions.mjs';
import {validateListingPatch,applyListingMetadata,verifyListingMetadata} from './listing-metadata.mjs';

const taskPath=process.argv[2];
if(!taskPath) throw new Error('Usage: node src/run.mjs <task.json>');
const task=validateTask(JSON.parse(await fs.readFile(taskPath,'utf8')));
// Validate the whole requested batch before launching Chrome or editing a listing.
if(task.type==='update_listing')validateListingPatch(task.patch);
if(task.type==='update_shop')validateShopPatch(task.patch);
if(task.type==='create_section')validateSectionTitle(task.title);
const uploads=await validateListingUploads(task);

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
      await applyListingMetadata(page,p);
      const evidence=await uploadAndSaveListing(page,uploads,{
        verifyMetadata:()=>verifyListingMetadata(page,p),
      });
      result={...result,success:true,verification:'EDITOR_READBACK_CONFIRMED',evidence,listing_id:task.listing_id,url:page.url()};
    }

    if(task.type==='update_shop'){
      await page.goto('https://www.etsy.com/your/shops/me/appearance',{waitUntil:'domcontentloaded'});
      const evidence=await updateShop(page,task.patch);
      result={...result,success:true,verification:'SHOP_READBACK_CONFIRMED',evidence,url:page.url()};
    }

    if(task.type==='create_section'){
      await page.goto('https://www.etsy.com/your/shops/me/tools/listings',{waitUntil:'domcontentloaded'});
      const evidence=await createSection(page,task.title);
      result={...result,success:true,verification:'SECTION_READBACK_CONFIRMED',evidence,title:task.title};
    }
  }
}catch(e){
  result.error=String(e?.stack||e);
}
console.log(JSON.stringify(result,null,2));
await browser.close();
if(!result.success && process.exitCode!==10) process.exitCode=1;


