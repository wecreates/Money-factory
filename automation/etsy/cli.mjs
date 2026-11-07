import fs from 'node:fs/promises';
import path from 'node:path';
import config from './config.json' with {type:'json'};
import {refreshAccessToken,apiKey,getListing,updateListing,updateShop,createSection,uploadListingFile,listListingFiles} from './api.mjs';
import {patchFromRebuild,SUPPLEMENTAL_FILES} from './patches.mjs';
import {planListingFiles,uploadFilePlan,summarizeFilePlan} from './file-plan.mjs';

const [action='diff',target='all']=process.argv.slice(2);
const shopId=Number(process.env.ETSY_SHOP_ID||config.shop_id);
const rebuild=JSON.parse(await fs.readFile(path.resolve(import.meta.dirname,config.full_rebuild_file),'utf8'));
const patches={flagship:(rebuild.replacements||[]).map(patchFromRebuild)};

function chosen(){
  const all=patches.flagship||[];
  if(target==='all') return all;
  return all.filter(x=>String(x.listing_id)===target || x.product.toLowerCase()===target.toLowerCase());
}

const allowedActions=['diff','apply','files','plan-files','shop','sections'];
if(!allowedActions.includes(action)) throw new Error('Usage: node cli.mjs <diff|apply|files|plan-files|shop|sections> <all|listing id|product>');
let filePlan;
if(['files','plan-files'].includes(action)){
  if(target==='all') throw new Error('File planning/upload requires one exact listing target');
  const selected=chosen();
  if(selected.length!==1) throw new Error('File planning/upload must match exactly one known listing');
  const root=process.env.ETSY_PRODUCT_ROOT;
  const manifestPath=process.env.ETSY_FILE_MANIFEST;
  if(!root) throw new Error('Missing ETSY_PRODUCT_ROOT');
  if(!manifestPath) throw new Error('Missing ETSY_FILE_MANIFEST');
  const manifest=JSON.parse(await fs.readFile(manifestPath,'utf8'));
  filePlan=await planListingFiles({root,manifest,listingId:selected[0].listing_id,shopId,requiredFilenames:['product.pdf',SUPPLEMENTAL_FILES[selected[0].listing_id]].filter(Boolean)});
}

if(action==='plan-files'){
  console.log(JSON.stringify({action,...summarizeFilePlan(filePlan)},null,2));
} else {
  const token=await refreshAccessToken();
  const apiKeyValue=apiKey();
  if(action==='shop'){
    const result=await updateShop({shopId,patch:config.desired_shop,token,apiKeyValue});
    console.log(JSON.stringify({action,result},null,2));
  } else if(action==='sections'){
    const out=[];
    for(const title of config.sections) out.push(await createSection({shopId,title,token,apiKeyValue}));
    console.log(JSON.stringify({action,sections:out},null,2));
  } else if(['diff','apply'].includes(action)){
    const out=[];
    for(const p of chosen()){
      const current=await getListing({listingId:p.listing_id,token,apiKeyValue});
      const desired={
        type:'download',
        title:p.title,
        description:p.description,
        tags:p.tags,
        price:String(p.price)
      };
      const before={type:current.type,title:current.title,description:current.description,tags:current.tags,price:current.price};
      if(action==='diff'){
        out.push({id:p.listing_id,product:p.product,before,desired});
      } else {
        const result=await updateListing({shopId,listingId:p.listing_id,patch:desired,token,apiKeyValue});
        out.push({id:p.listing_id,product:p.product,result});
      }
    }
    console.log(JSON.stringify({action,target,count:out.length,items:out},null,2));
  } else if(action==='files'){
    const listing=await getListing({listingId:filePlan.listing_id,token,apiKeyValue});
    const existingFiles=await listListingFiles({shopId,listingId:filePlan.listing_id,token,apiKeyValue});
    const result=await uploadFilePlan({
      plan:filePlan,listing,existingFiles,
      upload:file=>uploadListingFile({shopId,listingId:filePlan.listing_id,filename:file.filename,bytes:file.bytes,rank:file.rank,token,apiKeyValue}),
      verify:()=>listListingFiles({shopId,listingId:filePlan.listing_id,token,apiKeyValue})
    });
    console.log(JSON.stringify({action,...summarizeFilePlan(filePlan),...result},null,2));
  }
}
