import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {updateShop,createSection,validateShopPatch,validateSectionTitle} from '../src/shop-actions.mjs';
import {createPage} from './fixtures/shop-double.mjs';
const patch={title:'New shop title',announcement:''};
for(const p of [null,[],{},'text',{unknown:'x'},{title:''},{title:7},{announcement:null}])test(`rejects invalid shop patch ${JSON.stringify(p)}`,()=>assert.throws(()=>validateShopPatch(p)));
for(const title of ['',null,7,'  '])test(`rejects invalid section title ${JSON.stringify(title)}`,()=>assert.throws(()=>validateSectionTitle(title)));
for(const scenario of ['missing-Shop title','ambiguous-Shop title','hidden-Shop title','missing-Announcement','fill-fails','ignored-fill','missing-save','ambiguous-save','disabled-save','hidden-save','stale-confirmation','alert','busy']){
  test(`shop does not save ${scenario}`,async()=>{const trace=[];await assert.rejects(updateShop(createPage(scenario,e=>trace.push(e)),patch));assert.ok(!trace.includes('save'));});
}
for(const scenario of ['missing-Manage sections','ambiguous-Manage sections','click-fails-Manage sections','missing-dialog','missing-list','ambiguous-list','duplicate-inventory','already-exists','missing-add','click-fails-add','missing-Section name','ambiguous-Section name','fill-fails','ignored-fill','missing-save','ambiguous-save','disabled-save','stale-confirmation','alert','busy']){
  test(`section does not save ${scenario}`,async()=>{const trace=[];await assert.rejects(createSection(createPage(scenario,e=>trace.push(e)),'New'));assert.ok(!trace.includes('save'));});
}
for(const [type,action,scenarios] of [
  ['shop',p=>updateShop(p,patch),['missing-confirmation','ambiguous-status','lost-field','lost-announcement','login-redirect','post-save-alert','click-fails-save']],
  ['section',p=>createSection(p,'New'),['missing-confirmation','ambiguous-status','lost-section','lost-prior-section','extra-section','login-redirect','post-save-alert','click-fails-save']],
])for(const scenario of scenarios)test(`${type} rejects unconfirmed ${scenario}`,async()=>{const trace=[];await assert.rejects(action(createPage(scenario,e=>trace.push(e))),/reconcile shop before retrying/);assert.ok(trace.filter(e=>e==='save').length<=1);});
test('shop verifies a cleared announcement after reload',async()=>{const trace=[];const r=await updateShop(createPage('success',e=>trace.push(e)),patch);assert.deepEqual(r.fields,['title','announcement']);assert.deepEqual(trace,['fill','fill','save','reload']);});
test('section verifies new and prior inventory after reload',async()=>{const trace=[];const r=await createSection(createPage('success',e=>trace.push(e)),'New');assert.equal(r.title,'New');assert.deepEqual(trace,['manage','add','fill','save','reload','manage']);});
async function runFixture(task,scenario){
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'etsy-shop-regression-'));
  try{
    const sourceUrl=new URL('../src/run.mjs',import.meta.url);
    let source=await fs.readFile(sourceUrl,'utf8');
    source=source.replace("from 'playwright'",`from ${JSON.stringify(new URL('./fixtures/shop-double.mjs',import.meta.url).href)}`);
    source=source.replace(/from '(\.\/[^']+)'/g,(_,rel)=>`from ${JSON.stringify(new URL(rel,sourceUrl).href)}`);
    const runner=path.join(dir,'runner.mjs'),taskFile=path.join(dir,'task.json'),traceFile=path.join(dir,'trace');
    await fs.writeFile(runner,source);await fs.writeFile(taskFile,JSON.stringify({id:'synthetic',...task}));
    const result=spawnSync(process.execPath,[runner,taskFile],{encoding:'utf8',timeout:10000,env:{SystemRoot:process.env.SystemRoot,TEMP:os.tmpdir(),TMP:os.tmpdir(),ETSY_TEST_SCENARIO:scenario,ETSY_TEST_TRACE:traceFile}});
    assert.equal(result.error,undefined);result.trace=await fs.readFile(traceFile,'utf8').catch(()=>'');return result;
  }finally{await fs.rm(dir,{recursive:true,force:true});}
}
for(const task of [{type:'update_shop',patch},{type:'create_section',title:'New'}]){
  for(const scenario of ['missing-save','missing-confirmation','login-redirect','success'])test(`runner ${task.type} ${scenario}`,async()=>{
    const r=await runFixture(task,scenario);
    if(scenario==='success'){assert.equal(r.status,0,r.stderr+r.stdout);assert.equal(JSON.parse(r.stdout).verification,task.type==='update_shop'?'SHOP_READBACK_CONFIRMED':'SECTION_READBACK_CONFIRMED');assert.match(r.trace,/save\nreload/);}
    else{assert.equal(r.status,1);assert.equal(JSON.parse(r.stdout).success,false);}
    assert.match(r.trace,/close\n$/);
  });
}
for(const task of [{type:'update_shop',patch:{}},{type:'update_shop',patch:{unknown:'x'}},{type:'create_section',title:''},{type:'create_section',title:42}])test(`runner rejects before launch ${JSON.stringify(task)}`,async()=>{const r=await runFixture(task,'success');assert.notEqual(r.status,0);assert.equal(r.trace,'');assert.doesNotMatch(r.stdout,/"success": true/);});
test('shop resolves all requested fields before editing any',async()=>{const trace=[];await assert.rejects(updateShop(createPage('missing-Announcement',e=>trace.push(e)),patch));assert.deepEqual(trace,[]);});
test('unknown section inventory stops before creating anything',async()=>{const trace=[];await assert.rejects(createSection(createPage('missing-list',e=>trace.push(e)),'New'));assert.deepEqual(trace,['manage']);});
