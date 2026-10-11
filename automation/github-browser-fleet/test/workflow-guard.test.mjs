import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

const workflows={
  'free-browser-fleet-health':'health',
  'free-monitor-diagnostic':'diagnose',
  'free-monitor-verify':'verify',
  'free-monitor-worker':'monitor',
  'render-immediate-check-verify':'verify',
  'render-monitor-cutover-verify':'verify'
};

for(const [name,jobName] of Object.entries(workflows)){
const workflowURL=new URL(`../../../.github/workflows/${name}.yml`,import.meta.url);
test(`${name} only triggers automatically for main pushes`,async()=>{
  const workflow=await fs.readFile(workflowURL,'utf8');
  assert.match(workflow,/\n  push:\n    branches: \[main\]\n/);
  assert.match(workflow,/\n  workflow_dispatch:/);
});

test(`${name} rejects non-main refs even for manual dispatch`,async()=>{
  const workflow=await fs.readFile(workflowURL,'utf8');
  const job=workflow.split(`\n  ${jobName}:\n`)[1];
  assert.ok(job,'write-enabled job must exist');
  assert.match(job,/\n    if: github\.ref == 'refs\/heads\/main'\n/);
  assert.ok(job.indexOf("if: github.ref == 'refs/heads/main'")<job.indexOf('steps:'),'guard belongs to the whole job');
});
}

test('main monitor schedule and concurrency remain intact',async()=>{
  const workflow=await fs.readFile(new URL('../../../.github/workflows/free-monitor-worker.yml',import.meta.url),'utf8');
  assert.match(workflow,/schedule:\n    - cron: '\*\/5 \* \* \* \*'/);
  assert.match(workflow,/concurrency:\n  group: cyzor-free-monitor-worker\n  cancel-in-progress: false/);
});

test('guard changes trigger dedicated regression CI',async()=>{
  const workflow=await fs.readFile(new URL('../../../.github/workflows/browser-fleet-tests.yml',import.meta.url),'utf8');
  for(const name of Object.keys(workflows)){
    assert.equal(workflow.split(`'.github/workflows/${name}.yml'`).length-1,2,'both PR and main push must test '+name);
  }
});
