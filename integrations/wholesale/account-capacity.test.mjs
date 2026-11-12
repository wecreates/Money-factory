import test from 'node:test';
import assert from 'node:assert/strict';
import {accountCapacity} from './account-capacity.mjs';
const now=100000000,account={account_id:'TEST',insertion_allowance:250,selling_limits:{classification:'declared_seller_snapshot',evidence_ref:'TEST-ONLY',account_id:'TEST',currency:'USD',observed_at_ms:now,period_end_ms:now+10000,max_quantity:10,used_quantity:7,pending_quantity:1,max_value_cents:10000,used_value_cents:7000,pending_value_cents:1000}};
const catalog=[{supplier_id:'TEST',sku:'X',price_cents:1000}],inventory=[{supplier_id:'TEST',sku:'X',available:8,feed_status:'current',quote_current:true}],plan=[{supplier_id:'TEST',sku:'X',additional_quantity:2}];
const check=(a=account,p=plan,i=inventory)=>accountCapacity(a,p,catalog,i,now);
test('capacity uses quantities and exact value including pending allocation, never free insertion allowance',()=>{
 const r=check();assert.equal(r.status,'WITHIN_DECLARED_LIMITS_UNVERIFIED');assert.equal(r.production_authorized,false);
 const over=check(account,[{...plan[0],additional_quantity:3}]);assert.ok(over.blockers.includes('SELLING_QUANTITY_LIMIT_EXCEEDED'));assert.ok(over.blockers.includes('SELLING_VALUE_LIMIT_EXCEEDED'));
 assert.ok(check({...account,selling_limits:undefined,reported_increase_prerequisite_dollars:1000}).blockers.includes('SELLER_LIMIT_SNAPSHOT_REQUIRED'));
});
test('stale mismatched and incomplete limits fail closed; duplicate and stale stock cannot supply capacity',()=>{
 for(const delta of [{observed_at_ms:now+1},{observed_at_ms:0},{period_end_ms:now},{account_id:'OTHER'},{classification:'user_reported'},{pending_quantity:undefined},{currency:'EUR'}])assert.equal(check({...account,selling_limits:{...account.selling_limits,...delta}}).status,'BLOCKED');
 assert.ok(check(account,[...plan,...plan]).blockers.includes('DUPLICATE_PLANNED_SKU'));
 assert.ok(check(account,plan,[{...inventory[0],feed_status:'stale_or_future',available:0}]).blockers.includes('PLANNED_QUANTITY_EXCEEDS_CURRENT_STOCK'));
});
