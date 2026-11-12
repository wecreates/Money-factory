import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {SandboxLedger,retryPlan} from './ledger.mjs';
test('terminal cancellation and explicit completion cannot reset to active statuses',async t=>{
 const {ledger}=await fixture(t);await ledger.transact(ingest);
 await ledger.transact({type:'cancel',identity,evidence_id:'ALL-CANCELLED',lines:[{line_id:'1',quantity:3}]});
 for(const status of ['reserved','processing','on_hold'])await assert.rejects(()=>ledger.transact({type:'status',identity,status}),/TERMINAL_ORDER/);
 await ledger.transact({type:'status',identity,status:'completed'});
 const closed=await ledger.read();
 assert.deepEqual(await ledger.transact(ingest),closed);
 await assert.rejects(()=>ledger.transact({type:'status',identity,status:'reserved'}),/TERMINAL_ORDER/);
 await assert.rejects(()=>ledger.transact({type:'ship',identity,package_id:'late',carrier:'MOCK',tracking_number:'MOCK',tendered_at_ms:100,evidence_id:'MOCK',lines:[{line_id:'1',quantity:1}]},{now:100}),/OVER_SHIPMENT/);
 assert.deepEqual(await ledger.read(),closed);
});
const exec=promisify(execFile);
test('valid event IDs matching inherited object names survive restart and replay',async t=>{
 const {ledger,path}=await fixture(t);await ledger.transact(ingest);
 const commands=[
  {type:'ship',identity,package_id:'toString',carrier:'MOCK',tracking_number:'MOCK',tendered_at_ms:100,evidence_id:'MOCK',lines:[{line_id:'1',quantity:2}]},
  {type:'cancel',identity,evidence_id:'valueOf',lines:[{line_id:'1',quantity:1}]},
  {type:'return',identity,return_id:'hasOwnProperty',lines:[{line_id:'1',quantity:2}]},
  {type:'refund',identity,refund_id:'toLocaleString',amount_cents:3753}
 ];
 for(const command of commands){
  const receipt=await ledger.transactWithReceipt(command,{now:100});assert.equal(receipt.changed,true);
  const restarted=new SandboxLedger(path);
  const replay=await restarted.transactWithReceipt(command,{now:100});
  assert.equal(replay.changed,false);assert.deepEqual(replay.state,receipt.state);
 }
 const state=await ledger.read();assert.equal(Object.values(state.inventory)[0],8);
 assert.equal(Object.values(state.orders)[0].refunded_cents,3753);assert.equal(state.external_effects,0);
 await assert.rejects(()=>ledger.transact({...commands[3],amount_cents:1}),/IDEMPOTENCY_CONFLICT/);
 assert.deepEqual(await ledger.read(),state);
});
const identity={marketplace:'amazon',account_id:'account-fixture',order_id:'order-fixture'};
const ingest={type:'ingest',...identity,lines:[{line_id:'1',supplier_id:'supplier',sku:'fixture',quantity:3,unit_price_cents:1251}]};
async function fixture(t,quantity=10){const dir=await mkdtemp(join(tmpdir(),'wholesale-ledger-'));t.after(()=>rm(dir,{recursive:true,force:true}));const path=join(dir,'ledger.json');const ledger=new SandboxLedger(path);await ledger.initialize({inventory:[{supplier_id:'supplier',sku:'fixture',quantity}]});return {ledger,path};}
test('durable ingest identity and optimistic version protect reservation',async t=>{
 const {ledger,path}=await fixture(t);await ledger.transact(ingest,{expectedVersion:0});const a=await ledger.read();assert.equal(a.version,1);
 assert.deepEqual(await ledger.transact(ingest),a);
 await assert.rejects(()=>ledger.transact({...ingest,lines:[{...ingest.lines[0],quantity:2}]}),/IDEMPOTENCY/);
 await assert.rejects(()=>ledger.transact({type:'status',identity,status:'processing'},{expectedVersion:0}),/VERSION/);
 const b=await new SandboxLedger(path).transact({type:'status',identity,status:'processing'},{expectedVersion:1});assert.equal(b.version,2);
 await ledger.transact({...ingest,account_id:'other-account'});assert.equal(Object.keys((await ledger.read()).orders).length,2);
});
test('partial shipment, confirmed cancellation, returns and capped simulated refund',async t=>{
 const {ledger}=await fixture(t);await ledger.transact(ingest);
 const ship={type:'ship',identity,package_id:'p1',carrier:'UPS',tracking_number:'FIXTURE',evidence_id:'fixture-tender',tendered_at_ms:100,lines:[{line_id:'1',quantity:2}]};
 await ledger.transact(ship,{now:100});const before=await ledger.read();assert.deepEqual(await ledger.transact(ship,{now:100}),before);
 await assert.rejects(()=>ledger.transact({...ship,lines:[{line_id:'1',quantity:1}]}),/IDEMPOTENCY/);
 await assert.rejects(()=>ledger.transact({...ship,package_id:'p2'}),/OVER_SHIPMENT/);
 await assert.rejects(()=>ledger.transact({type:'cancel',identity,evidence_id:'cancel',lines:[{line_id:'1',quantity:2}]}),/OVER_CANCELLATION/);
 await ledger.transact({type:'cancel',identity,evidence_id:'cancel',lines:[{line_id:'1',quantity:1}]});
 assert.equal(Object.values((await ledger.read()).inventory)[0],8);
 await ledger.transact({type:'return',identity,return_id:'r1',lines:[{line_id:'1',quantity:1}]});
 await assert.rejects(()=>ledger.transact({type:'return',identity,return_id:'r2',lines:[{line_id:'1',quantity:2}]}),/OVER_RETURN/);
 const refund={type:'refund',identity,refund_id:'f1',amount_cents:2502};await ledger.transact(refund);const refunded=await ledger.read();assert.deepEqual(await ledger.transact(refund),refunded);
 await assert.rejects(()=>ledger.transact({...refund,refund_id:'f2',amount_cents:1}),/REFUND_CAP/);
 assert.equal(refunded.external_effects,0);assert.equal(refunded.verified_profit_cents,0);assert.equal(Object.values(refunded.inventory)[0],8);
});
test('invalid partial batch is atomic and event identifiers cannot pollute prototype',async t=>{
 const {ledger,path}=await fixture(t);await ledger.transact(ingest);const before=await readFile(path,'utf8');
 await assert.rejects(()=>ledger.transact({type:'cancel',identity,evidence_id:'cancel',lines:[{line_id:'1',quantity:1},{line_id:'missing',quantity:1}]}),/UNKNOWN_LINE/);
 assert.equal(await readFile(path,'utf8'),before);
 await assert.rejects(()=>ledger.transact({type:'refund',identity,refund_id:'__proto__',amount_cents:1}),/INVALID_ID/);
});
test('independent Node processes contend safely for one shared stock pool',async t=>{
 const {ledger,path}=await fixture(t,3);
 const url=new URL('./ledger.mjs',import.meta.url).href;
 const run=n=>exec(process.execPath,['--input-type=module','-e',`import {SandboxLedger} from ${JSON.stringify(url)}; const l=new SandboxLedger(${JSON.stringify(path)}); try {await l.transact(${JSON.stringify({...ingest,order_id:'order-'+n})}); console.log('reserved');}catch(e){console.log(e.message);}`]);
 const results=await Promise.all([run(1),run(2),run(3)]);assert.equal(results.filter(r=>r.stdout.trim()==='reserved').length,1);assert.equal(results.filter(r=>r.stdout.includes('INSUFFICIENT_INVENTORY')).length,2);
 const state=await ledger.read();assert.equal(Object.keys(state.orders).length,1);assert.equal(Object.values(state.inventory)[0],0);
});
test('leftover writer lock requires reconciliation, never automatic stealing',async t=>{
 const {path}=await fixture(t);await writeFile(path+'.lock','fixture interrupted writer');const ledger=new SandboxLedger(path,{lockTimeoutMs:20});await assert.rejects(()=>ledger.transact(ingest),/LOCK_BUSY_RECONCILE/);
});
test('fresh inventory ceiling is enforced under lock across independent processes',async t=>{
 const {ledger,path}=await fixture(t,8);const url=new URL('./ledger.mjs',import.meta.url).href;
 const current={...ingest,lines:[{...ingest.lines[0],quantity:2}],inventory_ceiling:[{supplier_id:'supplier',sku:'fixture',quantity:2}]};
 const run=n=>exec(process.execPath,['--input-type=module','-e',`import {SandboxLedger} from ${JSON.stringify(url)}; try {await new SandboxLedger(${JSON.stringify(path)}).transact(${JSON.stringify({...current,order_id:'ceiling-'+n})});console.log('reserved');}catch(e){console.log(e.message);}`]);
 const results=await Promise.all([run(1),run(2)]);assert.equal(results.filter(r=>r.stdout.trim()==='reserved').length,1);assert.equal(results.filter(r=>r.stdout.includes('INSUFFICIENT_INVENTORY')).length,1);
 const state=await ledger.read();assert.equal(Object.values(state.inventory)[0],0);assert.equal(Object.keys(state.orders).length,1);
 const saved=Object.values(state.orders)[0];assert.deepEqual(await ledger.transact({...current,order_id:saved.order_id,inventory_ceiling:[]}),state);
});
test('inventory ceiling rejects missing duplicate and invalid quantities atomically',async t=>{
 const {ledger}=await fixture(t,8);const state=await ledger.read(),entry={supplier_id:'supplier',sku:'fixture',quantity:2};
 for(const [ceiling,error] of [[[],/MISSING_INVENTORY_CEILING/],[[entry,entry],/DUPLICATE_INVENTORY_CEILING/],[[{...entry,quantity:-1}],/INVALID_INTEGER/]]){
  await assert.rejects(()=>ledger.transact({...ingest,inventory_ceiling:ceiling}),error);assert.deepEqual(await ledger.read(),state);
 }
});
test('retry planner reconciles ambiguous mutations and bounds read retries',()=>{
 assert.throws(()=>retryPlan({status:500}),/INVALID_METHOD/);
 assert.equal(retryPlan({method:'POST',status:500}).action,'reconcile');
 assert.equal(retryPlan({method:'POST'}).action,'reconcile');
 assert.equal(retryPlan({method:'GET',status:401}).action,'stop');
 assert.equal(retryPlan({method:'POST',ambiguous:true,status:504}).action,'reconcile');
 assert.equal(retryPlan({method:'GET',status:503,attempt:2}).delay_ms,4000);
 assert.equal(retryPlan({method:'GET',status:503,attempt:3}).action,'stop');
 assert.equal(retryPlan({method:'GET',status:429,retry_after_seconds:30}).delay_ms,30000);
 assert.equal(retryPlan({method:'GET',status:429,retry_after_seconds:301}).action,'defer');
 assert.equal(retryPlan({method:'POST',status:429,retry_after_seconds:1}).automatic_retry,false);
});
test('local status completion requires all units fulfilled and holds block new shipments',async t=>{
 const {ledger}=await fixture(t);await ledger.transact(ingest);
 await assert.rejects(()=>ledger.transact({type:'status',identity,status:'completed'}),/ORDER_NOT_FULFILLED/);
 await ledger.transact({type:'status',identity,status:'on_hold'});
 const ship={type:'ship',identity,package_id:'p1',carrier:'UPS',tracking_number:'FIXTURE',evidence_id:'fixture-tender',tendered_at_ms:100,lines:[{line_id:'1',quantity:2}]};
 await assert.rejects(()=>ledger.transact(ship),/ORDER_ON_HOLD/);
 await ledger.transact({type:'status',identity,status:'processing'});await ledger.transact(ship);
 await assert.rejects(()=>ledger.transact({type:'status',identity,status:'completed'}),/ORDER_NOT_FULFILLED/);
 await ledger.transact({type:'cancel',identity,evidence_id:'cancel',lines:[{line_id:'1',quantity:1}]});
 const state=await ledger.transact({type:'status',identity,status:'completed'});assert.equal(Object.values(state.orders)[0].status,'completed');
});
