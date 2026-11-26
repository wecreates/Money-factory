import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {safeRelativePath,verifyZipEntries} from '../zip-entries.mjs';
import {fileManifestDigest,planListingFiles} from '../file-plan.mjs';
import {syntheticZip} from './fixtures/zip.mjs';

const hash=value=>createHash('sha256').update(value).digest('hex');
const reviewed=entries=>Object.entries(entries).filter(([name])=>!name.endsWith('/')).map(([name,value])=>({path:name,sha256:hash(value)}));
const verify=entries=>verifyZipEntries(syntheticZip(entries),reviewed(entries));
const reserved=['CON','PRN','AUX','NUL',...['COM','LPT'].flatMap(prefix=>['1','2','3','4','5','6','7','8','9','\u00b9','\u00b2','\u00b3'].map(suffix=>prefix+suffix))];

for(const name of reserved){
  test(`reserved device ${name} fails in every path component`,()=>{
    for(const filename of [name,`${name}.txt`,`${name.toLowerCase()}.tar.gz`,`nested/${name}.txt`,`${name}/guide.pdf`]){
      assert.equal(safeRelativePath(filename),false,filename);
      assert.throws(()=>verify({[filename]:'synthetic'}),/unsafe/);
    }
    assert.throws(()=>verify({'guide.pdf':'synthetic',[`${name}/`]:''}),/unsafe/);
  });
}

const unsafe=['','/guide.pdf','../guide.pdf','folder/../guide.pdf','./guide.pdf','folder//guide.pdf','folder/','C:guide.pdf','C:/guide.pdf','folder\\guide.pdf','folder/guide.pdf:stream','folder<bad>/guide.pdf','folder>bad/guide.pdf','folder|bad/guide.pdf','folder?bad/guide.pdf','folder*bad/guide.pdf','folder"bad/guide.pdf','folder./guide.pdf','folder /guide.pdf','guide.pdf.','guide.pdf ','bad\0name.pdf','bad\u0001name.pdf','bad\u001fname.pdf','bad\ufffdname.pdf'];
for(const filename of unsafe){
  test(`unsafe relative path ${JSON.stringify(filename)} fails`,()=>{
    assert.equal(safeRelativePath(filename),false);
    assert.throws(()=>verifyZipEntries(syntheticZip({'guide.pdf':'synthetic'}),[{path:filename,sha256:hash('synthetic')}]));
  });
}

for(const name of ['COM\u00c2.txt','LPT\u00c2.txt','COM0.txt','LPT0.txt','COM10.txt','LPT10.txt','COM1-extra.txt','LPT2_extra.txt','CONSOLE.txt','NUL-data.txt','.hidden','Guides/Getting Started.txt','nested/deeper/Guide.pdf']){
  test(`valid path ${name} remains accepted`,()=>{
    assert.equal(safeRelativePath(name),true);
    assert.doesNotThrow(()=>verify({[name]:'synthetic'}));
  });
}

for(const pair of [
  ['Guide.pdf','guide.pdf'],
  ['nested/Guide.pdf','nested/guide.pdf'],
  ['Guides/one.pdf','guides/two.pdf'],
  ['guide','guide/child.pdf'],
  ['GUIDE','guide/nested/child.pdf'],
  ['\u03a3.txt','\u03c2.txt'],
  ['\u03c3','\u03c2/child.txt'],
  ['S.txt','\u017f.txt'],
  ['I.txt','\u0131.txt'],
  ['\u00df.txt','\u1e9e.txt'],
  ['\u00df','\u1e9e/child.txt']
]){
  for(const names of [pair,[...pair].reverse()]){
    test(`reviewed path collision ${names.join(' then ')} fails`,()=>{
      const entries=Object.fromEntries(names.map(name=>[name,'synthetic']));
      assert.throws(()=>verify(entries),/unsafe/);
    });
  }
}

for(const pair of [['guide','guide/'],['Guide','guide/'],['guide/','GUIDE/'],['\u00df','\u1e9e/']]){
  for(const names of [pair,[...pair].reverse()]){
    test(`archive file/directory collision ${names.join(' then ')} fails`,()=>{
      const entries=Object.fromEntries([...names.map(name=>[name,name.endsWith('/')?'':'synthetic']),['other.pdf','synthetic']]);
      assert.throws(()=>verify(entries),/unsafe/);
    });
  }
}

test('archive directories must agree with the spelling of implicit parent directories',()=>{
  for(const entries of [
    {'Guide/child.pdf':'synthetic','guide/':''},
    {'guide/':'','Guide/child.pdf':'synthetic'}
  ]) assert.throws(()=>verify(entries),/unsafe/);
});

test('valid explicit nested directories work before and after their children',()=>{
  const entries=[['Guides/',''],['Guides/Nested/',''],['Guides/one.pdf','one'],['Guides/Nested/two.pdf','two'],['Guides/three.pdf','three']];
  for(const ordered of [entries,[...entries].reverse()]){
    assert.doesNotThrow(()=>verify(Object.fromEntries(ordered)));
    const files=Object.fromEntries(ordered.filter(([name])=>!name.endsWith('/')));
    assert.doesNotThrow(()=>verify(files));
  }
});

test('deep valid nesting is checked without recursion or repeated full-path prefixes',()=>{
  const filename=`${'nested/'.repeat(4000)}guide.pdf`;
  assert.doesNotThrow(()=>verify({[filename]:'synthetic'}));
});

test('unsafe manifest directory fails before filesystem lookup',async()=>{
  for(const filename of ['CON/product.pdf','nested./product.pdf','nested /product.pdf','bad:name/product.pdf']){
    const manifest={schema_version:1,listing_id:'4535911896',shop_id:'43299966',type:'download',files:[{path:filename,sha256:hash('synthetic')}]};
    manifest.qa={status:'PASS',review_id:'synthetic-only',reviewed_manifest_sha256:fileManifestDigest(manifest)};
    await assert.rejects(planListingFiles({root:'/synthetic-path-that-does-not-exist',manifest,listingId:manifest.listing_id,shopId:manifest.shop_id}),/safe relative path/);
  }
});

test('CLI rejects colliding reviewed ZIP paths before OAuth or upload',async t=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'etsy-zip-collision-'));
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  const workbook='Small-Business-Bookkeeping-Dashboard.xlsx';
  const entries={[workbook]:'synthetic workbook','Guide.pdf':'one','guide.pdf':'two'};
  const bytes=syntheticZip(entries);
  await fs.writeFile(path.join(root,'product.pdf'),'synthetic PDF');
  await fs.writeFile(path.join(root,'bundle.zip'),bytes);
  const manifest={schema_version:1,listing_id:'4535911896',shop_id:'43299966',type:'download',files:[{path:'product.pdf',sha256:hash('synthetic PDF')},{path:'bundle.zip',sha256:hash(bytes),archive_entries:reviewed(entries)}]};
  manifest.qa={status:'PASS',review_id:'synthetic-only',reviewed_manifest_sha256:fileManifestDigest(manifest)};
  const manifestPath=path.join(root,'manifest.json');
  await fs.writeFile(manifestPath,JSON.stringify(manifest));
  const guard=path.join(root,'guard.mjs');
  await fs.writeFile(guard,"globalThis.fetch=()=>{throw new Error('NETWORK_CALL_FORBIDDEN')};\n");
  const cli=fileURLToPath(new URL('../cli.mjs',import.meta.url));
  for(const action of ['plan-files','files']){
    const result=spawnSync(process.execPath,['--import',pathToFileURL(guard).href,cli,action,manifest.listing_id],{encoding:'utf8',env:{ETSY_PRODUCT_ROOT:root,ETSY_FILE_MANIFEST:manifestPath}});
    assert.notEqual(result.status,0);
    assert.match(result.stderr,/unsafe/);
    assert.doesNotMatch(result.stderr,/NETWORK_CALL_FORBIDDEN|Missing ETSY_/);
  }
});
