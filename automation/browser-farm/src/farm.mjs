
import {spawn} from 'node:child_process';
import {MAX_PARALLEL} from './config.mjs';

const children=[];
function start(args){
  const c=spawn(process.execPath,args,{stdio:'inherit',env:process.env});
  children.push(c);
  c.on('exit',code=>{
    console.error('child exited',args.join(' '),code);
    if(code!==0) setTimeout(()=>start(args),2000);
  });
}
start(['src/github-poller.mjs']);
for(let i=0;i<MAX_PARALLEL;i++) start(['src/worker.mjs']);

process.on('SIGTERM',()=>children.forEach(c=>c.kill('SIGTERM')));
process.on('SIGINT',()=>children.forEach(c=>c.kill('SIGINT')));
