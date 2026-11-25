import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {runBoundedProcess} from '../resource-supervisor.mjs';

const node=process.execPath,python='/usr/bin/python3';
const worker=fileURLToPath(new URL('../worker.mjs',import.meta.url));
const limits={cpuSeconds:5,addressSpaceBytes:8_000_000_000,fileSizeBytes:1_000_000,
  totalOutputBytes:1_000_000,wallMs:10_000};

async function fixture(t){
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'monitor-bounded-'));
  t.after(()=>fs.rm(directory,{recursive:true,force:true}));
  return directory;
}

test('actual monitor workload completes inside enforced process and output ceilings',async t=>{
  const directory=await fixture(t);
  await fs.writeFile(path.join(directory,'FREE_MONITOR_WATCHES.json'),'[]\n');
  const receipt=await runBoundedProcess({command:node,args:[worker],cwd:directory,limits,pollMs:5,
    env:{...process.env,MONITOR_WORKFLOW_WALL_LIMIT_MS:'300000'}});
  assert.equal(receipt.exit_code,0);
  assert.equal(receipt.signal,null);
  assert.equal(receipt.termination,'process_exit');
  assert.equal(receipt.success,true);
  assert.equal(receipt.enforcement.cpu_time_rlimit_per_process,true);
  assert.equal(receipt.enforcement.address_space_rlimit_per_process,true);
  assert.equal(receipt.enforcement.aggregate_output_process_group_watchdog,true);
  assert.equal(receipt.enforcement.total_cpu_tree_quota,false);
  assert.equal(receipt.enforcement.total_memory_tree_quota,false);
  assert.ok(receipt.observed.peak_output_bytes<=limits.totalOutputBytes);
  assert.ok(receipt.observed.peak_rss_bytes>0);
  assert.equal(JSON.parse(await fs.readFile(path.join(directory,'FREE_MONITOR_STATE.json'),'utf8'))
    ._monitor_runtime.publication_enabled,false);
});
test('total-output watchdog kills a real multi-file writer crossing its aggregate ceiling',async t=>{
  const directory=await fixture(t);
  const script='import os,time\nfor i in range(100):\n open(f"chunk-{i}","wb").write(b"x"*65536)\n time.sleep(.01)\n';
  const receipt=await runBoundedProcess({command:python,args:['-c',script],cwd:directory,
    limits:{...limits,totalOutputBytes:200_000},pollMs:5});
  assert.equal(receipt.termination,'total_output_limit');
  assert.equal(receipt.success,false);
  assert.equal(receipt.signal,'SIGKILL');
  assert.ok(receipt.observed.peak_output_bytes>200_000);
});

test('post-exit validation rejects a fast aggregate writer that finishes between polls',async t=>{
  const directory=await fixture(t);
  const receipt=await runBoundedProcess({command:python,
    args:['-c','open("burst.bin","wb").write(b"x"*900000)'],cwd:directory,
    limits:{...limits,totalOutputBytes:200_000},pollMs:1_000});
  assert.equal(receipt.exit_code,0);
  assert.equal(receipt.signal,null);
  assert.equal(receipt.success,false);
  assert.equal(receipt.termination,'total_output_limit_post_exit');
  assert.equal(receipt.observed.output_after_bytes,900_000);
});

test('wall timer kills a process that overruns between slow aggregate-output polls',async t=>{
  const directory=await fixture(t);
  const receipt=await runBoundedProcess({command:python,args:['-c','import time; time.sleep(.2)'],cwd:directory,
    limits:{...limits,wallMs:100},pollMs:1_000});
  assert.equal(receipt.success,false);
  assert.equal(receipt.termination,'wall_limit');
  assert.equal(receipt.signal,'SIGKILL');
});

test('post-exit wall validation excludes supervisor polling after a timely process exit',async t=>{
  const directory=await fixture(t);
  const receipt=await runBoundedProcess({command:python,args:['-c','import time; time.sleep(.05)'],cwd:directory,
    limits:{...limits,wallMs:500},pollMs:1_000});
  assert.equal(receipt.success,true);
  assert.equal(receipt.termination,'process_exit');
  assert.ok(receipt.elapsed_ms<500);
});

test('transient atomic rename and delete races do not kill a healthy bounded writer',async t=>{
  const directory=await fixture(t);
  const script='import os,time\nfor i in range(300):\n p=f".atomic-{i}.tmp"\n q=f"atomic-{i%3}.json"\n open(p,"wb").write(b"x"*128)\n os.replace(p,q)\n if i%2==0:\n  try: os.unlink(q)\n  except FileNotFoundError: pass\n time.sleep(.0005)\n';
  const receipt=await runBoundedProcess({command:python,args:['-c',script],cwd:directory,
    limits:{...limits,totalOutputBytes:500_000},pollMs:1});
  assert.equal(receipt.success,true);
  assert.equal(receipt.termination,'process_exit');
});

test('repeated actual monitor runs survive concurrent atomic output measurement',async t=>{
  for(let iteration=0;iteration<12;iteration++){
    const directory=await fixture(t);
    await fs.writeFile(path.join(directory,'FREE_MONITOR_WATCHES.json'),'[]\n');
    const receipt=await runBoundedProcess({command:node,args:[worker],cwd:directory,limits,pollMs:1,
      env:{...process.env,MONITOR_WORKFLOW_WALL_LIMIT_MS:'300000'}});
    assert.equal(receipt.success,true,`iteration ${iteration}: ${JSON.stringify(receipt)}`);
  }
});

test('address-space rlimit contains a real memory pressure workload',async t=>{
  const directory=await fixture(t);
  const receipt=await runBoundedProcess({command:python,
    args:['-c','x=bytearray(256*1024*1024); print(len(x))'],cwd:directory,
    limits:{...limits,addressSpaceBytes:64*1024*1024},pollMs:5});
  assert.notEqual(receipt.exit_code,0);
  assert.equal(receipt.success,false);
  assert.ok(receipt.observed.peak_rss_bytes<64*1024*1024);
  assert.equal(receipt.enforcement.address_space_rlimit_per_process,true);
});

test('CPU rlimit terminates a real busy process before the wall watchdog',async t=>{
  const directory=await fixture(t);
  const receipt=await runBoundedProcess({command:python,args:['-c','while True: pass'],cwd:directory,
    limits:{...limits,cpuSeconds:1,wallMs:5_000},pollMs:5});
  assert.equal(receipt.termination,'limit_signal');
  assert.equal(receipt.success,false);
  assert.ok(['SIGKILL','SIGXCPU'].includes(receipt.signal));
  assert.ok(receipt.elapsed_ms<5_000);
  assert.ok(receipt.observed.peak_user_cpu_ticks>0);
});

test('symlinks in the output root fail closed before starting work',async t=>{
  const directory=await fixture(t);
  await fs.symlink('/tmp',path.join(directory,'escape'));
  await assert.rejects(runBoundedProcess({command:node,args:['-e','process.exit(0)'],cwd:directory,limits}),
    /cannot contain symbolic links/);
});

