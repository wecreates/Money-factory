import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {evaluateVerification,runVerification} from '../verify.mjs';

const watch=id=>({id,targetUrl:'https://example.com/',status:'active'});
const state=(ids,time)=>Object.fromEntries(ids.map(id=>[id,{status:'active',targetUrl:'https://example.com/',last_checked_at:time,last_status:200,last_error:null}]));
const cycle=(ids,time)=>({ok:true,results:ids.map(id=>({id,checked:true,status:200,last_checked_at:time}))});
function fixture(){
 const ids=['cyzor-website','money-factory-repository'];
 return [ids.map(watch),state(ids,1),state(ids,2),state(ids,3),cycle(ids,2),cycle(ids,3)];
}
test('configured current watch IDs pass without removed smoke ID',()=>{
 const result=evaluateVerification(...fixture());
 assert.equal(result.pass,true);assert.equal(result.active_watch_count,2);
});
test('empty active set, missing checks, skipped checks, failure and stale times cannot pass',()=>{
 const mutations=[a=>a[0]=[],a=>a[0].forEach(w=>w.status='paused'),
  a=>a[5].results.pop(),a=>a[4].results[0].checked=false,
  a=>a[5].ok=false,a=>a[3]['cyzor-website'].last_error='timeout',
  a=>a[3]['cyzor-website'].last_checked_at=2,
  a=>a[2]['cyzor-website'].last_checked_at=NaN,
  a=>a[4].results[0].status=502,a=>a[3]['cyzor-website'].targetUrl='https://stale.example/'];
 for(const mutate of mutations){const args=fixture();mutate(args);assert.equal(evaluateVerification(...args).pass,false);}
});
test('duplicate active IDs reject ambiguous evidence',()=>{
 const args=fixture();args[0].push(args[0][0]);assert.throws(()=>evaluateVerification(...args),/duplicate/);
});
test('two real local-fixture HTTP cycles retain current-ID health and timestamps',async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-verification-'));
 let status=200;
 const server=http.createServer((req,res)=>{res.writeHead(status);res.end('synthetic local verification fixture');});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const options={watchesPath:path.join(dir,'watches.json'),statePath:path.join(dir,'state.json'),eventsPath:path.join(dir,'events.json'),reportPath:path.join(dir,'report.json')};
 try{
  await fs.writeFile(options.watchesPath,JSON.stringify([{...watch('current-fixture'),targetUrl:`http://127.0.0.1:${server.address().port}`} ]));
  const report=await runVerification(options);assert.equal(report.pass,true);assert.equal(report.watches[0].id,'current-fixture');
  status=502;
  const failed=await runVerification(options);assert.equal(failed.pass,false);assert.equal(failed.watches[0].first_cycle_healthy,false);
  assert.equal(JSON.parse(await fs.readFile(options.reportPath,'utf8')).pass,false);
 }finally{server.closeAllConnections();server.close();await fs.rm(dir,{recursive:true,force:true});}
});


test('malformed configuration replaces stale successful report with failure',async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-malformed-'));
 const options={watchesPath:path.join(dir,'watches.json'),statePath:path.join(dir,'state.json'),eventsPath:path.join(dir,'events.json'),reportPath:path.join(dir,'report.json')};
 try{
  await fs.writeFile(options.watchesPath,'not json');
  await fs.writeFile(options.reportPath,JSON.stringify({pass:true,checked_at:'stale'}));
  const result=await runVerification(options);
  assert.equal(result.pass,false);assert.match(result.error,/SyntaxError/);
  const saved=JSON.parse(await fs.readFile(options.reportPath,'utf8'));
  assert.equal(saved.pass,false);assert.notEqual(saved.checked_at,'stale');
 }finally{await fs.rm(dir,{recursive:true,force:true});}
});
