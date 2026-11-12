import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {integrationSmoke} from './integration-smoke.mjs';
const input=JSON.parse(await readFile(new URL('./sandbox-input.json',import.meta.url),'utf8'));
test('full mock adapter-policy-ledger flow retains three identities and partial line events',async()=>{
 const r=await integrationSmoke(input);assert.equal(Object.keys(r.state.orders).length,3);assert.equal(r.pages.length,3);
 const amazon=Object.values(r.state.orders).find(o=>o.marketplace==='amazon');assert.deepEqual([amazon.lines[0].shipped,amazon.lines[0].cancelled,amazon.lines[0].returned],[1,1,1]);
 assert.equal(Object.keys(amazon.packages).length,1);assert.equal(r.provider_validated,false);assert.equal(r.orders_placed,0);assert.equal(r.retry_example.action,'reconcile');
 assert.ok(r.inventory_previews.every(p=>p.dispatch_enabled===false));assert.equal(r.shipment_preview.dispatch_enabled,false);assert.equal(Object.values(r.state.inventory)[0],3);
});
