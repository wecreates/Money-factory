import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

async function runFixture(scenario){
  const temporary=await fs.mkdtemp(path.join(os.tmpdir(),'etsy-runner-regression-'));
  try{
    const sourceUrl=new URL('../src/run.mjs',import.meta.url);
    let source=await fs.readFile(sourceUrl,'utf8');
    // Only replace module resolution. The production runner's actual code runs.
    source=source.replace("from 'playwright'",`from ${JSON.stringify(new URL('./fixtures/playwright-double.mjs',import.meta.url).href)}`);
    source=source.replace(/from '(\.\/[^']+)'/g,(_,relative)=>`from ${JSON.stringify(new URL(relative,sourceUrl).href)}`);
    const runner=path.join(temporary,'runner.mjs'),taskFile=path.join(temporary,'task.json'),traceFile=path.join(temporary,'trace.txt');
    const product=path.join(temporary,'product.pdf');
    if(scenario!=='missing-file')await fs.writeFile(product,'synthetic fixture, not a buyer asset');
    await fs.writeFile(runner,source);
    await fs.writeFile(taskFile,JSON.stringify({id:'synthetic',type:'update_listing',listing_id:'123',patch:{type:'download',files:[product]}}));
    const result=spawnSync(process.execPath,[runner,taskFile],{
      encoding:'utf8',timeout:10000,
      env:{SystemRoot:process.env.SystemRoot,TEMP:os.tmpdir(),TMP:os.tmpdir(),ETSY_TEST_SCENARIO:scenario,ETSY_TEST_TRACE:traceFile},
    });
    assert.equal(result.error,undefined);
    result.trace=await fs.readFile(traceFile,'utf8').catch(()=> '');
    return result;
  }finally{await fs.rm(temporary,{recursive:true,force:true});}
}

for(const scenario of ['missing-file','missing-digital-input','missing-save','missing-confirmation','stale-confirmation']){
  test(`blocks ${scenario} instead of reporting success`,async()=>{
    const result=await runFixture(scenario);
    assert.notEqual(result.status,0,`runner falsely passed: ${result.stdout}`);
    assert.doesNotMatch(result.stdout,/"success": true/);
    if(scenario==='missing-file')assert.equal(result.trace,'','invalid local assets must not launch a browser');
    if(['missing-file','missing-digital-input','missing-save','stale-confirmation'].includes(scenario))assert.doesNotMatch(result.trace,/save/);
    if(scenario==='missing-confirmation')assert.match(result.stdout,/reconcile listing before retrying/);
  });
}
test('reports success only after requested file upload and fresh save confirmation',async()=>{
  const result=await runFixture('success');
  assert.equal(result.status,0,result.stderr+result.stdout);
  assert.match(result.stdout,/"success": true/);
  assert.equal(result.trace,'launch\nupload\nsave\n');
});
