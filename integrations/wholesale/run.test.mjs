import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,mkdtempSync,rmSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {run} from './run.mjs';
const fixture=JSON.parse(readFileSync(new URL('./sandbox-input.json',import.meta.url),'utf8'));
test('complete three-marketplace dry run keeps all external counters zero',()=>{
 const r=run(fixture);assert.equal(r.state.orders.length,3);
 assert.deepEqual(r.state.orders.map(o=>o.state),['refunded','cancelled','accepted']);
 assert.equal(r.state.inventory[0].available,4);assert.equal(r.estimates[0].projected_profit_cents,820);
 assert.equal(r.orders_placed,0);assert.equal(r.verified_revenue_cents,0);assert.equal(r.financial_transactions,0);
 assert.equal(r.publication_enabled,false);assert.ok(r.production_blockers.length);
});
test('runner rejects live execution and unsupported actions',()=>{
 assert.throws(()=>run({...fixture,mode:'live'}),/sandbox/);
 assert.throws(()=>run({...fixture,commands:[{action:'publish'}]}),/Unsupported/);
 assert.throws(()=>run({...fixture,now:undefined}),/clock/);
});
test('actual CLI writes report, protects existing output, and imports synthetic CSV',()=>{
 const dir=mkdtempSync(join(tmpdir(),'wholesale-test-'));
 try {
  const output=join(dir,'report.json');
  const runner=fileURLToPath(new URL('./run.mjs',import.meta.url));
  const source=fileURLToPath(new URL('./sandbox-input.json',import.meta.url));
  const call=()=>spawnSync(process.execPath,[runner,source,output],{encoding:'utf8'});
  assert.equal(call().status,0);const before=readFileSync(output,'utf8');assert.equal(call().status,1);assert.equal(readFileSync(output,'utf8'),before);
  const imported=join(dir,'catalog.json');
  const csv=spawnSync(process.execPath,[fileURLToPath(new URL('./catalog-csv.mjs',import.meta.url)),fileURLToPath(new URL('./synthetic-catalog.csv',import.meta.url)),imported],{encoding:'utf8'});
  assert.equal(csv.status,0,csv.stderr);assert.ok(existsSync(imported));assert.deepEqual(JSON.parse(readFileSync(imported,'utf8')),fixture.catalog);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
