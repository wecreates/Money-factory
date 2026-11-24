import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('../../../',import.meta.url));
const exec=promisify(execFile);

async function git(cwd,...args){
  return exec('git',args,{cwd});
}

function persistScript(workflow){
  const match=workflow.match(/- name: Persist monitor state\n[\s\S]*?run: \|\n([\s\S]*?)      - name: Fail on unhealthy targets/);
  assert.ok(match,'persist step not found');
  return match[1].split('\n').map(line=>line.startsWith('          ')?line.slice(10):line).join('\n');
}

function restoreScript(workflow){
  const match=workflow.match(/- name: Restore durable monitor state\n[\s\S]*?run: \|\n([\s\S]*?)      - name: Unit tests/);
  assert.ok(match,'restore step not found');
  return match[1].split('\n').map(line=>line.startsWith('          ')?line.slice(10):line).join('\n');
}

function diagnosticPersistScript(workflow){
  const match=workflow.match(/- name: Persist diagnostic\n[\s\S]*?run: \|\n([\s\S]*?)      - name: Fail on unsuccessful diagnostic/);
  assert.ok(match,'diagnostic persist step not found');
  return match[1].split('\n').map(line=>line.startsWith('          ')?line.slice(10):line).join('\n');
}

function diagnosticRestoreScript(workflow){
  const match=workflow.match(/- name: Restore durable monitor state\n[\s\S]*?run: \|\n([\s\S]*?)      - name: Run diagnostic/);
  assert.ok(match,'diagnostic restore step not found');
  return match[1].split('\n').map(line=>line.startsWith('          ')?line.slice(10):line).join('\n');
}

function verificationPersistScript(workflow){
  const match=workflow.match(/- name: Persist verification\n[\s\S]*?run: \|\n([\s\S]*?)      - name: Fail on unsuccessful verification/);
  assert.ok(match,'verification persist step not found');
  return match[1].split('\n').map(line=>line.startsWith('          ')?line.slice(10):line).join('\n');
}

function verificationRestoreScript(workflow){
  const match=workflow.match(/- name: Restore durable monitor state\n[\s\S]*?run: \|\n([\s\S]*?)      - name: Unit tests/);
  assert.ok(match,'verification restore step not found');
  return match[1].split('\n').map(line=>line.startsWith('          ')?line.slice(10):line).join('\n');
}

test('repository watch follows main while cadence evidence uses a separate branch',async()=>{
  const watches=JSON.parse(await fs.readFile(root+'FREE_MONITOR_WATCHES.json','utf8'));
  const repository=watches.find(watch=>watch.id==='money-factory-repository');
  assert.equal(repository?.targetUrl,
    'https://api.github.com/repos/wecreates/Money-factory/commits/main');

  const workflow=await fs.readFile(root+'.github/workflows/free-monitor-worker.yml','utf8');
  assert.match(workflow,/MONITOR_STATE_BRANCH: cyzor-free-monitor-state/);
  assert.match(workflow,/git show "origin\/\$MONITOR_STATE_BRANCH:FREE_MONITOR_STATE\.json"/);
  assert.match(workflow,/git worktree add -B "\$MONITOR_STATE_BRANCH"/);
  assert.match(workflow,/git push origin "HEAD:refs\/heads\/\$MONITOR_STATE_BRANCH"/);
  assert.match(workflow,/free monitor cadence tick \[skip ci\]/);
  assert.match(workflow,/cleanup\(\) \{\s+cd "\$GITHUB_WORKSPACE"/);
  assert.doesNotMatch(workflow,/git push origin HEAD:main/);
});

test('persist step advances only the state branch and retains both files',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-state-branch-'));
  const remote=path.join(dir,'remote.git');
  const workspace=path.join(dir,'workspace');
  const restored=path.join(dir,'restored');
  const workflow=await fs.readFile(root+'.github/workflows/free-monitor-worker.yml','utf8');
  const script=persistScript(workflow);
  try{
    await fs.mkdir(workspace);
    await git(dir,'init','--bare',remote);
    await git(workspace,'init','--initial-branch=main');
    await git(workspace,'config','user.name','fixture');
    await git(workspace,'config','user.email','fixture@example.com');
    await git(workspace,'remote','add','origin',remote);
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'{"cycle":1}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_EVENTS.json'),'[]\n');
    await git(workspace,'add','FREE_MONITOR_STATE.json','FREE_MONITOR_EVENTS.json');
    await git(workspace,'commit','-m','fixture main');
    await git(workspace,'push','-u','origin','main');
    const main=(await git(workspace,'rev-parse','HEAD')).stdout.trim();

    const env={...process.env,GITHUB_WORKSPACE:workspace,MONITOR_STATE_BRANCH:'cyzor-free-monitor-state'};
    await exec('bash',['-c',script],{cwd:workspace,env});
    assert.equal((await git(dir,'--git-dir='+remote,'rev-parse','main')).stdout.trim(),main);
    const first=(await git(dir,'--git-dir='+remote,'rev-parse','cyzor-free-monitor-state')).stdout.trim();
    assert.equal((await git(dir,'--git-dir='+remote,'show',first+':FREE_MONITOR_STATE.json')).stdout,'{"cycle":1}\n');
    assert.equal((await git(dir,'--git-dir='+remote,'show',first+':FREE_MONITOR_EVENTS.json')).stdout,'[]\n');

    await git(workspace,'fetch','origin','cyzor-free-monitor-state:refs/remotes/origin/cyzor-free-monitor-state');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'{"cycle":2}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_EVENTS.json'),'[{"type":"change"}]\n');
    await exec('bash',['-c',script],{cwd:workspace,env});
    const second=(await git(dir,'--git-dir='+remote,'rev-parse','cyzor-free-monitor-state')).stdout.trim();
    assert.notEqual(second,first);
    assert.equal((await git(dir,'--git-dir='+remote,'show',second+':FREE_MONITOR_STATE.json')).stdout,'{"cycle":2}\n');
    assert.equal((await git(dir,'--git-dir='+remote,'show',second+':FREE_MONITOR_EVENTS.json')).stdout,'[{"type":"change"}]\n');
    assert.equal((await git(dir,'--git-dir='+remote,'rev-parse','main')).stdout.trim(),main);

    await git(dir,'clone','--branch','main',remote,restored);
    await exec('bash',['-c',restoreScript(workflow)],{
      cwd:restored,
      env:{...process.env,GITHUB_WORKSPACE:restored,MONITOR_STATE_BRANCH:'cyzor-free-monitor-state'}
    });
    assert.equal(await fs.readFile(path.join(restored,'FREE_MONITOR_STATE.json'),'utf8'),'{"cycle":2}\n');
    assert.equal(await fs.readFile(path.join(restored,'FREE_MONITOR_EVENTS.json'),'utf8'),'[{"type":"change"}]\n');
  }finally{
    await fs.rm(dir,{recursive:true,force:true});
  }
});

test('diagnostic persists on the state branch without changing main',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-diagnostic-branch-'));
  const remote=path.join(dir,'remote.git');
  const workspace=path.join(dir,'workspace');
  const restored=path.join(dir,'restored');
  const workflow=await fs.readFile(root+'.github/workflows/free-monitor-diagnostic.yml','utf8');
  const persist=diagnosticPersistScript(workflow);
  const restore=diagnosticRestoreScript(workflow);
  try{
    await fs.mkdir(workspace);
    await git(dir,'init','--bare',remote);
    await git(workspace,'init','--initial-branch=main');
    await git(workspace,'config','user.name','fixture');
    await git(workspace,'config','user.email','fixture@example.com');
    await git(workspace,'remote','add','origin',remote);
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_DIAGNOSTIC.json'),'{"run":"main"}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'{"cycle":"main"}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_EVENTS.json'),'[]\n');
    await git(workspace,'add','FREE_MONITOR_DIAGNOSTIC.json','FREE_MONITOR_STATE.json','FREE_MONITOR_EVENTS.json');
    await git(workspace,'commit','-m','fixture main');
    await git(workspace,'push','-u','origin','main');
    const main=(await git(workspace,'rev-parse','HEAD')).stdout.trim();

    await git(workspace,'switch','-c','cyzor-free-monitor-state');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'{"cycle":1}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_EVENTS.json'),'[{"event":1}]\n');
    await git(workspace,'add','FREE_MONITOR_STATE.json','FREE_MONITOR_EVENTS.json');
    await git(workspace,'commit','-m','fixture retained state');
    await git(workspace,'push','-u','origin','cyzor-free-monitor-state');
    await git(workspace,'switch','main');
    await git(workspace,'fetch','origin','cyzor-free-monitor-state:refs/remotes/origin/cyzor-free-monitor-state');

    const baseEnv={...process.env,GITHUB_WORKSPACE:workspace,MONITOR_STATE_BRANCH:'cyzor-free-monitor-state'};
    await exec('bash',['-c',restore],{cwd:workspace,env:baseEnv});
    assert.equal(await fs.readFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'utf8'),'{"cycle":1}\n');
    assert.equal(await fs.readFile(path.join(workspace,'FREE_MONITOR_EVENTS.json'),'utf8'),'[{"event":1}]\n');

    await fs.writeFile(path.join(workspace,'FREE_MONITOR_DIAGNOSTIC.json'),'{"run":"healthy"}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'{"cycle":2}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_EVENTS.json'),'[{"event":2}]\n');
    await exec('bash',['-c',persist],{cwd:workspace,env:{...baseEnv,PAIR_READY:'true'}});
    const healthy=(await git(dir,'--git-dir='+remote,'rev-parse','cyzor-free-monitor-state')).stdout.trim();
    assert.equal((await git(dir,'--git-dir='+remote,'show',healthy+':FREE_MONITOR_DIAGNOSTIC.json')).stdout,'{"run":"healthy"}\n');
    assert.equal((await git(dir,'--git-dir='+remote,'show',healthy+':FREE_MONITOR_STATE.json')).stdout,'{"cycle":2}\n');
    assert.equal((await git(dir,'--git-dir='+remote,'show',healthy+':FREE_MONITOR_EVENTS.json')).stdout,'[{"event":2}]\n');
    assert.equal((await git(dir,'--git-dir='+remote,'rev-parse','main')).stdout.trim(),main);

    await git(workspace,'fetch','origin','cyzor-free-monitor-state:refs/remotes/origin/cyzor-free-monitor-state');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_DIAGNOSTIC.json'),'{"run":"failed"}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'{"cycle":"partial"}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_EVENTS.json'),'[{"event":"partial"}]\n');
    await exec('bash',['-c',persist],{cwd:workspace,env:{...baseEnv,PAIR_READY:'false'}});
    const failed=(await git(dir,'--git-dir='+remote,'rev-parse','cyzor-free-monitor-state')).stdout.trim();
    assert.notEqual(failed,healthy);
    assert.equal((await git(dir,'--git-dir='+remote,'show',failed+':FREE_MONITOR_DIAGNOSTIC.json')).stdout,'{"run":"failed"}\n');
    assert.equal((await git(dir,'--git-dir='+remote,'show',failed+':FREE_MONITOR_STATE.json')).stdout,'{"cycle":2}\n');
    assert.equal((await git(dir,'--git-dir='+remote,'show',failed+':FREE_MONITOR_EVENTS.json')).stdout,'[{"event":2}]\n');
    assert.equal((await git(dir,'--git-dir='+remote,'rev-parse','main')).stdout.trim(),main);

    await git(dir,'clone','--branch','main',remote,restored);
    await exec('bash',['-c',restore],{cwd:restored,env:{...baseEnv,GITHUB_WORKSPACE:restored}});
    assert.equal(await fs.readFile(path.join(restored,'FREE_MONITOR_STATE.json'),'utf8'),'{"cycle":2}\n');
    assert.equal(await fs.readFile(path.join(restored,'FREE_MONITOR_EVENTS.json'),'utf8'),'[{"event":2}]\n');
  }finally{
    await fs.rm(dir,{recursive:true,force:true});
  }
});

test('diagnostic workflow cannot write operational evidence to main',async()=>{
  const workflow=await fs.readFile(root+'.github/workflows/free-monitor-diagnostic.yml','utf8');
  assert.match(workflow,/MONITOR_STATE_BRANCH: cyzor-free-monitor-state/);
  assert.match(workflow,/git push origin "HEAD:refs\/heads\/\$MONITOR_STATE_BRANCH"/);
  assert.match(workflow,/record free monitor diagnostic \[skip ci\]/);
  assert.doesNotMatch(workflow,/git push origin HEAD:main/);
  assert.doesNotMatch(workflow,/git pull --rebase origin main/);
});

test('verification persists on the state branch and retains the last completed pair',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-verification-branch-'));
  const remote=path.join(dir,'remote.git');
  const workspace=path.join(dir,'workspace');
  const workflow=await fs.readFile(root+'.github/workflows/free-monitor-verify.yml','utf8');
  const persist=verificationPersistScript(workflow);
  const restore=verificationRestoreScript(workflow);
  try{
    await fs.mkdir(workspace);
    await git(dir,'init','--bare',remote);
    await git(workspace,'init','--initial-branch=main');
    await git(workspace,'config','user.name','fixture');
    await git(workspace,'config','user.email','fixture@example.com');
    await git(workspace,'remote','add','origin',remote);
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_VERIFICATION.json'),'{"run":"main"}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'{"cycle":"main"}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_EVENTS.json'),'[]\n');
    await git(workspace,'add','FREE_MONITOR_VERIFICATION.json','FREE_MONITOR_STATE.json','FREE_MONITOR_EVENTS.json');
    await git(workspace,'commit','-m','fixture main');
    await git(workspace,'push','-u','origin','main');
    const main=(await git(workspace,'rev-parse','HEAD')).stdout.trim();

    await git(workspace,'switch','-c','cyzor-free-monitor-state');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'{"cycle":1}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_EVENTS.json'),'[{"event":1}]\n');
    await git(workspace,'add','FREE_MONITOR_STATE.json','FREE_MONITOR_EVENTS.json');
    await git(workspace,'commit','-m','fixture retained state');
    await git(workspace,'push','-u','origin','cyzor-free-monitor-state');
    await git(workspace,'switch','main');
    await git(workspace,'fetch','origin','cyzor-free-monitor-state:refs/remotes/origin/cyzor-free-monitor-state');
    const baseEnv={...process.env,GITHUB_WORKSPACE:workspace,MONITOR_STATE_BRANCH:'cyzor-free-monitor-state'};
    await exec('bash',['-c',restore],{cwd:workspace,env:baseEnv});
    assert.equal(await fs.readFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'utf8'),'{"cycle":1}\n');

    await fs.writeFile(path.join(workspace,'FREE_MONITOR_VERIFICATION.json'),'{"run":"healthy"}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'{"cycle":2}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_EVENTS.json'),'[{"event":2}]\n');
    await exec('bash',['-c',persist],{cwd:workspace,env:{...baseEnv,PAIR_READY:'true'}});
    const healthy=(await git(dir,'--git-dir='+remote,'rev-parse','cyzor-free-monitor-state')).stdout.trim();
    assert.equal((await git(dir,'--git-dir='+remote,'show',healthy+':FREE_MONITOR_VERIFICATION.json')).stdout,'{"run":"healthy"}\n');
    assert.equal((await git(dir,'--git-dir='+remote,'show',healthy+':FREE_MONITOR_STATE.json')).stdout,'{"cycle":2}\n');
    assert.equal((await git(dir,'--git-dir='+remote,'show',healthy+':FREE_MONITOR_EVENTS.json')).stdout,'[{"event":2}]\n');
    assert.equal((await git(dir,'--git-dir='+remote,'rev-parse','main')).stdout.trim(),main);

    await git(workspace,'fetch','origin','cyzor-free-monitor-state:refs/remotes/origin/cyzor-free-monitor-state');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_VERIFICATION.json'),'{"run":"failed"}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_STATE.json'),'{"cycle":"partial"}\n');
    await fs.writeFile(path.join(workspace,'FREE_MONITOR_EVENTS.json'),'[{"event":"partial"}]\n');
    await exec('bash',['-c',persist],{cwd:workspace,env:{...baseEnv,PAIR_READY:'false'}});
    const failed=(await git(dir,'--git-dir='+remote,'rev-parse','cyzor-free-monitor-state')).stdout.trim();
    assert.notEqual(failed,healthy);
    assert.equal((await git(dir,'--git-dir='+remote,'show',failed+':FREE_MONITOR_VERIFICATION.json')).stdout,'{"run":"failed"}\n');
    assert.equal((await git(dir,'--git-dir='+remote,'show',failed+':FREE_MONITOR_STATE.json')).stdout,'{"cycle":2}\n');
    assert.equal((await git(dir,'--git-dir='+remote,'show',failed+':FREE_MONITOR_EVENTS.json')).stdout,'[{"event":2}]\n');
    assert.equal((await git(dir,'--git-dir='+remote,'rev-parse','main')).stdout.trim(),main);
  }finally{
    await fs.rm(dir,{recursive:true,force:true});
  }
});

test('verification workflow cannot write operational evidence to main',async()=>{
  const workflow=await fs.readFile(root+'.github/workflows/free-monitor-verify.yml','utf8');
  assert.match(workflow,/MONITOR_STATE_BRANCH: cyzor-free-monitor-state/);
  assert.match(workflow,/git push origin "HEAD:refs\/heads\/\$MONITOR_STATE_BRANCH"/);
  assert.match(workflow,/verify free monitor cadence \[skip ci\]/);
  assert.doesNotMatch(workflow,/git push origin HEAD:main/);
  assert.doesNotMatch(workflow,/git pull --rebase origin main/);
});
