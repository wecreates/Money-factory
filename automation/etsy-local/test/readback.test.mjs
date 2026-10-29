import test from 'node:test';
import assert from 'node:assert/strict';
const {uploadAndSaveListing}=await import(process.env.ETSY_ACTIONS_MODULE||'../src/listing-actions.mjs');
import {applyListingMetadata,verifyListingMetadata,validateListingPatch} from '../src/listing-metadata.mjs';
import {createPage} from './fixtures/playwright-double.mjs';
const uploads={files:['/synthetic/product.pdf'],images:[]};
for(const scenario of ['stalled-upload','missing-attachment','blob-preview','unchanged-attachment','duplicate-attachment','rejected-upload','not-download-link','missing-attachment-group','drops-old-attachment']){
  test(`does not save ${scenario}`,async()=>{
    const trace=[];const page=createPage(scenario,x=>trace.push(x));
    await assert.rejects(uploadAndSaveListing(page,uploads,{timeout:3}));
    assert.ok(!trace.includes('save'));
  });
}
for(const scenario of ['lost-attachment','reverted-attachment','login-redirect','post-save-error','loses-old-on-reload']){
  test(`does not report success after ${scenario}`,async()=>{
    const trace=[];
    await assert.rejects(uploadAndSaveListing(createPage(scenario,x=>trace.push(x)),uploads,{timeout:3}),/reconcile listing before retrying/);
    assert.ok(trace.includes('save'));assert.ok(trace.includes('reload'));
  });
}
test('waits for delayed upload and reads back after reload',async()=>{
  const trace=[];
  const result=await uploadAndSaveListing(createPage('delayed-upload',x=>trace.push(x)),uploads,{timeout:100});
  assert.deepEqual(trace,['upload','save','reload']);assert.equal(result.bytesVerified,false);
});
test('rejects partial batch',async()=>{
  const trace=[];
  await assert.rejects(uploadAndSaveListing(createPage('partial-upload',x=>trace.push(x)),{images:[],files:['/synthetic/a.pdf','/synthetic/b.pdf']},{timeout:3}));
  assert.ok(!trace.includes('save'));
});
test('rejects duplicate requested names before uploading',async()=>{
  const trace=[];
  await assert.rejects(uploadAndSaveListing(createPage('success',x=>trace.push(x)),{images:[],files:['/a/product.pdf','/b/product.pdf']},{timeout:3}),/duplicate/);
  assert.deepEqual(trace,[]);
});
test('checks images independently of digital files',async()=>{
  const result=await uploadAndSaveListing(createPage(),{images:['/synthetic/cover.png'],files:['/synthetic/product.pdf']},{timeout:3});
  assert.deepEqual(result.attachments,[{kind:'images',name:'cover.png'},{kind:'files',name:'product.pdf'}]);
});
test('does not save incomplete image upload',async()=>{
  const trace=[];
  await assert.rejects(uploadAndSaveListing(createPage('missing-attachment',x=>trace.push(x)),{images:['/synthetic/cover.png'],files:[]},{timeout:3}));
  assert.ok(!trace.includes('save'));
});
const patch={title:'Example',description:'Full description',price:'4.50',type:'download',tags:['planner','printable']};
for(const scenario of ['missing-field','ambiguous-field','fill-fails','field-not-filled','missing-type','type-check-fails','type-not-selected','missing-tags','tag-remove-fails','tag-add-fails','tag-not-added']){
  test(`metadata rejects ${scenario}`,async()=>{await assert.rejects(applyListingMetadata(createPage(scenario),patch));});
}
for(const scenario of ['lost-field','lost-type','lost-tags']){
  test(`persisted metadata rejects ${scenario}`,async()=>{
    const page=createPage(scenario);await applyListingMetadata(page,patch);
    await assert.rejects(uploadAndSaveListing(page,uploads,{timeout:3,verifyMetadata:()=>verifyListingMetadata(page,patch)}),/reconcile/);
  });
}
test('metadata and attachments persist together',async()=>{
  const page=createPage();await applyListingMetadata(page,patch);
  const result=await uploadAndSaveListing(page,uploads,{timeout:3,verifyMetadata:()=>verifyListingMetadata(page,patch)});
  assert.equal(result.metadata,'requested fields matched after reload');
});
test('empty tags removes existing tags and verifies empty set',async()=>{const page=createPage();await applyListingMetadata(page,{tags:[]});await verifyListingMetadata(page,{tags:[]});});
for(const p of [{unknown:'ignored'},{title:''},{description:null},{price:0},{price:null},{type:'physical'},{tags:['duplicate','duplicate']},{tags:['a'.repeat(21)]}])test(`rejects invalid patch ${JSON.stringify(p)}`,()=>assert.throws(()=>validateListingPatch(p)));

test('preserves prior inventory alongside new attachments',async()=>{const result=await uploadAndSaveListing(createPage('preserves-old-attachment'),uploads,{timeout:3});assert.equal(result.bytesVerified,false);});
