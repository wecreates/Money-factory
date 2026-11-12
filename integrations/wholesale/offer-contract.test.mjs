import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture} from './offer-contract.fixture.mjs';
import {buildOfferContracts,decimalCents} from './offer-contract.mjs';
function input(){
 const c=fixture();c.accounts[0].selling_limits.used_quantity=2;c.accounts[0].selling_limits.used_value_cents=6000;
 const e={classification:'declared_document',reference:'SYNTHETIC',account_id:'TEST-ACCOUNT',seller_sku:'TEST-SELLER-SKU',category_id:'123',observed_at_ms:c.now,expires_at_ms:c.now+1000};
 c.offer_contracts=[{seller_sku:e.seller_sku,listing_duration:'GTC',shipping_mode:'flat',identifiers:{},reconciliation:{...e,version:'SYNTHETIC-V1',max_age_ms:1000,scope:'single_offer_single_marketplace',pending_mutations:0,existing_offer_quantity:2,other_reserved_quantity:1,absolute_offer_quantity:3},category_requirements:{...e,complete:true,required_aspects:['Brand'],required_identifiers:[],allowed_conditions:['NEW'],allowed_durations:['GTC'],unsupported_required_fields:[],package_required:false}}];return c;
}
function twoOffers(){
 const c=input(),sku='DEMO-002',seller='SECOND';
 c.catalog.push({...c.catalog[0],sku,supplier_quote:{...c.catalog[0].supplier_quote,sku}});c.feeds[0].records.push({...c.feeds[0].records[0],code:sku});
 c.suppliers[0].authorization.skus.push(sku);c.listing_plans.ebay.push({...c.listing_plans.ebay[0],sku});
 const d=structuredClone(c.listing_details[0]);d.sku=sku;d.seller_sku=seller;
 for(const k of ['category_evidence','content_rights_evidence','shipping_returns_evidence','fee_evidence'])d[k].sku=sku;
 c.listing_details.push(d);
 const contract=structuredClone(c.offer_contracts[0]);contract.seller_sku=seller;contract.reconciliation.seller_sku=seller;contract.category_requirements.seller_sku=seller;c.offer_contracts.push(contract);
 return c;
}
test('malformed prerequisite and category collections yield blocked contract reports',()=>{
 for(const mutate of [c=>c.catalog=null,c=>c.listing_plans.ebay={},c=>c.offer_contracts[0].category_requirements.allowed_durations=7,c=>c.offer_contracts[0].category_requirements.allowed_conditions={},c=>c.offer_contracts[0].category_requirements.required_aspects={some:'not-a-function'}]){
  const c=input();mutate(c);const r=buildOfferContracts(c);
  assert.equal(r.status,'BLOCKED');assert.ok(r.blockers.length);assert.deepEqual(r.plans,[]);
  assert.equal(r.publication_enabled,false);assert.equal(r.dispatch_enabled,false);
 }
});
test('aggregate existing quantities cannot reuse account usage across distinct offers',()=>{
 const c=twoOffers();c.accounts[0].selling_limits.max_quantity=4;
 const r=buildOfferContracts(JSON.parse(JSON.stringify(c)));
 assert.equal(r.status,'BLOCKED');assert.deepEqual(r.plans,[]);
 assert.ok(r.blockers.some(b=>b.code==='BATCH_EXISTING_QUANTITY_EXCEEDS_ACCOUNT_USAGE'));
 assert.equal(r.publication_enabled,false);assert.equal(r.dispatch_enabled,false);
});
test('consistent batch accepts equality or unused account usage outside this batch',()=>{
 for(const used of [4,5]){
  const c=twoOffers();c.accounts[0].selling_limits.used_quantity=used;c.accounts[0].selling_limits.max_quantity=used+2;
  const r=buildOfferContracts(c);assert.deepEqual(r.blockers,[]);assert.deepEqual(r.plans.map(p=>p.absolute_quantity),[3,3]);assert.equal(r.provider_validated,false);
 }
});
test('serializes explicit absolute stock independently from increment and exact cents',()=>{
 const c=input(),r=buildOfferContracts(c);assert.deepEqual(r.blockers,[]);
 assert.equal(r.plans[0].proposed_increment,1);assert.equal(r.plans[0].offer.availableQuantity,3);assert.equal(r.plans[0].inventory_item.availability.shipToLocationAvailability.quantity,3);
 assert.deepEqual(r.plans[0].offer.pricingSummary.price,{currency:'USD',value:'30.00'});
 for(const flag of ['publication_enabled','dispatch_enabled','production_ready','provider_validated','api_schema_validated'])assert.equal(r[flag],false);
 assert.equal(decimalCents(1),'0.01');assert.equal(decimalCents(100),'1.00');assert.equal(decimalCents(Number.MAX_SAFE_INTEGER),'90071992547409.91');assert.throws(()=>decimalCents(1.5));
 r.plans[0].inventory_item.product.aspects.Brand[0]='changed';assert.equal(c.listing_details[0].aspects.Brand[0],'SYNTHETIC');
});
test('unknown metadata, stale reconciliation, unpaid allocations and mismatched absolute stock block previews',()=>{
 const cases=[c=>delete c.offer_contracts,c=>c.offer_contracts[0].reconciliation.absolute_offer_quantity=1,c=>c.offer_contracts[0].reconciliation.other_reserved_quantity=7,c=>c.offer_contracts[0].reconciliation.pending_mutations=1,c=>c.offer_contracts[0].reconciliation.observed_at_ms=0,c=>c.offer_contracts[0].reconciliation.account_id='OTHER',c=>delete c.offer_contracts[0].listing_duration,c=>c.offer_contracts[0].category_requirements.complete=false,c=>c.offer_contracts[0].category_requirements.required_aspects=['Missing'],c=>c.offer_contracts[0].category_requirements.required_identifiers=['upc'],c=>c.offer_contracts[0].category_requirements.unsupported_required_fields=['regulatory'],c=>c.offer_contracts[0].category_requirements.package_required=true,c=>c.offer_contracts[0].identifiers={upc:[123]},c=>c.suppliers[0].authorization.channels=[]];
 for(const mutate of cases){const c=input();mutate(c);const r=buildOfferContracts(c);assert.equal(r.status,'BLOCKED');assert.deepEqual(r.plans,[]);assert.equal(r.dispatch_enabled,false);}
});
