import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {sessionForBusiness} from '../src/session.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const state={cookies:[{name:'synthetic',value:'test-only-session'}],origins:[]};
const raw=JSON.stringify({example:Buffer.from(JSON.stringify(state)).toString('base64')});

test('matrix task paths resolve from the workflow working directory',async()=>{
  for(const group of ['all','frequent','normal']){
    const matrix=JSON.parse(execFileSync(process.execPath,['src/matrix.mjs',group],{cwd:root,encoding:'utf8'}));
    assert.ok(matrix.include.length>0);
    for(const row of matrix.include){
      const task=JSON.parse(await fs.readFile(path.join(root,row.task_file),'utf8'));
      assert.ok(Array.isArray(task.steps));
    }
  }
});

test('sessions are decoded to objects, isolated by business, and optional',()=>{
  assert.deepEqual(sessionForBusiness(raw,'example'),state);
  assert.equal(sessionForBusiness(raw,'other'),undefined);
  assert.equal(sessionForBusiness(undefined,'example'),undefined);
  assert.equal(sessionForBusiness('','example'),undefined);
});

test('malformed sessions fail closed without exposing input',()=>{
  for(const value of ['test-only-session','null','[]',JSON.stringify({example:42}),JSON.stringify({example:'bad'}),JSON.stringify({example:Buffer.from('{}').toString('base64')})]){
    assert.throws(()=>sessionForBusiness(value,'example'),{message:'Invalid browser session configuration'});
  }
});

test('runner uses in-memory sessions and creates no session artifacts',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'fleet-test-'));
  try{
    await fs.writeFile(path.join(dir,'task.json'),JSON.stringify({steps:[{action:'inspect',url:'https://example.invalid'}]}));
    const output=execFileSync(process.execPath,[
      '--loader',path.join(root,'test/fixtures/playwright-loader.mjs'),
      path.join(root,'src/run-business.mjs')
    ],{cwd:dir,encoding:'utf8',env:{...process.env,BUSINESS_ID:'example',TASK_FILE:'task.json',BROWSER_SESSIONS_JSON:raw},stdio:['ignore','pipe','pipe']});
    assert.equal(JSON.parse(output).ok,true);
    const artifacts=path.join(dir,'artifacts/example');
    assert.deepEqual(await fs.readdir(artifacts),['result.json']);
    assert.ok(!output.includes('test-only-session'));
    assert.ok(!(await fs.readFile(path.join(artifacts,'result.json'),'utf8')).includes('test-only-session'));
  }finally{
    await fs.rm(dir,{recursive:true,force:true});
  }
});

test('workflow artifacts allowlist excludes storage-state files',async()=>{
  const workflow=await fs.readFile(path.join(root,'../../.github/workflows/browser-fleet.yml'),'utf8');
  const upload=workflow.split('- uses: actions/upload-artifact@v4')[1];
  assert.match(upload,/path: \|\n\s+automation\/github-browser-fleet\/artifacts\/\$\{\{ matrix.business \}\}\/result\.json\n\s+automation\/github-browser-fleet\/artifacts\/\$\{\{ matrix.business \}\}\/\*\*\/\*\.png\n/);
});

import {spawnSync} from 'node:child_process';

test('authenticated tasks reject missing sessions before opening the browser',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'fleet-auth-'));
  try{
    await fs.writeFile(path.join(dir,'task.json'),JSON.stringify({steps:[{action:'goto',url:'https://chrome.google.com/webstore/devconsole/'}]}));
    const result=spawnSync(process.execPath,['--loader',path.join(root,'test/fixtures/playwright-loader.mjs'),path.join(root,'src/run-business.mjs')],{cwd:dir,encoding:'utf8',env:{...process.env,BUSINESS_ID:'chrome-store',TASK_FILE:'task.json',BROWSER_SESSIONS_JSON:''}});
    assert.equal(result.status,2);
    assert.equal(JSON.parse(result.stdout).error,'AUTHENTICATED_SESSION_REQUIRED');
    assert.deepEqual(await fs.readdir(path.join(dir,'artifacts/chrome-store')),['result.json']);
  }finally{await fs.rm(dir,{recursive:true,force:true});}
});

test('authenticated navigation rejects sign-in redirects and stops following actions',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'fleet-redirect-'));
  try{
    await fs.writeFile(path.join(dir,'task.json'),JSON.stringify({steps:[{action:'goto',url:'https://chrome.google.com/webstore/devconsole/'},{action:'screenshot'}]}));
    const result=spawnSync(process.execPath,['--loader',path.join(root,'test/fixtures/playwright-loader.mjs'),path.join(root,'src/run-business.mjs')],{cwd:dir,encoding:'utf8',env:{...process.env,BUSINESS_ID:'chrome-store',TASK_FILE:'task.json',BROWSER_SESSIONS_JSON:JSON.stringify({'chrome-store':Buffer.from(JSON.stringify(state)).toString('base64')}),FIXTURE_URL:'https://accounts.google.com/signin'}});
    assert.equal(result.status,2);
    const report=JSON.parse(result.stdout);assert.equal(report.ok,false);assert.equal(report.results.length,1);
    assert.equal(report.results[0].error,'AUTHENTICATED_DESTINATION_NOT_REACHED');
  }finally{await fs.rm(dir,{recursive:true,force:true});}
});
