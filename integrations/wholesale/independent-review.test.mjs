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
test('review: all zero-ceiling cases block unrecorded orders but permit unchanged retry',async t=>{
 const input=await setup(t);await ingestMockPage(input);const before=await input.ledger.read();
 const variations=[{snapshots:[]},{snapshots:input.snapshots.map(s=>({...s,observed_at_ms:0}))},{snapshots:input.snapshots.map(s=>({...s,observed_at_ms:input.now+1}))},{catalog:input.catalog.map(r=>({...r,quote_expires_at_ms:input.now}))}];
 for(const changes of variations){
  assert.equal((await ingestMockPage({...input,...changes})).results[0].status,'SIMULATED_REPLAY');
  const result=(await ingestMockPage({...input,...changes,response:{orders:[{...raw,orderId:'NEW'}]}})).results[0];
  assert.equal(result.reason,'INSUFFICIENT_INVENTORY');assert.deepEqual(await input.ledger.read(),before);
 }
});
test('review: new order still needs channel, SKU, authorization, returns, packaging, margin',async t=>{
 const input=await setup(t);const before=await input.ledger.read();
 const variants=[{suppliers:input.suppliers.map(s=>({...s,authorization:{...s.authorization,channels:[]}}))},{suppliers:input.suppliers.map(s=>({...s,authorization:{...s.authorization,skus:[]}}))},{suppliers:input.suppliers.map(s=>({...s,authorization:{...s.authorization,expires_at_ms:input.now}}))},{suppliers:input.suppliers.map(s=>({...s,returns:{...s.returns,expires_at_ms:input.now}}))},{suppliers:input.suppliers.map(s=>({...s,neutral_packaging:false}))},{catalog:input.catalog.map(r=>({...r,cost_cents:r.price_cents}))}];
 for(const changes of variants){assert.equal((await ingestMockPage({...input,...changes})).results[0].status,'BLOCKED');assert.deepEqual(await input.ledger.read(),before);}
});
test('review: same supplier SKU is shared across accounts; other supplier cannot borrow stock',async t=>{
 const input=await setup(t);await ingestMockPage(input);
 const other={...input,account_id:'OTHER',mappings:input.mappings.map(m=>({...m,account_id:'OTHER'}))};
 assert.equal((await ingestMockPage(other)).results[0].status,'SIMULATED_RESERVED');
 assert.equal(Object.values((await input.ledger.read()).inventory)[0],4);
 const before=await input.ledger.read();
 const redirected={...input,response:{orders:[{...raw,orderId:'NEW'}]},catalog:input.catalog.map(r=>({...r,supplier_id:'OTHER'})),suppliers:input.suppliers.map(s=>({...s,id:'OTHER'})),snapshots:input.snapshots.map(s=>({...s,supplier_id:'OTHER'})),mappings:input.mappings.map(m=>({...m,supplier_id:'OTHER'}))};
 assert.equal((await ingestMockPage(redirected)).results[0].reason,'INSUFFICIENT_INVENTORY');assert.deepEqual(await input.ledger.read(),before);
});
test('review: price changes conflict and parallel depleted retries never mutate',async t=>{
 const input=await setup(t);await ingestMockPage(input);const before=await input.ledger.read();
 const depleted={...input,snapshots:input.snapshots.map(s=>({...s,quantity:0}))};
 const results=await Promise.all(Array.from({length:12},()=>ingestMockPage({...depleted,ledger:new SandboxLedger(input.ledger.path)})));
 assert.ok(results.every(r=>r.results[0].status==='SIMULATED_REPLAY'&&r.results[0].reservation_created===false));
 assert.equal((await ingestMockPage({...depleted,catalog:input.catalog.map(r=>({...r,price_cents:r.price_cents+1}))})).results[0].reason,'IDEMPOTENCY_CONFLICT');assert.deepEqual(await input.ledger.read(),before);
});