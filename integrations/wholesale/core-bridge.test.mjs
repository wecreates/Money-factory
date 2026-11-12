import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {join} from 'node:path';
import {WholesaleSandboxProvider,installWholesaleSandbox} from './core-bridge.mjs';
const input=JSON.parse(readFileSync(new URL('./sandbox-input.json',import.meta.url),'utf8'));
test('sandbox provider guards keys, mutations, concurrent duplicate calls and webhooks',async()=>{
 const p=new WholesaleSandboxProvider();const h=await p.health();assert.equal(h.ok,false);assert.equal(h.sandbox_ready,true);
 await assert.rejects(p.execute('simulate',input),/KEY_REQUIRED/);
 await assert.rejects(p.execute('publish',input,{idempotencyKey:'x'}),/DISABLED/);
 const [a,b]=await Promise.all([p.execute('simulate',input,{idempotencyKey:'a'}),p.execute('simulate',input,{idempotencyKey:'a'})]);assert.deepEqual(a,b);
 a.data.state.orders[0].state='tamper';assert.notEqual((await p.execute('simulate',input,{idempotencyKey:'a'})).data.state.orders[0].state,'tamper');
 await assert.rejects(p.execute('simulate',{...input,commands:[]},{idempotencyKey:'a'}),/CONFLICT/);
 assert.throws(()=>p.normalizeWebhook({type:'revenue_verified'}),/WEBHOOKS_DISABLED/);
});

test('verified recovered core registry and worker accept dedicated simulation without financial state changes', {skip:!process.env.MONEY_FACTORY_CORE_ROOT},async()=>{
 const root=process.env.MONEY_FACTORY_CORE_ROOT;
 const manifest=readFileSync(join(root,'SOURCE_SHA256SUMS.txt'),'utf8');let verified=0;
 for(const line of manifest.split(/\r?\n/)){const match=line.match(/^([a-f0-9]{64})  (src\/.+)$/);if(!match)continue;
   assert.equal(createHash('sha256').update(readFileSync(join(root,match[2]))).digest('hex'),match[1],`Core source changed: ${match[2]}`);verified++;
 }
 assert.ok(verified>30,'Full core source manifest must be verified before execution');
 const require=createRequire(join(root,'package.json'));
 const {ProviderRegistry,LocalProviderAdapter}=require('./src/providers.js');
 const {createHandlers}=require('./src/runtime.js');
 const {initialState}=require('./src/store.js');
 const {businessPnl}=require('./src/finance.js');
 const {transitionOrder}=require('./src/autonomy.js');
 const {enqueueJob,WorkerPool}=require('./src/queue.js');
 const state=initialState();state.businesses.demo={id:'demo'};
 let writes=0;const store={read:async()=>structuredClone(state),update:async()=>{writes++;throw Error('Unexpected core state mutation');}};
 const providers=new ProviderRegistry([new LocalProviderAdapter()]);
 const original=createHandlers({store,providers});
 const handlers=installWholesaleSandbox({providers,handlers:original});
 assert.equal(handlers.provider_action,original.provider_action);
 assert.equal((await providers.health())['wholesale-sandbox'].ok,false);
 const result=await handlers.wholesale_sandbox({idempotencyKey:'core-test',payload:{input}});
 assert.equal(result.dryRun,true);assert.equal(result.data.state.orders.length,3);assert.equal(writes,0);assert.deepEqual(state.orders,{});assert.equal(businessPnl(state,'demo').netProfit,0);
 await assert.rejects(handlers.provider_action({payload:{provider:'wholesale-sandbox',action:'simulate',input},idempotencyKey:'bad-route'}),e=>e.code==='LIVE_DISPATCH_DISABLED');
 assert.throws(()=>installWholesaleSandbox({providers,handlers:original}),/ALREADY_REGISTERED/);
 // Existing order proof gate remains enforced; do not call createOrder on simulations (it labels orders paid).
 const isolated={orders:{sample:{id:'sample',status:'paid',history:[]}}};
 assert.throws(()=>transitionOrder(isolated,'sample','supplier_confirmed'),/proof/);
 transitionOrder(isolated,'sample','supplier_confirmed',{proof:'SYNTHETIC'});
 assert.throws(()=>transitionOrder(isolated,'sample','shipped'),/tracking/);
 assert.deepEqual(state.events,[]);
 const queuedState=initialState();queuedState.businesses.demo={id:'demo'};
 const queueStore={read:async()=>structuredClone(queuedState),update:async fn=>structuredClone(await fn(queuedState))};
 const queueProviders=new ProviderRegistry([new LocalProviderAdapter()]);
 const queueHandlers=installWholesaleSandbox({providers:queueProviders,handlers:createHandlers({store:queueStore,providers:queueProviders})});
 const job=await enqueueJob(queueStore,{businessId:'demo',type:'wholesale_sandbox',idempotencyKey:'queued-simulation',payload:{input}});
 const worker=new WorkerPool({store:queueStore,handlers:queueHandlers,workerId:'test-worker',concurrency:1});
 assert.equal(await worker.runOnce(),1);
 assert.equal(queuedState.jobs[job.id].status,'done');assert.equal(queuedState.jobs[job.id].result.dryRun,true);
 assert.equal(await worker.runOnce(),0);assert.deepEqual(queuedState.orders,{});assert.deepEqual(queuedState.events,[]);assert.equal(businessPnl(queuedState,'demo').netProfit,0);
});
