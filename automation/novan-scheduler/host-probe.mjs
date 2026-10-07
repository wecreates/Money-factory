import fs from 'node:fs/promises';
import dns from 'node:dns/promises';
import tls from 'node:tls';

const host='cyzorcreations.com';
const out={checked_at:new Date().toISOString(),host};

for (const [name,fn] of Object.entries({
  A:()=>dns.resolve4(host),
  AAAA:()=>dns.resolve6(host),
  CNAME:()=>dns.resolveCname(host),
  NS:()=>dns.resolveNs(host),
  MX:()=>dns.resolveMx(host)
})) {
  try{out[name]=await fn()}catch(e){out[name]={error:e.code||String(e)}}
}

const ips=Array.isArray(out.A)?out.A:[];
out.reverse={};
out.ipinfo={};
for(const ip of ips){
  try{out.reverse[ip]=await dns.reverse(ip)}catch(e){out.reverse[ip]={error:e.code||String(e)}}
  try{
    const r=await fetch('https://ipinfo.io/'+encodeURIComponent(ip)+'/json');
    out.ipinfo[ip]=await r.json();
  }catch(e){out.ipinfo[ip]={error:String(e)}}
}

out.tls=await new Promise(resolve=>{
  const s=tls.connect(443,host,{servername:host},()=>{
    const c=s.getPeerCertificate();
    resolve({
      subject:c.subject||null,
      issuer:c.issuer||null,
      subjectaltname:c.subjectaltname||null,
      valid_from:c.valid_from||null,
      valid_to:c.valid_to||null,
      fingerprint256:c.fingerprint256||null
    });
    s.end();
  });
  s.setTimeout(15000,()=>{s.destroy();resolve({error:'timeout'})});
  s.on('error',e=>resolve({error:String(e)}));
});

const r=await fetch('https://cyzorcreations.com/api/v1/ext/watch?clientId=cyzor-host-probe');
out.http={status:r.status,headers:Object.fromEntries(r.headers.entries())};

await fs.writeFile('CYZOR_HOST_PROBE.json',JSON.stringify(out,null,2)+'\n');
console.log(JSON.stringify(out,null,2));
