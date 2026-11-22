import test from 'node:test';
import assert from 'node:assert/strict';
import {importCatalog,economics,supplierBlockers,inventoryPlan,SandboxOrders} from './engine.mjs';
const now=100000;
const row={supplier_id:'fixture',sku:'DEMO',currency:'USD',price_cents:3000,cost_cents:1000,shipping_cents:400,handling_cents:100,tax_cents:50,fee_bps:1500,fixed_fee_cents:30,min_fee_cents:0,return_reserve_bps:500,quote_expires_at_ms:200000,safety_stock:2};
const supplier={id:'fixture',relationship:'wholesale',authorization:{channels:['amazon','walmart','ebay'],skus:['DEMO'],evidence_id:'SIMULATION',expires_at_ms:200000},seller_of_record:true,neutral_packaging:true,returns:{evidence_id:'SIMULATION',expires_at_ms:200000}};
const feed={supplier_id:'fixture',sku:'DEMO',quantity:10,observed_at_ms:90000,max_age_ms:20000};
const create=()=>new SandboxOrders({catalog:[row],suppliers:[supplier],snapshots:[feed],now});
const order=(id='o1',marketplace='amazon',quantity=2)=>({id,marketplace,supplier_id:'fixture',sku:'DEMO',quantity});

test('zero feed age policy cannot bypass onboarding through direct engine or sync',()=>{
 const invalid={...feed,observed_at_ms:now,max_age_ms:0};
 assert.throws(()=>inventoryPlan([row],[invalid],[],now),/INVALID_MAX_AGE/);
 assert.throws(()=>new SandboxOrders({catalog:[row],suppliers:[supplier],snapshots:[invalid],now}),/INVALID_MAX_AGE/);
 const s=create();s.route(order());const before=s.snapshot();
 assert.throws(()=>s.syncInventory([invalid],now),/INVALID_MAX_AGE/);
 assert.deepEqual(s.snapshot(),before);
 // An explicit positive policy includes its age boundary, then suppresses stock.
 const valid={...feed,observed_at_ms:now,max_age_ms:1};
 assert.equal(inventoryPlan([row],[valid],[],now+1)[0].available,8);
 assert.equal(inventoryPlan([row],[valid],[],now+2)[0].available,0);
});
test('margin basis points use exact signed floor arithmetic',()=>{
 const base={...row,price_cents:100,cost_cents:43,shipping_cents:0,handling_cents:0,tax_cents:0,fee_bps:0,fixed_fee_cents:0,min_fee_cents:0,return_reserve_bps:0};
 assert.equal(economics(base).margin_bps,5700);
 assert.equal(economics({...base,price_cents:3,cost_cents:2}).margin_bps,3333);
 assert.equal(economics({...base,price_cents:3,cost_cents:4}).margin_bps,-3334);
 assert.equal(economics({...base,cost_cents:100}).margin_bps,0);
 assert.equal(economics({...base,cost_cents:0}).margin_bps,10000);
 assert.throws(()=>economics({...base,price_cents:1,cost_cents:Number.MAX_SAFE_INTEGER}),/MARGIN/);
});
test('catalog rejects duplicates and invalid money, rate, currency and identifiers',()=>{
 assert.throws(()=>importCatalog([row,row]),/DUPLICATE/);
 for(const [f,v] of [['cost_cents',-1],['price_cents',NaN],['shipping_cents',1.5],['fee_bps',10001],['currency','EUR'],['sku','']]) assert.throws(()=>importCatalog([{...row,[f]:v}]));
 const rows=importCatalog([row]); rows[0].sku='changed'; assert.equal(row.sku,'DEMO');
});
test('economics includes landed charges, fixed fee and reserve without booked profit',()=>{
 const e=economics(row); assert.equal(e.landed_cost_cents,1550); assert.equal(e.marketplace_fee_cents,480); assert.equal(e.return_reserve_cents,150); assert.equal(e.projected_profit_cents,820); assert.equal(e.verified_profit_cents,0);
 assert.equal(economics({...row,min_fee_cents:600}).marketplace_fee_cents,600);
 assert.equal(economics({...row,price_cents:3001}).return_reserve_cents,151);
 assert.throws(()=>economics({...row,cost_cents:Number.MAX_SAFE_INTEGER}),/TOTAL_COST/);
});
test('supplier policy requires explicit current channel and SKU evidence',()=>{
 assert.deepEqual(supplierBlockers(supplier,'amazon','DEMO',now),[]);
 assert.ok(supplierBlockers({...supplier,relationship:'retail'},'amazon','DEMO',now).includes('WHOLESALE_RELATIONSHIP_REQUIRED'));
 assert.ok(supplierBlockers(supplier,'etsy','DEMO',now).length);
 assert.ok(supplierBlockers(supplier,'amazon','unknown',now).length);
 assert.ok(supplierBlockers({...supplier,neutral_packaging:false},'amazon','DEMO',now).length);
 assert.ok(supplierBlockers(supplier,'amazon','DEMO',200000).length);
});
test('inventory zeroes missing, old, future and expired quotes; subtracts global reservations',()=>{
 assert.equal(inventoryPlan([row],[feed],[{supplier_id:'fixture',sku:'DEMO',quantity:3}],now)[0].available,5);
 for(const feeds of [[],[{...feed,observed_at_ms:1}],[{...feed,observed_at_ms:now+1}]]) assert.equal(inventoryPlan([row],feeds,[],now)[0].available,0);
 assert.equal(inventoryPlan([{...row,quote_expires_at_ms:now}],[feed],[],now)[0].available,0);
 assert.throws(()=>inventoryPlan([row],[feed,feed],[],now),/DUPLICATE/);
});
test('route is idempotent, cross-market reservations prevent oversell and reject changed retries',()=>{
 const s=create(); s.route(order()); s.route(order()); assert.equal(s.snapshot().inventory[0].available,6);
 assert.throws(()=>s.route(order('o1','amazon',3)),/IDEMPOTENCY/);
 s.route(order('o2','walmart',6)); assert.equal(s.snapshot().inventory[0].available,0);
 assert.throws(()=>s.route(order('o3','ebay',1)),/INSUFFICIENT/);
});
test('cancellation holds stock until supplier confirmation and terminal transitions fail',()=>{
 const s=create(); s.route(order()); s.requestCancel('o1'); assert.equal(s.snapshot().inventory[0].available,6); assert.throws(()=>s.confirmCancel('o1',''),/EVIDENCE/); s.confirmCancel('o1','SIM-CANCEL'); assert.equal(s.snapshot().inventory[0].available,8);
 assert.throws(()=>s.accept('o1','ref'),/TRANSITION/); assert.throws(()=>s.confirmCancel('o1','SIM-CANCEL'),/TRANSITION/);
});
test('inventory sync replaces snapshot atomically and keeps conservative reservations',()=>{
 const s=create(); s.route(order()); const old=s.snapshot();
 assert.throws(()=>s.syncInventory([feed],now-1),/CLOCK_REGRESSION/); assert.deepEqual(s.snapshot(),old);
 assert.throws(()=>s.syncInventory([{...feed,quantity:-1}],now+1),/INVALID/); assert.deepEqual(s.snapshot(),old);
 assert.equal(s.syncInventory([{...feed,quantity:20,observed_at_ms:now+1}],now+1)[0].available,16);
 assert.equal(s.syncInventory([],now+2)[0].available,0); assert.equal(s.snapshot().inventory[0].reserved_quantity,2);
});
test('supplier cancellation refusal restores previous state and allows accepted order tracking',()=>{
 const s=create(); s.route(order()); s.requestCancel('o1'); assert.equal(s.denyCancel('o1','SIM-DENIED').state,'routed');
 s.accept('o1','SIM-REF'); s.requestCancel('o1'); assert.throws(()=>s.denyCancel('o1',''),/REFERENCE/);
 assert.equal(s.denyCancel('o1','SIM-TOO-LATE').state,'accepted'); assert.equal(s.snapshot().inventory[0].available,6);
 assert.throws(()=>s.denyCancel('o1','SIM-REPEAT'),/TRANSITION/);
 assert.equal(s.track('o1',{carrier:'UPS',tracking_number:'DEMO',tendered_at_ms:now,evidence_id:'SIM-TENDER'}).state,'shipped');
});
test('tracking and return/refund follow strict simulated state machine; returns do not assume restock',()=>{
 const tracking={carrier:'UPS',tracking_number:'DEMO',tendered_at_ms:now,evidence_id:'SIM-TENDER'};
 const s=create(); s.route(order()); assert.throws(()=>s.track('o1',tracking),/TRANSITION/);
 s.accept('o1','SIM-REF'); assert.throws(()=>s.track('o1',{...tracking,tendered_at_ms:now+1}),/FUTURE_TENDER/); assert.throws(()=>s.track('o1',{...tracking,evidence_id:''}),/TENDER_EVIDENCE/); s.track('o1',tracking); assert.throws(()=>s.requestCancel('o1'),/TRANSITION/);
 s.requestReturn('o1'); assert.throws(()=>s.refund('o1'),/TRANSITION/); s.authorizeReturn('o1','SIM-RMA'); s.receiveReturn('o1'); s.refund('o1');
 const state=s.snapshot(); assert.equal(state.orders[0].state,'refunded'); assert.equal(state.inventory[0].available,6); assert.equal(state.external_effects,0); assert.equal(state.verified_profit_cents,0); assert.doesNotThrow(()=>JSON.stringify(state)); assert.throws(()=>s.refund('o1'),/TRANSITION/);
});
test('live mode, expired quote, unprofitable catalog and unauthorized supplier cannot route',()=>{
 assert.throws(()=>new SandboxOrders({mode:'live'}),/LIVE_MODE_DISABLED/);
 for(const badRow of [{...row,quote_expires_at_ms:now},{...row,cost_cents:5000}]){const s=new SandboxOrders({catalog:[badRow],suppliers:[supplier],snapshots:[feed],now}); assert.throws(()=>s.route(order()));}
 const s=new SandboxOrders({catalog:[row],suppliers:[{...supplier,relationship:'retail'}],snapshots:[feed],now}); assert.throws(()=>s.route(order()),/WHOLESALE/);
});
