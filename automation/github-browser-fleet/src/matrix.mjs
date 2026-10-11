
import {loadBusinesses,selectBusinesses} from './config.mjs';
const config=await loadBusinesses();
const group=process.argv[2]||'all';
const only=process.argv[3]||'';
const rows=selectBusinesses(config,{group,only}).map(x=>({
  business:x.id,
  // The workflow runs the task from the fleet directory, just like this script.
  task_file:x.task_file,
  mode:x.mode
}));
process.stdout.write(JSON.stringify({include:rows}));
