import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {syntheticZip} from './fixtures/zip.mjs';
import {fileManifestDigest,planListingFiles,uploadFilePlan,summarizeFilePlan,MAX_FILE_BYTES} from '../file-plan.mjs';
import {verifyZipEntries} from '../zip-entries.mjs';

const listingId='4535911896';
const workbook='Small-Business-Bookkeeping-Dashboard.xlsx';
const requiredFilenames=['product.pdf',workbook];
const workbookZip='Small-Business-Bookkeeping-Dashboard.zip';
const shopId='43299966';
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const cli=fileURLToPath(new URL('../cli.mjs',import.meta.url));

function review(manifest){
  manifest.qa={status:'PASS',review_id:'synthetic-fixture-only',reviewed_manifest_sha256:fileManifestDigest(manifest)};
  return manifest;
}
async function fixture(t,{extra=false}={}){
  const parent=await fs.mkdtemp(path.join(os.tmpdir(),'etsy-files-test-'));
  t.after(()=>fs.rm(parent,{recursive:true,force:true}));
  const root=path.join(parent,'products');
  await fs.mkdir(path.join(root,listingId),{recursive:true});
  const manifest={schema_version:1,listing_id:listingId,shop_id:shopId,type:'download',files:[]};
  for(const name of ['product.pdf',workbookZip,...(extra?['stickers.png','art.jpg']:[])]){
    // Deliberately synthetic bytes, never represented as a real sellable asset.
    const content=Buffer.from(`Synthetic test fixture for ${name}`);
    const bytes=name===workbookZip?syntheticZip({[workbook]:content}):content;
    const relative=`${listingId}/${name}`;
    await fs.writeFile(path.join(root,relative),bytes);
    manifest.files.push({path:relative,sha256:hash(bytes),...(name===workbookZip?{archive_entries:[{path:workbook,sha256:hash(content)}]}:{})});
  }
  review(manifest);
  return {parent,root,manifest,listingId,shopId,requiredFilenames};
}

test('valid exact manifest preserves all PDF/XLSX/PNG/JPG files, bytes and order',async t=>{
  const f=await fixture(t,{extra:true});
  const plan=await planListingFiles(f);
  assert.deepEqual(plan.files.map(x=>x.filename),['product.pdf',workbookZip,'stickers.png','art.jpg']);
  assert.deepEqual(plan.files.map(x=>x.rank),[1,2,3,4]);
  for(const file of plan.files) assert.equal(hash(file.bytes),file.sha256);
  const summary=summarizeFilePlan(plan);
  assert.ok(summary.files.every(x=>!('bytes' in x)));
  assert.equal(summary.content_quality_independently_verified,false);
  assert.equal(summary.publication_authorized,false);
  assert.equal(summary.live_listing_type_verified,false);
});

test('missing promised spreadsheet fails rather than silently uploading PDF only',async t=>{
  const f=await fixture(t); f.manifest.files.pop(); review(f.manifest);
  await assert.rejects(planListingFiles(f),/Missing required deliverable.*xlsx/);
});
test('missing product.pdf fails',async t=>{
  const f=await fixture(t); f.manifest.files.shift(); review(f.manifest);
  await assert.rejects(planListingFiles(f),/Missing required deliverable: product.pdf/);
});
test('manifest file absent on disk fails',async t=>{
  const f=await fixture(t); await fs.unlink(path.join(f.root,f.manifest.files[1].path));
  await assert.rejects(planListingFiles(f),/ENOENT/);
});
test('tampered delivered bytes fail',async t=>{
  const f=await fixture(t); await fs.writeFile(path.join(f.root,f.manifest.files[0].path),'changed');
  await assert.rejects(planListingFiles(f),/hash mismatch/);
});
test('empty deliverable fails even with matching hash',async t=>{
  const f=await fixture(t); await fs.writeFile(path.join(f.root,f.manifest.files[0].path),'');
  f.manifest.files[0].sha256=hash(''); review(f.manifest);
  await assert.rejects(planListingFiles(f),/nonempty regular file/);
});
test('listing ID substring is not an exact match',async t=>{
  const f=await fixture(t); f.manifest.listing_id=`1${listingId}`; review(f.manifest);
  await assert.rejects(planListingFiles(f),/listing ID does not match/);
});
test('physical manifest is blocked',async t=>{
  const f=await fixture(t); f.manifest.type='physical'; review(f.manifest);
  await assert.rejects(planListingFiles(f),/digital download/);
});
test('zero-file manifest is blocked',async t=>{
  const f=await fixture(t); f.manifest.files=[]; review(f.manifest);
  await assert.rejects(planListingFiles(f),/nonempty deliverable/);
});
test('missing QA, failed QA and missing review ID are blocked',async t=>{
  const f=await fixture(t);
  for(const qa of [undefined,{status:'FAIL'},{status:'PASS',review_id:'',reviewed_manifest_sha256:fileManifestDigest(f.manifest)}]){
    f.manifest.qa=qa;
    await assert.rejects(planListingFiles(f),/passing QA review/);
  }
});
test('review of older file list cannot authorize changed file order',async t=>{
  const f=await fixture(t); f.manifest.files.reverse();
  await assert.rejects(planListingFiles(f),/passing QA review/);
});
test('duplicate paths or upload basenames fail',async t=>{
  const f=await fixture(t); f.manifest.files.push({...f.manifest.files[0]}); review(f.manifest);
  await assert.rejects(planListingFiles(f),/Duplicate/);
  f.manifest.files.at(-1).path='other/PRODUCT.PDF'; review(f.manifest);
  await assert.rejects(planListingFiles(f),/Duplicate/);
});
test('absolute, traversal and ambiguous relative paths are blocked',async t=>{
  const f=await fixture(t);
  for(const bad of ['/tmp/product.pdf','../product.pdf','x/../product.pdf','x\\product.pdf','x//product.pdf','./product.pdf']){
    f.manifest.files[0].path=bad; review(f.manifest);
    await assert.rejects(planListingFiles(f),/safe relative path/);
  }
});
test('symlink escaping product root is blocked before reading bytes',async t=>{
  const f=await fixture(t); const file=path.join(f.root,f.manifest.files[0].path);
  const outside=path.join(f.parent,'outside.pdf'); await fs.writeFile(outside,'synthetic outside');
  await fs.unlink(file); await fs.symlink(outside,file);
  await assert.rejects(planListingFiles(f),/outside product root/);
});
test('directory masquerading as an artifact is blocked',async t=>{
  const f=await fixture(t); const file=path.join(f.root,f.manifest.files[0].path);
  await fs.unlink(file); await fs.mkdir(file);
  await assert.rejects(planListingFiles(f),/nonempty regular file/);
});
test('unsupported schema and invalid hash fail',async t=>{
  const f=await fixture(t); f.manifest.schema_version=2;
  await assert.rejects(planListingFiles(f),/Unsupported/);
  f.manifest.schema_version=1; f.manifest.files[0].sha256='not-a-hash'; review(f.manifest);
  await assert.rejects(planListingFiles(f),/SHA-256/);
});

test('upload sends every verified file exactly once then verifies returned IDs',async t=>{
  const plan=await planListingFiles(await fixture(t,{extra:true})); const uploaded=[];
  const result=await uploadFilePlan({plan,existingFiles:{count:0,results:[]},listing:{listing_id:listingId,shop_id:shopId,type:'download'},upload:async file=>{uploaded.push(file); return {listing_file_id:uploaded.length};},verify:async()=>({count:uploaded.length,results:uploaded.map((_,i)=>({listing_file_id:i+1}))})});
  assert.deepEqual(uploaded,plan.files);
  assert.deepEqual(result.uploaded_file_ids,['1','2','3','4']);
  assert.equal(result.attachment_readback_verified,true);
  assert.equal(result.buyer_download_verified,false);
});
test('physical or mismatched seller listing cannot receive uploads',async t=>{
  const plan=await planListingFiles(await fixture(t)); let calls=0;
  for(const listing of [{listing_id:listingId,type:'physical'},{listing_id:'999',type:'download'},undefined]){
    await assert.rejects(uploadFilePlan({plan,existingFiles:{count:0,results:[]},listing,upload:async()=>{calls++;},verify:async()=>{calls++;}}),/exact listing is a digital download/);
  }
  assert.equal(calls,0);
});
test('all plan hashes are rechecked before the first upload',async t=>{
  const plan=await planListingFiles(await fixture(t)); plan.files[1].bytes[0]^=1; let calls=0;
  await assert.rejects(uploadFilePlan({plan,existingFiles:{count:0,results:[]},listing:{listing_id:listingId,shop_id:shopId,type:'download'},upload:async()=>{calls++;}}),/no longer match/);
  assert.equal(calls,0);
});
test('uncertain upload response fails with no automatic retry',async t=>{
  const plan=await planListingFiles(await fixture(t)); let calls=0;
  await assert.rejects(uploadFilePlan({plan,existingFiles:{count:0,results:[]},listing:{listing_id:listingId,shop_id:shopId,type:'download'},upload:async()=>{calls++;return {};},verify:async()=>{throw Error('must not verify');}}),/missing listing_file_id/);
  assert.equal(calls,1);
});
test('duplicate provider file IDs fail',async t=>{
  const plan=await planListingFiles(await fixture(t));
  await assert.rejects(uploadFilePlan({plan,existingFiles:{count:0,results:[]},listing:{listing_id:listingId,shop_id:shopId,type:'download'},upload:async()=>({listing_file_id:1}),verify:async()=>{throw Error('must not verify');}}),/duplicate file IDs/);
});
test('missing uploaded file in read-back cannot count as success',async t=>{
  const plan=await planListingFiles(await fixture(t)); let id=0;
  await assert.rejects(uploadFilePlan({plan,existingFiles:{count:0,results:[]},listing:{listing_id:listingId,shop_id:shopId,type:'download'},upload:async()=>({listing_file_id:++id}),verify:async()=>({count:0,results:[]})}),/missing from seller read-back/);
});
test('malformed read-back cannot count as success',async t=>{
  const plan=await planListingFiles(await fixture(t)); let id=0;
  await assert.rejects(uploadFilePlan({plan,existingFiles:{count:0,results:[]},listing:{listing_id:listingId,shop_id:shopId,type:'download'},upload:async()=>({listing_file_id:++id}),verify:async()=>({})}),/Invalid listing-file verification/);
});

async function runCli(t,{action='plan-files',target=listingId,mutate}={}){
  const f=await fixture(t); if(mutate) await mutate(f);
  const manifestFile=path.join(f.parent,'manifest.json'); await fs.writeFile(manifestFile,JSON.stringify(f.manifest));
  const guard=path.join(f.parent,'no-network.mjs'); await fs.writeFile(guard,"globalThis.fetch=async()=>{throw new Error('NETWORK_CALL_FORBIDDEN')};\n");
  return spawnSync(process.execPath,['--import',pathToFileURL(guard).href,cli,action,target],{encoding:'utf8',env:{ETSY_PRODUCT_ROOT:f.root,ETSY_FILE_MANIFEST:manifestFile,ETSY_CLIENT_ID:'synthetic-only',ETSY_REFRESH_TOKEN:'synthetic-only',ETSY_API_KEY:'synthetic-only',ETSY_SHARED_SECRET:'synthetic-only'}});
}
test('CLI offline planning succeeds without OAuth or network',async t=>{
  const r=await runCli(t); assert.equal(r.status,0,r.stderr);
  const out=JSON.parse(r.stdout); assert.equal(out.listing_id,listingId); assert.equal(out.files.length,2);
});
test('CLI files fails missing supplement before OAuth or any network call',async t=>{
  const r=await runCli(t,{action:'files',mutate:async f=>{f.manifest.files.pop();review(f.manifest);}});
  assert.notEqual(r.status,0); assert.match(r.stderr,/Missing required deliverable/); assert.doesNotMatch(r.stderr,/NETWORK_CALL_FORBIDDEN/);
});
test('CLI requires one known listing and refuses batch all before network',async t=>{
  for(const target of ['all','999','453591']){
    const r=await runCli(t,{action:'files',target}); assert.notEqual(r.status,0);
    assert.match(r.stderr,/one exact listing target|exactly one known listing/); assert.doesNotMatch(r.stderr,/NETWORK_CALL_FORBIDDEN/);
  }
});

test('more than five planned attachments fails before reading files',async t=>{
  const f=await fixture(t); f.manifest.files=Array.from({length:6},(_,i)=>({path:`${i}.pdf`,sha256:hash('x')})); review(f.manifest);
  await assert.rejects(planListingFiles(f),/at most five/);
});
test('oversize file fails before it can be read or uploaded',async t=>{
  const f=await fixture(t); await fs.truncate(path.join(f.root,f.manifest.files[0].path),MAX_FILE_BYTES+1);
  await assert.rejects(planListingFiles(f),/20 MB/);
});
test('unsupported raw XLSX is rejected even with a passing review',async t=>{
  const f=await fixture(t); f.manifest.files[1]={path:`${listingId}/${workbook}`,sha256:hash('x')}; review(f.manifest);
  await assert.rejects(planListingFiles(f),/Unsupported Etsy direct file type/);
});
test('filename spaces and length above 70 characters fail',async t=>{
  const f=await fixture(t);
  for(const name of ['bad name.pdf',`${'a'.repeat(67)}.pdf`]){
    f.manifest.files[0].path=`${listingId}/${name}`; review(f.manifest);
    await assert.rejects(planListingFiles(f),/70 supported characters/);
  }
});
test('manifest is tied to the expected shop',async t=>{
  const f=await fixture(t); f.manifest.shop_id='999'; review(f.manifest);
  await assert.rejects(planListingFiles(f),/shop ID/);
});
test('mismatched seller shop stops before any upload',async t=>{
  const plan=await planListingFiles(await fixture(t)); let calls=0;
  await assert.rejects(uploadFilePlan({plan,listing:{listing_id:listingId,shop_id:'999',type:'download'},existingFiles:{count:0,results:[]},upload:async()=>calls++}),/exact listing/);
  assert.equal(calls,0);
});
test('occupied, incomplete, or ambiguous existing attachment states stop all uploads',async t=>{
  const plan=await planListingFiles(await fixture(t)); let calls=0;
  for(const existingFiles of [undefined,{results:[]},{count:1,results:[]},{count:0,results:[{listing_file_id:1}]},{count:1,results:[{listing_file_id:1}]}]){
    await assert.rejects(uploadFilePlan({plan,listing:{listing_id:listingId,shop_id:shopId,type:'download'},existingFiles,upload:async()=>calls++}),/seller reconciliation/);
  }
  assert.equal(calls,0);
});
test('ZIP contents are checked for the exact workbook hash, including deflate archives',()=>{
  const bytes=Buffer.from('synthetic workbook'); const expected=[{path:workbook,sha256:hash(bytes)}];
  assert.doesNotThrow(()=>verifyZipEntries(syntheticZip({[workbook]:bytes},{deflate:true}),expected));
  assert.throws(()=>verifyZipEntries(syntheticZip({[workbook]:'different'}),expected),/hash mismatch/);
});
test('ZIP cannot omit, rename, duplicate, or add unreviewed deliverables',()=>{
  const expected=[{path:workbook,sha256:hash('workbook')}];
  assert.throws(()=>verifyZipEntries(syntheticZip({'wrong.xlsx':'workbook'}),expected));
  assert.throws(()=>verifyZipEntries(syntheticZip({[workbook]:'workbook','unreviewed.txt':'extra'}),expected));
  assert.throws(()=>verifyZipEntries(syntheticZip({[workbook]:'workbook'}),[...expected,...expected]));
  assert.throws(()=>verifyZipEntries(syntheticZip({}),expected));
});
test('unsafe paths, corrupt ZIP headers and encrypted ZIPs are rejected',()=>{
  const expected=[{path:workbook,sha256:hash('workbook')}];
  assert.throws(()=>verifyZipEntries(syntheticZip({'../escape.xlsx':'workbook'}),[{path:'../escape.xlsx',sha256:hash('workbook')}]));
  const encrypted=syntheticZip({[workbook]:'workbook'}); encrypted.writeUInt16LE(1,6);
  assert.throws(()=>verifyZipEntries(encrypted,expected));
  const invalid=syntheticZip({[workbook]:'workbook'}); invalid[0]=0;
  assert.throws(()=>verifyZipEntries(invalid,expected));
  assert.throws(()=>verifyZipEntries(Buffer.from('not zip'),expected));
});
test('ZIP entries and archive hash are bound to the QA manifest',async t=>{
  const f=await fixture(t); f.manifest.files[1].archive_entries[0].sha256=hash('different');
  await assert.rejects(planListingFiles(f),/passing QA review/);
  review(f.manifest);
  await assert.rejects(planListingFiles(f),/ZIP entry hash mismatch/);
});

for(const phase of ['first upload','second upload','verification']){
  test(`${phase} exception preserves cause and known IDs and requires reconciliation`,async t=>{
    const plan=await planListingFiles(await fixture(t,{extra:true}));
    const cause=new Error('synthetic network/HTTP failure');
    cause.status=503;
    let uploads=0,verifications=0;
    await assert.rejects(uploadFilePlan({
      plan,listing:{listing_id:listingId,shop_id:shopId,type:'download'},existingFiles:{count:0,results:[]},
      upload:async()=>{
        uploads++;
        if((phase==='first upload' && uploads===1)||(phase==='second upload' && uploads===2)) throw cause;
        return {listing_file_id:uploads};
      },
      verify:async()=>{verifications++;throw cause;}
    }),error=>{
      const knownIds=phase==='first upload'?[]:phase==='second upload'?['1']:['1','2','3','4'];
      assert.equal(error.cause,cause);
      assert.equal(error.cause.status,503);
      assert.deepEqual(error.uploaded_file_ids,knownIds);
      assert.equal(error.seller_state_uncertain,true);
      assert.equal(error.reconciliation_required,true);
      assert.match(error.message,/seller state is uncertain/);
      assert.match(error.message,/reconcile seller state before retrying/);
      assert.ok(error.message.includes(JSON.stringify(knownIds)),'CLI-visible message must include known IDs');
      return true;
    });
    assert.equal(uploads,phase==='first upload'?1:phase==='second upload'?2:4,'must stop without retrying or attempting remaining uploads');
    assert.equal(verifications,phase==='verification'?1:0);
  });
}
