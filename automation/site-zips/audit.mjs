import fs from 'node:fs/promises';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import config from './site-zips.json' with {type:'json'};
const exec=promisify(execFile);
const out=[];
await fs.rm('tmp',{recursive:true,force:true});
await fs.mkdir('tmp',{recursive:true});
for(const ext of config.extensions){
  const safe=ext.name.replace(/[^a-z0-9]+/gi,'-').toLowerCase();
  const zip=path.resolve('tmp',safe+'.zip');
  let rec={name:ext.name,url:ext.url,ok:false};
  try{
    const res=await fetch(ext.url);
    rec.http_status=res.status;
    if(!res.ok) throw new Error('HTTP '+res.status);
    const bytes=new Uint8Array(await res.arrayBuffer());
    await fs.writeFile(zip,bytes);
    rec.size_bytes=bytes.byteLength;
    const {stdout}=await exec('unzip',['-p',zip,'manifest.json']);
    const m=JSON.parse(stdout);
    rec.version=m.version;
    rec.display_name=m.name;
    rec.manifest_version=m.manifest_version;
    rec.ok=true;
  }catch(e){ rec.error=String(e?.stack||e); }
  out.push(rec);
}
console.log(JSON.stringify(out,null,2));
await fs.writeFile('site-zip-audit.json',JSON.stringify({generated_at:new Date().toISOString(),extensions:out},null,2));
if(out.some(x=>!x.ok)) process.exitCode=1;
