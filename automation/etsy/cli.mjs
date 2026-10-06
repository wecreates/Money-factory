import fs from 'node:fs/promises';
import path from 'node:path';
import config from './config.json' with {type:'json'};
import {refreshAccessToken,apiKey,getListing,updateListing,updateShop,createSection} from './api.mjs';

const [action='diff',target='all']=process.argv.slice(2);
const shopId=Number(process.env.ETSY_SHOP_ID||config.shop_id);
const patches=JSON.parse(await fs.readFile(path.resolve(import.meta.dirname,config.flagship_patch_file),'utf8'));
const token=await refreshAccessToken();
const apiKeyValue=apiKey();

function chosen(){
  const all=patches.flagship||[];
  if(target==='all') return all;
  return all.filter(x=>String(x.id)===target || x.product.toLowerCase()===target.toLowerCase());
}

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
    const current=await getListing({listingId:p.id,token,apiKeyValue});
    const desired={
      title:p.title,
      description:[p.description_open,'','WHAT YOU GET','See listing images for the complete page set and current file details.','','DIGITAL DELIVERY','Digital items download after payment. Physical items are shipped only where the listing is marked physical.','','SUPPORT','Questions about the file or order? Message CyzorCreations through Etsy.'].join('\n'),
      tags:p.tags
    };
    const before={title:current.title,description:current.description,tags:current.tags,price:current.price};
    if(action==='diff'){
      out.push({id:p.id,product:p.product,before,desired});
    } else {
      const result=await updateListing({shopId,listingId:p.id,patch:desired,token,apiKeyValue});
      out.push({id:p.id,product:p.product,result});
    }
  }
  console.log(JSON.stringify({action,target,count:out.length,items:out},null,2));
} else {
  throw new Error('Usage: node cli.mjs <diff|apply|shop|sections> <all|listing id|product>');
}
