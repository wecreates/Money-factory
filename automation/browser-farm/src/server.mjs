
import express from 'express';
import {enqueue,counts,ensureQueue} from './queue.mjs';
import {PORT,FARM_TOKEN,MAX_PARALLEL} from './config.mjs';
import {spawn} from 'node:child_process';

await ensureQueue();
const app=express();
app.use(express.json({limit:'2mb'}));

app.get('/health',async(req,res)=>res.json({ok:true,queue:await counts(),max_parallel:MAX_PARALLEL}));

app.use((req,res,next)=>{
  if(!FARM_TOKEN) return res.status(503).json({error:'FARM_TOKEN not configured'});
  if((req.get('authorization')||'')!==('Bearer '+FARM_TOKEN)) return res.status(401).json({error:'unauthorized'});
  next();
});

app.post('/tasks',async(req,res)=>{
  const task=req.body||{};
  if(!task.business||!task.type) return res.status(400).json({error:'business and type required'});
  const id=await enqueue(task);
  res.status(202).json({ok:true,id});
});

app.listen(PORT,'127.0.0.1',()=>{
  console.log('CYZOR Browser Farm listening locally on',PORT);
  for(let i=0;i<MAX_PARALLEL;i++){
    const child=spawn(process.execPath,['src/worker.mjs'],{stdio:'inherit',env:process.env});
    child.on('exit',code=>console.error('worker exited',code));
  }
});
