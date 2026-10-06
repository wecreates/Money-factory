const endpoint='https://api.grants.gov/v1/api/search2';
const payload={keyword:'education',oppStatuses:'posted',rows:5};
const res=await fetch(endpoint,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
const text=await res.text();
let body; try{body=JSON.parse(text)}catch{body={raw:text}};
const hits=body?.data?.oppHits;
const out={
  checked_at:new Date().toISOString(),
  endpoint,
  status:res.status,
  ok:res.ok,
  has_oppHits:Array.isArray(hits),
  hit_count:Array.isArray(hits)?hits.length:null,
  sample:Array.isArray(hits)?hits.slice(0,3).map(x=>({id:x.id||null,number:x.number||null,title:x.title||null,closeDate:x.closeDate||null,oppStatus:x.oppStatus||null})):null
};
console.log(JSON.stringify(out,null,2));
if(!res.ok || !Array.isArray(hits)) process.exitCode=1;
