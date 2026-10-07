
import {loadBusinesses,selectBusinesses} from './config.mjs';
const config=await loadBusinesses();
const group=process.argv[2]||'all';
const only=process.argv[3]||'';
const rows=selectBusinesses(config,{group,only}).map(x=>({
  business:x.id,
  task_file:'automation/github-browser-fleet/'+x.task_file,
  mode:x.mode
}));
process.stdout.write(JSON.stringify({include:rows}));
