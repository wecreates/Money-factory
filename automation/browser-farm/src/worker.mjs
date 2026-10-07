
import {claim,finish,ensureQueue} from './queue.mjs';
import {runForBusiness} from './browser-manager.mjs';
import {handleTask} from './handlers.mjs';

await ensureQueue();
console.log('CYZOR browser worker started');
for(;;){
  const item=await claim();
  if(!item){await new Promise(r=>setTimeout(r,1000));continue;}
  try{
    const task=item.task;
    if(!task.business) throw new Error('business is required');
    const result=await runForBusiness(task.business,ctx=>handleTask(task,ctx));
    await finish(item.file,result,result.ok!==false);
  }catch(e){
    await finish(item.file,{ok:false,error:String(e?.stack||e)},false);
  }
}
