// Local review artifact only. No eBay requests, endpoints or publishing operations.
import {readFile,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {checkOnboarding} from './onboarding.mjs';
import {economics} from './engine.mjs';
const text=x=>typeof x==='string'&&x.trim().length>0;
export function buildListingDrafts(input){
 const onboarding=checkOnboarding(input),blockers=[...onboarding.blockers];
 const add=(code,path)=>blockers.push({code,path});
 if(input.channels?.length!==1||input.channels[0]!=='ebay')add('EBAY_ONLY_DRAFT_SCOPE','channels');
 const plan=input.listing_plans?.ebay??[],details=input.listing_details;
 if(!Array.isArray(details)||details.length!==plan.length)add('EXACT_DRAFT_DETAILS_REQUIRED','listing_details');
 const drafts=[],sellerSkus=new Set();
 // Do not dereference rejected prerequisites while constructing a blocked report.
 for(const [index,item] of onboarding.configuration_complete&&Array.isArray(plan)?plan.entries():[]){
  const path=`listing_details.${index}`,before=blockers.length;
  const matches=(Array.isArray(details)?details:[]).filter(d=>d?.supplier_id===item.supplier_id&&d?.sku===item.sku);
  if(matches.length!==1){add('UNIQUE_DRAFT_DETAILS_REQUIRED',path);continue;}
  const d=matches[0],row=input.catalog.find(r=>r.supplier_id===item.supplier_id&&r.sku===item.sku);
  if(!row){add('CATALOG_PRODUCT_REQUIRED',path);continue;}
  const supplier=input.suppliers.find(s=>s.id===row.supplier_id),origin=input.origins.find(o=>o.id===supplier?.shipping_origin_id);
  if(!text(d.seller_sku)||sellerSkus.has(d.seller_sku))add('UNIQUE_SELLER_SKU_REQUIRED',path);sellerSkus.add(d.seller_sku);
  if(d.variant_id!==row.variant_id||d.unit!==row.unit||d.currency!==row.currency)add('DRAFT_IDENTITY_MISMATCH',path);
  if(d.origin_id!==origin?.id||!origin)add('DRAFT_ORIGIN_MISMATCH',path);
  if(d.marketplace_id!=='EBAY_US'||d.format!=='FIXED_PRICE'||d.condition!=='NEW'||d.group_id!==undefined)add('UNSUPPORTED_DRAFT_SCOPE',path);
  if(!text(d.title)||d.title.length>80||!text(d.description)||typeof d.category_id!=='string'||!/^\d+$/.test(d.category_id))add('PRODUCT_DETAILS_REQUIRED',path);
  if(!Array.isArray(d.image_urls)||!d.image_urls.length||d.image_urls.some(u=>{if(typeof u!=='string')return true;try{const v=new URL(u);return v.protocol!=='https:'||!!v.username||!!v.password;}catch{return true;}}))add('HTTPS_IMAGES_REQUIRED',path);
  if(!d.aspects||typeof d.aspects!=='object'||Array.isArray(d.aspects)||Object.values(d.aspects).some(v=>!Array.isArray(v)||!v.length||v.some(x=>!text(x))))add('PRODUCT_ASPECTS_REQUIRED',path);
  for(const k of ['fulfillment_policy_id','return_policy_id','payment_policy_id','merchant_location_key'])if(!text(d[k]))add('SELLER_POLICY_OR_LOCATION_REQUIRED',path+'.'+k);
  // Evidence declarations must bind this exact SKU/account/category and location.
  // They are never authenticated by this offline builder.
  for(const k of ['category_evidence','content_rights_evidence','shipping_returns_evidence','fee_evidence']){
   const e=d[k];
   if(e?.classification!=='declared_document'||!text(e.reference)||!Number.isSafeInteger(e.reviewed_at_ms)||e.reviewed_at_ms>input.now||e.reviewed_at_ms<0||!Number.isSafeInteger(e.expires_at_ms)||e.expires_at_ms<=input.now||e.supplier_id!==row.supplier_id||e.sku!==row.sku||e.account_id!==input.accounts?.[0]?.account_id||e.category_id!==d.category_id||e.origin_id!==d.origin_id)add('SCOPED_DRAFT_EVIDENCE_REQUIRED',path+'.'+k);
  }
  if(!Number.isSafeInteger(d.shipping?.handling_days)||d.shipping.handling_days<origin?.handling_days||!text(d.shipping?.service)||!Array.isArray(d.shipping?.destination_countries)||!d.shipping.destination_countries.length||d.shipping.destination_countries.some(c=>c!=='US')||d.shipping?.cost_cents!==row.shipping_cents)add('SHIPPING_TERMS_REQUIRED',path);
  if(!Number.isSafeInteger(d.returns?.window_days)||d.returns.window_days<=0||!['SELLER','BUYER'].includes(d.returns?.shipping_payer)||row.return_reserve_bps<=0||row.fee_bps<=0)add('FEE_AND_RETURN_BUFFER_REQUIRED',path);
  if(blockers.length===before&&onboarding.configuration_complete){
   drafts.push({supplier_id:row.supplier_id,sku:row.sku,seller_sku:d.seller_sku,variant_id:row.variant_id,unit:row.unit,quantity:item.additional_quantity,currency:row.currency,price_cents:row.price_cents,
    title:d.title,description:d.description,category_id:d.category_id,condition:d.condition,aspects:d.aspects,image_urls:d.image_urls,
    origin:{country:origin.country,postal_code:origin.postal_code,timezone:origin.timezone},shipping:d.shipping,returns:d.returns,
    seller_policy_references:{fulfillment:d.fulfillment_policy_id,returns:d.return_policy_id,payment:d.payment_policy_id,location:d.merchant_location_key},economics:economics(row)});
  }
 }
 return {mode:'sandbox',classification:'local_listing_review_only',status:blockers.length?'BLOCKED':'DRAFTS_FOR_REVIEW_UNVERIFIED',blockers,drafts:blockers.length?[]:structuredClone(drafts),
  production_ready:false,provider_validated:false,publication_enabled:false,dispatch_enabled:false,orders_placed:0,financial_transactions:0,
  external_prerequisites:onboarding.external_prerequisites.concat(['Verify current category aspects/identifiers/condition and policy/location ownership against eBay','Reconcile existing offers, pending allocations and stock before any separately approved publication'])};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
 try{const [source,output]=process.argv.slice(2);if(!source||!output)throw Error('ARGS');const r=buildListingDrafts(JSON.parse(await readFile(source,'utf8')));await writeFile(output,JSON.stringify(r,null,2)+'\n',{flag:'wx'});console.log(r.status);}
 catch{console.error('Draft build failed; check input and new output path.');process.exitCode=1;}
}
