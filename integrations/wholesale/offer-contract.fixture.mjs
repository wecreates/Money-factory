// Authored synthetic fixture; no real account or supplier evidence.
import {readFile} from 'node:fs/promises';
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
export function fixture(){
 const c=declared();c.channels=['ebay'];c.accounts=c.accounts.filter(a=>a.marketplace==='ebay');
 const e={classification:'declared_document',reference:'SYNTHETIC-NOT-EVIDENCE',reviewed_at_ms:c.now,expires_at_ms:c.now+1000,supplier_id:'SYNTHETIC-ONLY',sku:'DEMO-001',account_id:'TEST-ACCOUNT',category_id:'123',origin_id:'TEST-ORIGIN'};
 c.listing_details=[{supplier_id:e.supplier_id,sku:e.sku,seller_sku:'TEST-SELLER-SKU',variant_id:'TEST-SINGLE',unit:'EACH',currency:'USD',origin_id:e.origin_id,marketplace_id:'EBAY_US',format:'FIXED_PRICE',condition:'NEW',title:'Synthetic product - not for sale',description:'Authored offline test only',category_id:'123',image_urls:['https://example.invalid/test.jpg'],aspects:{Brand:['SYNTHETIC']},fulfillment_policy_id:'TEST-F',return_policy_id:'TEST-R',payment_policy_id:'TEST-P',merchant_location_key:'TEST-L',category_evidence:{...e},content_rights_evidence:{...e},shipping_returns_evidence:{...e},fee_evidence:{...e},shipping:{handling_days:1,service:'TEST-SERVICE',destination_countries:['US'],cost_cents:400},returns:{window_days:30,shipping_payer:'SELLER'}}];return c;
}