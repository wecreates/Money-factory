import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {createStore,createWatch,listWatches,deleteWatch,listEvents,applyCheck} from './store.mjs';

const PORT=Number(process.env.PORT||8080);
const DATA_FILE=process.env.DATA_FILE||'/data/monitor.json';
const CHECK_MS=Math.max(60000,Number(process.env.CHECK_MS||300000));

async function load(){
  try{return createStore(JSON.parse(await fs.readFile(DATA_FILE,'utf8')))}
  catch{return createStore()}
}
async function save(store){
  await fs.mkdir(path.dirname(DATA_FILE),{recursive:true});
  await fs.writeFile(DATA_FILE,JSON.stringify(store,null,2)+'\n');
}
function send(res,status,data){
  const body=JSON.stringify(data);
  res.writeHead(status,{'content-type':'application/json; charset=utf-8','access-control-allow-origin':'*','access-control-allow-methods':'GET,POST,DELETE,OPTIONS','access-control-allow-headers':'content-type'});
  res.end(body);
}
async function body(req){
  let s=''; for await (const c of req) s+=c;
  return s?JSON.parse(s):{};
}
const store=await load();

let checking=false;
async function runChecks(){
  if(checking) return;
  checking=true;
  try{
    for(const w of store.watches.filter(x=>x.status==='active')){
      try{
        const r=await fetch(w.target_url,{redirect:'follow',headers:{'user-agent':'CYZOR-Oracle-Monitor/1.0'}});
        const body=Buffer.from(await r.arrayBuffer());
        const hash=crypto.createHash('sha256').update(body).digest('hex');
        applyCheck(store,w.id,{hash,checkedAt:Date.now(),status:r.status});
      }catch(error){
        const current=store.watches.find(x=>x.id===w.id);
        if(current){
          current.last_checked_at=Date.now();
          current.last_error=String(error);
        }
      }
    }
    await save(store);
  }finally{
    checking=false;
  }
}
setTimeout(runChecks,5000);
setInterval(runChecks,CHECK_MS);

const server=http.createServer(async(req,res)=>{
  try{
    if(req.method==='OPTIONS'){res.writeHead(204,{'access-control-allow-origin':'*','access-control-allow-methods':'GET,POST,DELETE,OPTIONS','access-control-allow-headers':'content-type'});return res.end()}
    const u=new URL(req.url,'http://localhost');
    if(u.pathname==='/health') return send(res,200,{ok:true,service:'cyzor-oracle-monitor-api'});

    if(u.pathname==='/api/v1/ext/watch'&&req.method==='GET'){
      const clientId=u.searchParams.get('clientId')||'';
      return send(res,200,{watches:listWatches(store,clientId)});
    }
    if(u.pathname==='/api/v1/ext/watch'&&req.method==='POST'){
      const data=await body(req);
      const w=createWatch(store,data);
      await save(store);
      return send(res,200,{ok:true,id:w.id});
    }
    const m=u.pathname.match(/^\/api\/v1\/ext\/watch\/([^/]+)$/);
    if(m&&req.method==='DELETE'){
      const clientId=u.searchParams.get('clientId')||'';
      const ok=deleteWatch(store,clientId,decodeURIComponent(m[1]));
      if(ok) await save(store);
      return send(res,200,{ok});
    }
    if(u.pathname==='/api/v1/ext/events'&&req.method==='GET'){
      const clientId=u.searchParams.get('clientId')||'';
      return send(res,200,{events:listEvents(store,clientId)});
    }
    send(res,404,{error:'not found'});
  }catch(e){
    send(res,400,{error:String(e?.message||e)});
  }
});
server.listen(PORT,'0.0.0.0',()=>console.log('oracle monitor api listening on',PORT));
