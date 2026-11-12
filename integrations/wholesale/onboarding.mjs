import {readFile,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {importCatalog,inventoryPlan,supplierBlockers,economics} from './engine.mjs';
import {accountCapacity} from './account-capacity.mjs';
const text=x=>typeof x==='string'&&x.trim().length>0;
const current=(x,now)=>Number.isSafeInteger(x)&&x>now;
const platforms=['amazon','walmart','ebay'];

// Validates declarations and actual mapped feed rows offline. No evidence, secret,
// credential reference or provider endpoint is fetched; completeness is not approval.
export function checkOnboarding(input){
 const blockers=[];const add=(code,path)=>blockers.push({code,path});
 const now=input.now;
 if(!Number.isSafeInteger(now)||now<0)throw Error('EXPLICIT_CLOCK_REQUIRED');
 function scan(value,path='input'){
  if(!value||typeof value!=='object')return;
  for(const [key,item] of Object.entries(value)){
   if(/^(access_token|refresh_token|client_secret|api_key|password|private_key)$/i.test(key))add('INLINE_SECRET_FORBIDDEN',path+'.'+key);
   else scan(item,path+'.'+key);
  }
 }
 scan(input);
 if(input.mode!=='sandbox'||input.live_enabled!==false)add('OFFLINE_MODE_REQUIRED','mode');
 if(input.fixture_data!==false)add('FIXTURE_DATA_NOT_PRODUCTION_EVIDENCE','fixture_data');
 let catalog=[];try{catalog=importCatalog(input.catalog);}catch{add('CATALOG_INVALID','catalog');}
 if(!catalog.length)add('CATALOG_REQUIRED','catalog');
 const channels=input.channels;
 if(!Array.isArray(channels)||!channels.length||new Set(channels).size!==channels.length||channels.some(c=>!platforms.includes(c)))add('CHANNELS_INVALID','channels');
 const records=name=>{if(!Array.isArray(input[name])){add('CONFIG_ARRAY_REQUIRED',name);return [];}return input[name].filter((r,i)=>{const valid=r&&typeof r==='object'&&!Array.isArray(r);if(!valid)add('CONFIG_RECORD_INVALID',`${name}.${i}`);return valid;});};
 const accounts=records('accounts'),suppliers=records('suppliers'),feeds=records('feeds'),origins=records('origins');
 const document=(value,path)=>{
  if(value?.classification!=='declared_document'||!text(value?.reference)||!current(value?.expires_at_ms,now)||!Number.isSafeInteger(value?.reviewed_at_ms)||value.reviewed_at_ms>now||value.reviewed_at_ms<0)add('CURRENT_DOCUMENT_DECLARATION_REQUIRED',path);
 };
 for(const channel of Array.isArray(channels)?channels.filter(c=>platforms.includes(c)):[]){
  const matches=accounts.filter(a=>a.marketplace===channel);
  if(matches.length!==1){add('UNIQUE_SELLER_ACCOUNT_REQUIRED',`accounts.${channel}`);continue;}
  const a=matches[0],path=`accounts.${channel}`;
  if(!text(a.account_id)||a.seller_status!=='approved')add('SELLER_APPROVAL_REQUIRED',path);
  if(!/^secret-ref:\/\/[A-Za-z0-9_/-]+$/.test(a.credential_ref??''))add('PRIVATE_CREDENTIAL_REFERENCE_REQUIRED',path+'.credential_ref');
  document(a.access_evidence,path+'.access_evidence');
  if(a.access_evidence?.account_id!==a.account_id||a.access_evidence?.marketplace!==channel)add('ACCESS_EVIDENCE_SCOPE_MISMATCH',path+'.access_evidence');
 }
 const mapped=[];
 for(const supplierId of new Set(catalog.map(r=>r.supplier_id))){
  const path=`suppliers.${supplierId}`,matches=suppliers.filter(s=>s.id===supplierId);
  if(matches.length!==1){add('UNIQUE_SUPPLIER_REQUIRED',path);continue;}
  const s=matches[0];document(s.authorization_document,path+'.authorization_document');
  if(s.authorization_document?.supplier_id!==supplierId)add('SUPPLIER_DOCUMENT_SCOPE_MISMATCH',path+'.authorization_document');
  // Missing/blank/non-string references must not join by equal invalid values.
  const origin=text(s.shipping_origin_id)?origins.filter(o=>text(o.id)&&o.id===s.shipping_origin_id):[];
  if(origin.length!==1)add('UNIQUE_SHIPPING_ORIGIN_REQUIRED',path+'.shipping_origin_id');
  else{
   const o=origin[0];let zone=true;try{new Intl.DateTimeFormat('en-US',{timeZone:o.timezone});}catch{zone=false;}
   if(!/^[A-Z]{2}$/.test(o.country??'')||!text(o.postal_code)||!text(o.timezone)||!zone||!Number.isSafeInteger(o.handling_days)||o.handling_days<0)add('SHIPPING_ORIGIN_INVALID',path+'.shipping_origin_id');
   if(!Array.isArray(s.authorized_origin_countries)||!s.authorized_origin_countries.includes(o.country))add('SHIPPING_ORIGIN_NOT_AUTHORIZED',path+'.authorized_origin_countries');
  }
  const found=feeds.filter(f=>f.supplier_id===supplierId);
  if(found.length!==1){add('UNIQUE_SUPPLIER_FEED_REQUIRED',`feeds.${supplierId}`);continue;}
  const f=found[0],fp=`feeds.${supplierId}`,keys=['sku','quantity','observed_at_ms','currency','unit','variant_id'];
  if(f.classification!=='supplier_export')add('FIXTURE_FEED_NOT_PRODUCTION_EVIDENCE',fp+'.classification');
  document(f.permission,fp+'.permission');
  if(f.permission?.supplier_id!==supplierId)add('FEED_PERMISSION_SCOPE_MISMATCH',fp+'.permission');
  if(f.snapshot_semantics!=='full'||f.quantity_semantics!=='total_before_local_reservations')add('FEED_RECONCILIATION_CONTRACT_REQUIRED',fp);
  if(!Number.isSafeInteger(f.max_age_ms)||f.max_age_ms<=0)add('FEED_FRESHNESS_LIMIT_REQUIRED',fp+'.max_age_ms');
  if(!keys.every(k=>text(f.field_map?.[k]))||new Set(keys.map(k=>f.field_map?.[k])).size!==keys.length||!Array.isArray(f.records)){add('FEED_FIELD_MAPPING_INVALID',fp+'.field_map');continue;}
  f.records.forEach((r,i)=>{
   if(!r||keys.some(k=>!Object.hasOwn(r,f.field_map[k]))){add('FEED_MAPPED_FIELD_MISSING',`${fp}.records.${i}`);return;}
   const product=catalog.find(p=>p.supplier_id===supplierId&&p.sku===r[f.field_map.sku]);
   // Compare the stock identity with the costed selling unit before normalization
   // discards provider columns. No implicit case conversion or variant fallback.
   if(product&&(['currency','unit','variant_id'].some(k=>r[f.field_map[k]]!==product[k])||product.unit!=='EACH'||!text(product.variant_id))){add('FEED_PRODUCT_IDENTITY_MISMATCH',`${fp}.records.${i}`);return;}
   mapped.push({supplier_id:supplierId,sku:r[f.field_map.sku],quantity:r[f.field_map.quantity],observed_at_ms:r[f.field_map.observed_at_ms],max_age_ms:f.max_age_ms});
  });
 }
 for(const row of catalog){
  const path=`catalog.${row.supplier_id}.${row.sku}`;
  if(row.unit!=='EACH'||!text(row.variant_id))add('CATALOG_SELLING_IDENTITY_REQUIRED',path);
  const quote=row.supplier_quote;
  // Unit-cost quotes may omit freight/tax. When supplied, those amounts must
  // agree with the catalog used by economics; never ignore contradictory costs.
  // Omission remains unverified, not a claim of complete landed-cost evidence.
  for(const field of ['shipping_cents','handling_cents','tax_cents']){
   if(quote&&Object.hasOwn(quote,field)&&quote[field]!==row[field])add('SUPPLIER_QUOTE_LANDED_CHARGE_MISMATCH',path+'.supplier_quote.'+field);
  }
  if(quote?.classification!=='declared_supplier_quote'||!text(quote?.reference)||['supplier_id','sku','currency','unit','variant_id','cost_cents'].some(k=>quote?.[k]!==row[k])||!Number.isSafeInteger(quote?.issued_at_ms)||quote.issued_at_ms<0||quote.issued_at_ms>now||!current(quote?.expires_at_ms,now)||quote.expires_at_ms!==row.quote_expires_at_ms)add('CURRENT_MATCHING_SUPPLIER_QUOTE_REQUIRED',path+'.supplier_quote');
  for(const channel of Array.isArray(channels)?channels.filter(c=>platforms.includes(c)):[]){
   for(const code of supplierBlockers(suppliers.find(s=>s.id===row.supplier_id),channel,row.sku,now))add(code,path+'.'+channel);
  }
  try{if(economics(row).projected_profit_cents<=0)add('NONPOSITIVE_ESTIMATED_CONTRIBUTION',path);}catch{add('ECONOMICS_INVALID',path);}
 }
 let inventory=[];
 try{inventory=inventoryPlan(catalog,mapped,[],now);for(const r of inventory){const path=`feeds.${r.supplier_id}.${r.sku}`;if(r.feed_status!=='current')add('CURRENT_INVENTORY_REQUIRED',path);if(!r.quote_current)add('CURRENT_COST_QUOTE_REQUIRED',path);}}
 catch{add('MAPPED_INVENTORY_INVALID','feeds');}
 const account_capacity=[];
 if(Array.isArray(channels)&&channels.includes('ebay')){
  const candidates=accounts.filter(a=>a.marketplace==='ebay');
  const result=accountCapacity(candidates.length===1?candidates[0]:null,input.listing_plans?.ebay,catalog,inventory,now);
  account_capacity.push({marketplace:'ebay',...result});
  for(const code of result.blockers)add(code,'accounts.ebay.selling_limits');
 }
 // Do not echo input, evidence references, account IDs, secret references or feed values.
 return {schema_version:1,mode:'sandbox',classification:'offline_onboarding_check',configuration_complete:blockers.length===0,status:blockers.length?'BLOCKED':'DECLARATIONS_COMPLETE_UNVERIFIED',blockers,
  external_prerequisites:['Independently verify seller approval and granted API access','Authenticate supplier/channel/SKU and origin/returns agreements','Validate actual supplier feed semantics and provider read-back in approved environment'],
  production_ready:false,provider_validated:false,publication_enabled:false,orders_placed:0,financial_transactions:0,
  checked_catalog_rows:catalog.length,checked_inventory_rows:inventory.length,account_capacity};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
 try{const [source,output]=process.argv.slice(2);if(!source||!output)throw Error('Usage: node onboarding.mjs config.json NEW-report.json');const result=checkOnboarding(JSON.parse(await readFile(source,'utf8')));await writeFile(output,JSON.stringify(result,null,2)+'\n',{flag:'wx'});console.log(result.status);}
 catch{console.error('Onboarding check failed; verify JSON input, clock and new output path.');process.exitCode=1;}
}
