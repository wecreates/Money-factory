import fs from 'node:fs/promises';
import path from 'node:path';
import config from './config.json' with {type:'json'};
import {refreshAccessToken,apiKey,getListing,updateListing,updateShop,createSection,uploadListingFile,listListingFiles} from './api.mjs';
import {patchFromRebuild,SUPPLEMENTAL_FILES} from './patches.mjs';

const [action='diff',target='all']=process.argv.slice(2);
const shopId=Number(process.env.ETSY_SHOP_ID||config.shop_id);
const rebuild=JSON.parse(await fs.readFile(path.resolve(import.meta.dirname,config.full_rebuild_file),'utf8'));
const patches={flagship:(rebuild.replacements||[]).map(patchFromRebuild)};
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
      type:'download',
      title:p.title,
      description:p.description,
      tags:p.tags,
      price:String(p.price)
    };
    const before={type:current.type,title:current.title,description:current.description,tags:current.tags,price:current.price};
    if(action==='diff'){
      out.push({id:p.id,product:p.product,before,desired});
    } else {
      const result=await updateListing({shopId,listingId:p.id,patch:desired,token,apiKeyValue});
      out.push({id:p.id,product:p.product,result});
    }
  }
  console.log(JSON.stringify({action,target,count:out.length,items:out},null,2));
} else if(action==='files'){
  const root=process.env.ETSY_PRODUCT_ROOT;
  if(!root) throw new Error('Missing ETSY_PRODUCT_ROOT');
  const out=[];
  const walk=async dir=>{
    const entries=await fs.readdir(dir,{withFileTypes:true});
    const found=[];
    for(const e of entries){
      const p=path.join(dir,e.name);
      if(e.isDirectory()) found.push(...await walk(p)); else found.push(p);
    }
    return found;
  };
  const allFiles=await walk(root);
  for(const p of chosen()){
    const prefix=String(p.listing_id);
    const productPdf=allFiles.find(f=>path.basename(f)==='product.pdf' && f.includes(prefix));
    if(!productPdf) throw new Error(`Missing product.pdf for listing ${prefix}`);
    const uploads=[productPdf];
    const supplement=SUPPLEMENTAL_FILES[prefix];
    if(supplement){
      const match=allFiles.find(f=>path.basename(f)===supplement);
      if(match) uploads.push(match);
    }
    const uploaded=[];
    let rank=1;
    for(const file of uploads){
      const bytes=new Uint8Array(await fs.readFile(file));
      uploaded.push(await uploadListingFile({
        shopId,listingId:prefix,filename:path.basename(file),bytes,rank,
        token,apiKeyValue
      }));
      rank++;
    }
    const verify=await listListingFiles({shopId,listingId:prefix,token,apiKeyValue});
    out.push({listing_id:prefix,uploaded:uploaded.map(x=>x.filename||x.listing_file_id),verify});
  }
  console.log(JSON.stringify({action,target,count:out.length,items:out},null,2));
} else {
  throw new Error('Usage: node cli.mjs <diff|apply|files|shop|sections> <all|listing id|product>');
}
