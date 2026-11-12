import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {buildListingDrafts} from './listing-draft.mjs';
const example=JSON.parse(await readFile(new URL('./onboarding.example.json',import.meta.url),'utf8'));
function declared(){
 const c=structuredClone(example);c.fixture_data=false;
 const doc={classification:'declared_document',reference:'TEST-DECLARATION-NOT-VERIFIED',reviewed_at_ms:c.now,expires_at_ms:c.now+86400000};
 c.accounts=c.channels.map(marketplace=>({marketplace,account_id:'TEST-ACCOUNT',seller_status:'approved',credential_ref:'secret-ref://test/reference-only',access_evidence:{...doc,account_id:'TEST-ACCOUNT',marketplace}}));
 c.accounts.find(a=>a.marketplace==='ebay').selling_limits={classification:'declared_seller_snapshot',evidence_ref:'TEST-ONLY',account_id:'TEST-ACCOUNT',currency:'USD',observed_at_ms:c.now,period_end_ms:c.now+86400000,max_quantity:10,used_quantity:0,max_value_cents:30000,used_value_cents:0,pending_quantity:0,pending_value_cents:0};
 c.listing_plans={ebay:[{supplier_id:'SYNTHETIC-ONLY',sku:'DEMO-001',additional_quantity:1}]};
 c.suppliers[0].authorization_document={...doc,supplier_id:c.suppliers[0].id};
 c.suppliers[0].shipping_origin_id='TEST-ORIGIN';c.suppliers[0].authorized_origin_countries=['US'];
 c.origins=[{id:'TEST-ORIGIN',country:'US',postal_code:'00000',timezone:'America/Los_Angeles',handling_days:1}];
 c.feeds[0].classification='supplier_export';c.feeds[0].permission={...doc,supplier_id:c.suppliers[0].id};
 c.catalog[0].unit='EACH';c.catalog[0].variant_id='TEST-SINGLE';
 Object.assign(c.feeds[0].field_map,{currency:'currency',unit:'unit',variant_id:'variant'});
 Object.assign(c.feeds[0].records[0],{currency:'USD',unit:'EACH',variant:'TEST-SINGLE'});
 for(const r of c.catalog)r.supplier_quote={classification:'declared_supplier_quote',reference:'SYNTHETIC-QUOTE-NOT-VERIFIED',supplier_id:r.supplier_id,sku:r.sku,currency:r.currency,unit:r.unit,variant_id:r.variant_id,cost_cents:r.cost_cents,issued_at_ms:c.now,expires_at_ms:r.quote_expires_at_ms};
 return c;
}
function fixture(){
 const c=declared();c.channels=['ebay'];c.accounts=c.accounts.filter(a=>a.marketplace==='ebay');
 const e={classification:'declared_document',reference:'SYNTHETIC-NOT-EVIDENCE',reviewed_at_ms:c.now,expires_at_ms:c.now+1000,supplier_id:'SYNTHETIC-ONLY',sku:'DEMO-001',account_id:'TEST-ACCOUNT',category_id:'123',origin_id:'TEST-ORIGIN'};
 c.listing_details=[{supplier_id:e.supplier_id,sku:e.sku,seller_sku:'TEST-SELLER-SKU',variant_id:'TEST-SINGLE',unit:'EACH',currency:'USD',origin_id:e.origin_id,marketplace_id:'EBAY_US',format:'FIXED_PRICE',condition:'NEW',title:'Synthetic product - not for sale',description:'Authored offline test only',category_id:'123',image_urls:['https://example.invalid/test.jpg'],aspects:{Brand:['SYNTHETIC']},fulfillment_policy_id:'TEST-F',return_policy_id:'TEST-R',payment_policy_id:'TEST-P',merchant_location_key:'TEST-L',category_evidence:{...e},content_rights_evidence:{...e},shipping_returns_evidence:{...e},fee_evidence:{...e},shipping:{handling_days:1,service:'TEST-SERVICE',destination_countries:['US'],cost_cents:400},returns:{window_days:30,shipping_payer:'SELLER'}}];return c;
}
test('origin references must be explicit strings even when all declarations agree',()=>{
 for(const value of [undefined,null,'','   ',7]){
  const c=fixture();c.suppliers[0].shipping_origin_id=value;c.origins[0].id=value;c.listing_details[0].origin_id=value;
  for(const key of ['category_evidence','content_rights_evidence','shipping_returns_evidence','fee_evidence'])c.listing_details[0][key].origin_id=value;
  const r=buildListingDrafts(JSON.parse(JSON.stringify(c)));
  assert.equal(r.status,'BLOCKED');assert.deepEqual(r.drafts,[]);
  assert.ok(r.blockers.some(b=>b.code==='UNIQUE_SHIPPING_ORIGIN_REQUIRED'));
  assert.equal(r.publication_enabled,false);assert.equal(r.dispatch_enabled,false);
 }
 for(const mutation of [c=>c.origins.push({...c.origins[0]}),c=>{c.origins[0].id='OTHER';}]){
  const c=fixture();mutation(c);const r=buildListingDrafts(c);
  assert.equal(r.status,'BLOCKED');assert.deepEqual(r.drafts,[]);
 }
});
for(const [label,mutate,code] of [
 ['nested image URL',d=>{d.image_urls=[['https://example.invalid/test.jpg']];},'HTTPS_IMAGES_REQUIRED'],
 ['numeric category ID',d=>{d.category_id=123;for(const k of ['category_evidence','content_rights_evidence','shipping_returns_evidence','fee_evidence'])d[k].category_id=123;},'PRODUCT_DETAILS_REQUIRED']
])test(`reject ${label} without coercion and suppress valid sibling`,()=>{
 const c=fixture();
 const sibling=structuredClone(c.listing_details[0]);sibling.sku='DEMO-002';sibling.seller_sku='SECOND';
 for(const k of ['category_evidence','content_rights_evidence','shipping_returns_evidence','fee_evidence'])sibling[k].sku=sibling.sku;
 c.listing_details.push(sibling);c.catalog.push({...c.catalog[0],sku:sibling.sku,supplier_quote:{...c.catalog[0].supplier_quote,sku:sibling.sku}});
 c.feeds[0].records.push({...c.feeds[0].records[0],code:sibling.sku});
 c.suppliers[0].authorization.skus.push(sibling.sku);
 c.listing_plans.ebay.push({...c.listing_plans.ebay[0],sku:sibling.sku});
 assert.equal(buildListingDrafts(c).drafts.length,2);
 mutate(c.listing_details[0]);
 const r=buildListingDrafts(JSON.parse(JSON.stringify(c)));
 assert.equal(r.status,'BLOCKED');assert.ok(r.blockers.some(b=>b.code===code));
 assert.deepEqual(r.drafts,[]);assert.equal(r.publication_enabled,false);assert.equal(r.dispatch_enabled,false);
});
test('offline draft composes declared stock, exact costs and explicit product/shipping facts',()=>{
 const c=fixture(),r=buildListingDrafts(c);assert.deepEqual(r.blockers,[]);assert.equal(r.drafts.length,1);assert.equal(r.drafts[0].economics.projected_profit_cents,820);assert.equal(r.drafts[0].quantity,1);assert.equal(r.production_ready,false);assert.equal(r.dispatch_enabled,false);assert.equal(r.publication_enabled,false);
 r.drafts[0].shipping.cost_cents=0;assert.equal(c.listing_details[0].shipping.cost_cents,400);
});

test('malformed onboarding collections return blockers instead of crashing draft assembly',()=>{
 for(const mutate of [c=>c.catalog=null,c=>c.suppliers=null,c=>c.origins=null,c=>c.listing_plans.ebay={},c=>c.listing_plans.ebay=[null]]){
  const c=fixture();mutate(c);const r=buildListingDrafts(c);
  assert.equal(r.status,'BLOCKED');assert.ok(r.blockers.length);assert.deepEqual(r.drafts,[]);
  assert.equal(r.dispatch_enabled,false);
 }
});
test('missing authorization, stock, origin, mismatches and uncosted shipping block all drafts',()=>{
 const mutations=[c=>c.suppliers[0].authorization.channels=[],c=>c.feeds[0].records=[],c=>c.feeds[0].records[0].updated=0,c=>c.origins=[],c=>c.listing_details[0].currency='EUR',c=>c.listing_details[0].variant_id='OTHER',c=>c.listing_details[0].unit='CASE',c=>c.listing_details[0].shipping.cost_cents=0,c=>c.listing_details[0].shipping.handling_days=0,c=>delete c.listing_details[0].fee_evidence,c=>c.listing_details[0].category_evidence.sku='OTHER',c=>c.catalog[0].return_reserve_bps=0,c=>c.listing_details[0].group_id='GROUP',c=>c.listing_details[0].image_urls=['http://example.invalid/a'],c=>c.accounts[0].selling_limits.used_quantity=10];
 for(const mutate of mutations){const c=fixture();mutate(c);const r=buildListingDrafts(c);assert.equal(r.status,'BLOCKED');assert.deepEqual(r.drafts,[]);assert.equal(r.publication_enabled,false);}
});
