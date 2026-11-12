// Deterministic supplied-contract validation; no network and no API-ready claim.
import {buildListingDrafts} from './listing-draft.mjs';
import {readFile,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const text=x=>typeof x==='string'&&x.trim().length>0;
const int=x=>Number.isSafeInteger(x)&&x>=0;
const list=x=>Array.isArray(x)&&x.every(text)&&new Set(x).size===x.length;
export const decimalCents=n=>{if(!int(n))throw Error('INVALID_CENTS');const b=BigInt(n);return `${b/100n}.${String(b%100n).padStart(2,'0')}`;};
export function buildOfferContracts(input){
 const base=buildListingDrafts(input),blockers=[...base.blockers],plans=[];
 const add=(code,sku)=>blockers.push({code,path:`offer_contracts.${sku}`});
 const contracts=input.offer_contracts;
 let existingBatchQuantity=0n;
 if(!Array.isArray(contracts)||contracts.length!==base.drafts.length)add('EXACT_OFFER_CONTRACTS_REQUIRED','batch');
 for(const d of base.drafts){
  const found=(Array.isArray(contracts)?contracts:[]).filter(c=>c?.seller_sku===d.seller_sku);
  if(found.length!==1){add('UNIQUE_OFFER_CONTRACT_REQUIRED',d.seller_sku);continue;}
  const c=found[0],r=c.reconciliation,m=c.category_requirements,before=blockers.length;
  // Draft seller SKUs and matching contracts are unique. Accumulate each once;
  // invalid counts are rejected below, never coerced into the aggregate.
  if(int(r?.existing_offer_quantity))existingBatchQuantity+=BigInt(r.existing_offer_quantity);
  const scoped=e=>e?.classification==='declared_document'&&text(e.reference)&&e.account_id===input.accounts[0].account_id&&e.seller_sku===d.seller_sku&&e.category_id===d.category_id&&int(e.observed_at_ms)&&e.observed_at_ms<=input.now&&int(e.expires_at_ms)&&e.expires_at_ms>input.now;
  if(!scoped(r)||!text(r?.version)||!int(r?.max_age_ms)||r.max_age_ms===0||input.now-r.observed_at_ms>r.max_age_ms||r.scope!=='single_offer_single_marketplace'||r.pending_mutations!==0)add('CURRENT_RECONCILIATION_REQUIRED',d.seller_sku);
  if(!scoped(m)||m?.complete!==true||!list(m?.required_aspects)||!list(m?.required_identifiers)||!list(m?.allowed_conditions)||!list(m?.allowed_durations)||!Array.isArray(m?.unsupported_required_fields)||m.unsupported_required_fields.length!==0){add('COMPLETE_CATEGORY_CONTRACT_REQUIRED',d.seller_sku);continue;}
  if(!text(c.listing_duration)||!m?.allowed_durations?.includes(c.listing_duration)||!m?.allowed_conditions?.includes(d.condition))add('DURATION_OR_CONDITION_NOT_ALLOWED',d.seller_sku);
  if(m?.required_aspects?.some?.(k=>!Object.hasOwn(d.aspects,k)))add('REQUIRED_ASPECT_MISSING',d.seller_sku);
  const identifiers=c.identifiers;
  const supported=['upc','ean','isbn'];
  if(!identifiers||typeof identifiers!=='object'||Array.isArray(identifiers)||Object.entries(identifiers).some(([k,v])=>!supported.includes(k)||!Array.isArray(v)||!v.length||v.some(x=>typeof x!=='string'||!/^\d+$/.test(x)))||m?.required_identifiers?.some?.(k=>!supported.includes(k)||!Object.hasOwn(identifiers,k)))add('PRODUCT_IDENTIFIER_CONTRACT_UNSUPPORTED_OR_MISSING',d.seller_sku);
  const row=input.catalog.find(x=>x.supplier_id===d.supplier_id&&x.sku===d.sku),feed=input.feeds.find(x=>x.supplier_id===d.supplier_id),stock=feed.records.find(x=>x[feed.field_map.sku]===d.sku)[feed.field_map.quantity];
  let absolute;
  if(!int(r?.existing_offer_quantity)||!int(r?.other_reserved_quantity)||!int(r?.absolute_offer_quantity)||r.absolute_offer_quantity!==r.existing_offer_quantity+d.quantity||!Number.isSafeInteger(r.existing_offer_quantity+d.quantity)||r.absolute_offer_quantity>stock-row.safety_stock-r.other_reserved_quantity||r.existing_offer_quantity>input.accounts[0].selling_limits.used_quantity)add('ABSOLUTE_QUANTITY_RECONCILIATION_FAILED',d.seller_sku);
  else absolute=r.absolute_offer_quantity;
  if(c.shipping_mode!=='flat'||m?.package_required!==false)add('PACKAGE_OR_SHIPPING_CONTRACT_UNSUPPORTED',d.seller_sku);
  if(blockers.length===before)plans.push({seller_sku:d.seller_sku,reconciliation_version:r.version,proposed_increment:d.quantity,absolute_quantity:absolute,
   inventory_item:{condition:d.condition,availability:{shipToLocationAvailability:{quantity:absolute}},product:{title:d.title,description:d.description,aspects:d.aspects,imageUrls:d.image_urls,...identifiers}},
   offer:{sku:d.seller_sku,marketplaceId:'EBAY_US',format:'FIXED_PRICE',categoryId:d.category_id,availableQuantity:absolute,listingDuration:c.listing_duration,merchantLocationKey:d.seller_policy_references.location,listingPolicies:{paymentPolicyId:d.seller_policy_references.payment,returnPolicyId:d.seller_policy_references.returns,fulfillmentPolicyId:d.seller_policy_references.fulfillment},pricingSummary:{price:{currency:d.currency,value:decimalCents(d.price_cents)}}}});
 }
 const used=input.accounts?.[0]?.selling_limits?.used_quantity;
 // Usage can include offers outside this batch. Keep the incremental capacity
 // gate unchanged; never replace account usage with this subset's quantity.
 if(int(used)&&existingBatchQuantity>BigInt(used))add('BATCH_EXISTING_QUANTITY_EXCEEDS_ACCOUNT_USAGE','batch');
 return {mode:'sandbox',classification:'supplied_contract_preview_only',status:blockers.length?'BLOCKED':'CONTRACT_PREVIEW_UNVERIFIED',blockers,plans:blockers.length?[]:structuredClone(plans),publication_enabled:false,dispatch_enabled:false,production_ready:false,provider_validated:false,api_schema_validated:false,orders_placed:0};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
 try{const [source,output]=process.argv.slice(2);if(!source||!output)throw Error('ARGS');const r=buildOfferContracts(JSON.parse(await readFile(source,'utf8')));await writeFile(output,JSON.stringify(r,null,2)+'\n',{flag:'wx'});console.log(r.status);}
 catch{console.error('Offline contract preview failed; verify input and new output path.');process.exitCode=1;}
}
