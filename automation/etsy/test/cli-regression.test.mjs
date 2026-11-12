import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {syntheticZip} from './fixtures/zip.mjs';
import {fileManifestDigest} from '../file-plan.mjs';


const cli=process.env.ETSY_REGRESSION_CLI || fileURLToPath(new URL('../cli.mjs',import.meta.url));
const listingId='4535911896';
const sha=b=>createHash('sha256').update(b).digest('hex');
async function run(t,{missingWorkbook=false,extra=false,emptyVerify=false}={}){
  const tmp=await fs.mkdtemp(path.join(os.tmpdir(),'etsy-regression-'));
  t.after(()=>fs.rm(tmp,{recursive:true,force:true}));
  const root=path.join(tmp,'products'); await fs.mkdir(path.join(root,listingId),{recursive:true});
  const names=['product.pdf','Small-Business-Bookkeeping-Dashboard.zip',...(extra?['bonus.png']:[])];
  const manifest={schema_version:1,listing_id:listingId,shop_id:'43299966',type:'download',files:[]};
  for(const name of names){
    const relative=`${listingId}/${name}`; const content=Buffer.from(`synthetic fixture ${name}`); const bytes=name.endsWith('.zip')?syntheticZip({'Small-Business-Bookkeeping-Dashboard.xlsx':content}):content;
    manifest.files.push({path:relative,sha256:sha(bytes),...(name.endsWith('.zip')?{archive_entries:[{path:'Small-Business-Bookkeeping-Dashboard.xlsx',sha256:sha(content)}]}:{})});
    if(!(missingWorkbook&&name.endsWith('.zip'))) await fs.writeFile(path.join(root,relative),bytes);
  }
  manifest.qa={status:'PASS',review_id:'synthetic-regression-only',reviewed_manifest_sha256:fileManifestDigest(manifest)};
  const manifestPath=path.join(tmp,'manifest.json'); await fs.writeFile(manifestPath,JSON.stringify(manifest));
  const capture=path.join(tmp,'calls.json');
  const guard=path.join(tmp,'mock-fetch.mjs');
  await fs.writeFile(guard,`
import fs from 'node:fs';
const calls=[]; const uploaded=[];
globalThis.fetch=async(url,options={})=>{
  calls.push({url,method:options.method||'GET'});
  const response=body=>{fs.writeFileSync(${JSON.stringify(capture)},JSON.stringify({calls,uploaded}));return new Response(JSON.stringify(body),{status:200,headers:{'content-type':'application/json'}});};
  if(url==='https://api.etsy.com/v3/public/oauth/token') return response({access_token:'synthetic-only'});
  if(url==='https://api.etsy.com/v3/application/listings/${listingId}') return response({listing_id:${listingId},shop_id:43299966,type:'download'});
  if(url==='https://api.etsy.com/v3/application/shops/43299966/listings/${listingId}/files'){
    if(options.method==='POST') {uploaded.push({listing_file_id:uploaded.length+1,filename:options.body.get('name')});return response(uploaded.at(-1));}
    return response({count:${emptyVerify?'0':'uploaded.length'},results:${emptyVerify?'[]':'uploaded'}});
  }
  throw new Error('Unexpected URL blocked by test fetch: '+url);
};
`);
  const result=spawnSync(process.execPath,['--import',pathToFileURL(guard).href,cli,'files',listingId],{encoding:'utf8',env:{ETSY_PRODUCT_ROOT:root,ETSY_FILE_MANIFEST:manifestPath,ETSY_CLIENT_ID:'synthetic-only',ETSY_REFRESH_TOKEN:'synthetic-only',ETSY_API_KEY:'synthetic-only',ETSY_SHARED_SECRET:'synthetic-only'}});
  let calls={calls:[],uploaded:[]}; try{calls=JSON.parse(await fs.readFile(capture,'utf8'));}catch{}
  return {...result,...calls};
}
test('missing promised workbook fails before any mocked provider call',async t=>{
  const result=await run(t,{missingWorkbook:true});
  assert.notEqual(result.status,0,'Legacy CLI silently uploaded only product.pdf');
  assert.equal(result.calls.length,0,'Preflight must precede OAuth');
});
test('every reviewed asset reaches the upload adapter, including bonus PNG',async t=>{
  const result=await run(t,{extra:true});
  assert.equal(result.status,0,result.stderr);
  assert.deepEqual(result.uploaded.map(x=>x.filename),['product.pdf','Small-Business-Bookkeeping-Dashboard.zip','bonus.png']);
});
test('empty seller file read-back cannot be reported as successful delivery attachment',async t=>{
  const result=await run(t,{emptyVerify:true});
  assert.notEqual(result.status,0,'Legacy CLI accepted empty verification results');
  assert.match(result.stderr,/missing from seller read-back/);
});
