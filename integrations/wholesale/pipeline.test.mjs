import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,mkdtemp,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {SandboxLedger} from './ledger.mjs';
import {inventoryPlan} from './engine.mjs';
import {ingestMockPage} from './pipeline.mjs';
const fixture=JSON.parse(await readFile(new URL('./sandbox-input.json',import.meta.url),'utf8'));
const raw={orderId:'MOCK-1',orderFulfillmentStatus:'NOT_STARTED',orderPaymentStatus:'PAID',cancelStatus:{cancelState:'NONE_REQUESTED'},lineItems:[{lineItemId:'LINE-1',sku:'seller-sku',quantity:2}]};
async function setup(t){
 const dir=await mkdtemp(join(tmpdir(),'wholesale-pipeline-'));t.after(()=>rm(dir,{recursive:true,force:true}));
 const ledger=new SandboxLedger(join(dir,'state.json'));
 await ledger.initialize({inventory:inventoryPlan(fixture.catalog,fixture.snapshots,[],fixture.now).map(s=>({...s,quantity:s.available}))});
 return {...fixture,fixture_data:true,marketplace:'ebay',account_id:'MOCK-ACCOUNT',response:{orders:[raw]},ledger,mappings:[{marketplace:'ebay',account_id:'MOCK-ACCOUNT',seller_sku:'seller-sku',supplier_id:'SYNTHETIC-ONLY',supplier_sku:'DEMO-001'}]};
}
test('raw mock page routes through policy gates into durable ledger and deduplicates restart',async t=>{
 const input=await setup(t);let result=await ingestMockPage(input);assert.equal(result.results[0].status,'SIMULATED_RESERVED');
 const first=await input.ledger.read();await ingestMockPage({...input,ledger:new SandboxLedger(input.ledger.path)});assert.deepEqual(await input.ledger.read(),first);
 assert.equal(Object.values(first.inventory)[0],6);assert.equal(result.provider_validated,false);assert.equal(result.poll_watermark_advanced,false);
});

test('invalid zero freshness policy rejects ingestion before any ledger mutation',async t=>{
 const input=await setup(t),before=await input.ledger.read();
 const snapshots=input.snapshots.map(s=>({...s,observed_at_ms:input.now,max_age_ms:0}));
 await assert.rejects(()=>ingestMockPage({...input,snapshots}),/INVALID_MAX_AGE/);
 assert.deepEqual(await input.ledger.read(),before);
});
test('identical retry after stock depletion replays without reserving; new and conflicting orders stay blocked',async t=>{
 const input=await setup(t);
 assert.equal((await ingestMockPage(input)).results[0].status,'SIMULATED_RESERVED');
 const before=await input.ledger.read();
 const depleted={...input,snapshots:input.snapshots.map(s=>({...s,quantity:0})),ledger:new SandboxLedger(input.ledger.path)};
 const replay=(await ingestMockPage(depleted)).results[0];
 assert.equal(replay.status,'SIMULATED_REPLAY');
 assert.equal(replay.reservation_created,false);
 assert.equal(replay.ledger_version,before.version);
 const conflict=(await ingestMockPage({...depleted,response:{orders:[{...raw,lineItems:[{...raw.lineItems[0],quantity:3}]}]}})).results[0];
 assert.equal(conflict.reason,'IDEMPOTENCY_CONFLICT');
 const fresh=(await ingestMockPage({...depleted,response:{orders:[{...raw,orderId:'MOCK-NEW'}]}})).results[0];
 assert.equal(fresh.status,'BLOCKED');
 assert.equal(fresh.reason,'INSUFFICIENT_INVENTORY');
 const otherAccount=(await ingestMockPage({...depleted,account_id:'OTHER',mappings:depleted.mappings.map(m=>({...m,account_id:'OTHER'}))})).results[0];
 assert.equal(otherAccount.reason,'INSUFFICIENT_INVENTORY');
 const noRights=(await ingestMockPage({...input,suppliers:[]})).results[0];
 assert.equal(noRights.status,'BLOCKED');
 assert.equal(noRights.reason,'UNIQUE_SUPPLIER_REQUIRED');
 assert.deepEqual(await input.ledger.read(),before);
});
test('blocked supplier, missing mapping, stale inventory and already shipped order cannot reserve',async t=>{
 const input=await setup(t);
 for(const changes of [{suppliers:[]},{mappings:[]},{now:fixture.now+86400001},{response:{orders:[{...raw,orderFulfillmentStatus:'FULFILLED'}]}}]){
  const result=await ingestMockPage({...input,...changes});assert.equal(result.results[0].status,'BLOCKED');assert.equal((await input.ledger.read()).version,0);
 }
 await assert.rejects(()=>ingestMockPage({...input,fixture_data:false}),/MOCK_SANDBOX/);
});
test('partial page outcome retains explicit failure and cursor without watermark advancement',async t=>{
 const input=await setup(t);const response={orders:[raw,{...raw,orderId:'MOCK-2',lineItems:[{lineItemId:'LINE-2',sku:'unmapped',quantity:1}]}],next:'https://api.ebay.com/sell/fulfillment/v1/order?offset=2'};
 const r=await ingestMockPage({...input,response});assert.deepEqual(r.results.map(x=>x.status),['SIMULATED_RESERVED','BLOCKED']);assert.equal(r.page_complete,false);assert.equal(r.next_cursor,response.next);assert.equal(r.poll_watermark_advanced,false);
});
test('cancelled order replay reports terminal quantities without resurrecting reservation',async t=>{
 const input=await setup(t);await ingestMockPage(input);
 const identity={marketplace:'ebay',account_id:'MOCK-ACCOUNT',order_id:'MOCK-1'};
 await input.ledger.transact({type:'cancel',identity,evidence_id:'CANCEL-CONFIRMED',lines:[{line_id:'LINE-1',quantity:2}]});
 const before=await input.ledger.read();const r=await ingestMockPage(input);
 assert.equal(r.results[0].status,'SIMULATED_REPLAY');
 assert.equal(r.results[0].fulfillment_state,'cancelled');
 assert.equal(r.results[0].reservation_created,false);
 assert.deepEqual(await input.ledger.read(),before);assert.equal(Object.values(before.inventory)[0],8);
});
test('concurrent page retries create exactly one reservation receipt',async t=>{
 const input=await setup(t);
 const results=await Promise.all([ingestMockPage(input),ingestMockPage({...input,ledger:new SandboxLedger(input.ledger.path)})]);
 assert.deepEqual(results.map(r=>r.results[0].status).sort(),['SIMULATED_REPLAY','SIMULATED_RESERVED']);
 assert.equal(results.filter(r=>r.results[0].reservation_created).length,1);
 assert.equal(Object.values((await input.ledger.read()).inventory)[0],6);
});
test('replays reflect partial shipment and returned/refunded units without dispatch intent',async t=>{
 const input=await setup(t);await ingestMockPage(input);
 const identity={marketplace:'ebay',account_id:'MOCK-ACCOUNT',order_id:'MOCK-1'};
 await input.ledger.transact({type:'ship',identity,package_id:'p1',carrier:'MOCK',tracking_number:'MOCK',tendered_at_ms:input.now,evidence_id:'MOCK',lines:[{line_id:'LINE-1',quantity:1}]},{now:input.now});
 let r=(await ingestMockPage(input)).results[0];assert.equal(r.fulfillment_state,'partially_shipped');assert.equal(r.status,'SIMULATED_REPLAY');assert.equal(r.lines[0].remaining,1);
 await input.ledger.transact({type:'cancel',identity,evidence_id:'CANCEL',lines:[{line_id:'LINE-1',quantity:1}]});
 await input.ledger.transact({type:'return',identity,return_id:'RETURN',lines:[{line_id:'LINE-1',quantity:1}]});
 await input.ledger.transact({type:'refund',identity,refund_id:'REFUND',amount_cents:3000});
 const before=await input.ledger.read();r=(await ingestMockPage(input)).results[0];
 assert.equal(r.fulfillment_state,'returned');assert.equal(r.fulfillment_closed,true);assert.equal(r.refunded_cents,3000);assert.equal(r.reservation_created,false);assert.deepEqual(await input.ledger.read(),before);
});
test('terminal replay cannot change quantity or redirect the same order to a different supplier',async t=>{
 const input=await setup(t);await ingestMockPage(input);
 await input.ledger.transact({type:'cancel',identity:{marketplace:'ebay',account_id:'MOCK-ACCOUNT',order_id:'MOCK-1'},evidence_id:'CANCEL',lines:[{line_id:'LINE-1',quantity:2}]});
 const before=await input.ledger.read();
 const altered={...input,response:{orders:[{...raw,lineItems:[{...raw.lineItems[0],quantity:3}]}]}};
 const redirected={...input,catalog:input.catalog.map(r=>({...r,supplier_id:'OTHER'})),suppliers:input.suppliers.map(s=>({...s,id:'OTHER'})),snapshots:input.snapshots.map(s=>({...s,supplier_id:'OTHER'})),mappings:input.mappings.map(m=>({...m,supplier_id:'OTHER'}))};
 for(const candidate of [altered,redirected]){const r=(await ingestMockPage(candidate)).results[0];assert.equal(r.status,'BLOCKED');assert.equal(r.reason,'IDEMPOTENCY_CONFLICT');assert.deepEqual(await input.ledger.read(),before);}
});
