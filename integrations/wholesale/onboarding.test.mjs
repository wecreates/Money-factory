import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {checkOnboarding} from './onboarding.mjs';
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
test('example catalog and fixture feed produce actionable blockers, not seller readiness',()=>{
 const r=checkOnboarding(example),codes=r.blockers.map(b=>b.code);
 for(const code of ['FIXTURE_DATA_NOT_PRODUCTION_EVIDENCE','UNIQUE_SELLER_ACCOUNT_REQUIRED','CURRENT_DOCUMENT_DECLARATION_REQUIRED','UNIQUE_SHIPPING_ORIGIN_REQUIRED','FIXTURE_FEED_NOT_PRODUCTION_EVIDENCE'])assert.ok(codes.includes(code),code);
 assert.equal(r.checked_catalog_rows,1);assert.equal(r.checked_inventory_rows,1);assert.equal(r.production_ready,false);
});
test('feed identity cannot silently replace currency, selling unit or variant',()=>{
 for(const [field,value] of [['currency','EUR'],['unit','CASE'],['variant','OTHER']]){
  const c=declared();c.feeds[0].records[0][field]=value;
  const r=checkOnboarding(c);
  assert.equal(r.configuration_complete,false,field);
  assert.ok(r.blockers.some(b=>b.code==='FEED_PRODUCT_IDENTITY_MISMATCH'),field);
  assert.equal(r.publication_enabled,false);
 }
});
test('supplier quote must bind current dated unit cost to the exact catalog identity',()=>{
 for(const mutate of [c=>delete c.catalog[0].supplier_quote,c=>c.catalog[0].supplier_quote.cost_cents++,c=>c.catalog[0].supplier_quote.sku='OTHER',c=>c.catalog[0].supplier_quote.currency='EUR',c=>c.catalog[0].supplier_quote.unit='CASE',c=>c.catalog[0].supplier_quote.variant_id='OTHER',c=>c.catalog[0].supplier_quote.issued_at_ms=c.now+1,c=>c.catalog[0].supplier_quote.expires_at_ms=c.now]){
  const c=declared();const r=c.catalog[0];r.supplier_quote={classification:'declared_supplier_quote',reference:'SYNTHETIC-QUOTE',supplier_id:r.supplier_id,sku:r.sku,currency:r.currency,unit:r.unit,variant_id:r.variant_id,cost_cents:r.cost_cents,issued_at_ms:c.now,expires_at_ms:r.quote_expires_at_ms};
  mutate(c);const result=checkOnboarding(c);assert.equal(result.configuration_complete,false);assert.ok(result.blockers.some(b=>b.code==='CURRENT_MATCHING_SUPPLIER_QUOTE_REQUIRED'));
 }
});
test('supplied quote landed charges cannot contradict the costed catalog',()=>{
 for(const field of ['shipping_cents','handling_cents','tax_cents']){
  for(const value of [999999,null,'0',-1,1.5]){
   const c=declared();c.catalog[0].supplier_quote[field]=value;
   const result=checkOnboarding(c);
   assert.equal(result.configuration_complete,false,`${field}:${value}`);
   assert.ok(result.blockers.some(b=>b.code==='SUPPLIER_QUOTE_LANDED_CHARGE_MISMATCH'));
   assert.equal(result.publication_enabled,false);
  }
 }
 const c=declared();for(const field of ['shipping_cents','handling_cents','tax_cents'])c.catalog[0].supplier_quote[field]=c.catalog[0][field];
 assert.equal(checkOnboarding(c).status,'DECLARATIONS_COMPLETE_UNVERIFIED');
});
test('absent identity declarations and shipping origin remain onboarding blockers',()=>{
 for(const mutate of [c=>delete c.feeds[0].field_map.unit,c=>delete c.feeds[0].records[0].variant,c=>delete c.catalog[0].variant_id,c=>c.origins=[]]){
  const c=declared();mutate(c);const r=checkOnboarding(c);
  assert.equal(r.configuration_complete,false);assert.equal(r.publication_enabled,false);
 }
});
test('complete declarations validate mappings but can never authenticate access or enable dispatch',()=>{
 const r=checkOnboarding(declared());assert.deepEqual(r.blockers,[]);assert.equal(r.status,'DECLARATIONS_COMPLETE_UNVERIFIED');
 assert.equal(r.configuration_complete,true);assert.equal(r.provider_validated,false);assert.equal(r.production_ready,false);assert.equal(r.publication_enabled,false);
 assert.ok(r.external_prerequisites.length);assert.equal(JSON.stringify(r).includes('secret-ref'),false);
});
test('invalid onboarding prerequisites fail closed with scoped blockers and no secret disclosure',()=>{
 const cases=[
  [c=>c.accounts[0].credential_ref='plaintext-secret','PRIVATE_CREDENTIAL_REFERENCE_REQUIRED'],
  [c=>c.accounts[0].access_evidence.marketplace='ebay','ACCESS_EVIDENCE_SCOPE_MISMATCH'],
  [c=>c.suppliers[0].authorization.channels=['ebay'],'CHANNEL_AUTHORIZATION_REQUIRED'],
  [c=>c.suppliers[0].relationship='retail','WHOLESALE_RELATIONSHIP_REQUIRED'],
  [c=>c.suppliers[0].authorization_document.expires_at_ms=c.now,'CURRENT_DOCUMENT_DECLARATION_REQUIRED'],
  [c=>c.origins[0].timezone='Invalid/Zone','SHIPPING_ORIGIN_INVALID'],
  [c=>c.origins[0].country='CA','SHIPPING_ORIGIN_NOT_AUTHORIZED'],
  [c=>c.feeds[0].records[0].updated=c.now+1,'CURRENT_INVENTORY_REQUIRED'],
  [c=>c.feeds[0].records[0].updated=0,'CURRENT_INVENTORY_REQUIRED'],
  [c=>c.feeds[0].field_map.quantity='unknown','FEED_MAPPED_FIELD_MISSING'],
  [c=>c.feeds[0].records[0].stock='10','MAPPED_INVENTORY_INVALID'],
  [c=>c.feeds[0].quantity_semantics='already_deducted','FEED_RECONCILIATION_CONTRACT_REQUIRED'],
  [c=>c.feeds[0].permission.supplier_id='different','FEED_PERMISSION_SCOPE_MISMATCH'],
  [c=>c.accounts.push(null),'CONFIG_RECORD_INVALID'],
  [c=>c.accounts[0].client_secret='DO-NOT-ECHO-THIS','INLINE_SECRET_FORBIDDEN']
 ];
 for(const [mutate,code] of cases){const c=declared();mutate(c);const r=checkOnboarding(c);assert.ok(r.blockers.some(b=>b.code===code),code);assert.equal(r.configuration_complete,false);assert.equal(JSON.stringify(r).includes('DO-NOT-ECHO-THIS'),false);}
});
