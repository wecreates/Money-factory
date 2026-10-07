import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createStore,createWatch,listWatches,deleteWatch,listEvents} from './store.mjs';

const PORT=Number(process.env.PORT||8080);
const DATA_FILE=process.env.DATA_FILE||'/data/monitor.json';

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
