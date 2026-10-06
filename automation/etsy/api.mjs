const API='https://api.etsy.com/v3/application';
const TOKEN='https://api.etsy.com/v3/public/oauth/token';

export function shopUrl(shopId){ return `${API}/shops/${shopId}`; }
export function sectionsUrl(shopId){ return `${API}/shops/${shopId}/sections`; }
export function listingUrl(shopId,listingId){ return `${API}/shops/${shopId}/listings/${listingId}`; }
export function publicListingUrl(listingId){ return `${API}/listings/${listingId}`; }
export function listingFilesUrl(shopId,listingId){ return `${API}/shops/${shopId}/listings/${listingId}/files`; }

async function readJson(res){
  const text=await res.text();
  let body; try{body=text?JSON.parse(text):{}}catch{body={raw:text}};
  if(!res.ok){
    const e=new Error(`HTTP ${res.status}: ${text.slice(0,2000)}`);
    e.status=res.status; e.body=body; throw e;
  }
  return body;
}

export async function refreshAccessToken(env=process.env,fetchImpl=fetch){
  const refresh_token=env.ETSY_REFRESH_TOKEN;
  const client_id=env.ETSY_CLIENT_ID;
  if(!refresh_token||!client_id) throw new Error('Missing ETSY_REFRESH_TOKEN/ETSY_CLIENT_ID');
  const form=new URLSearchParams({grant_type:'refresh_token',client_id,refresh_token});
  const res=await fetchImpl(TOKEN,{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:form});
  const data=await readJson(res);
  if(!data.access_token) throw new Error('OAuth response missing access_token');
  return data.access_token;
}

function headers(token,apiKey,form=false){
  const h={'x-api-key':apiKey,Authorization:`Bearer ${token}`};
  if(form) h['content-type']='application/x-www-form-urlencoded';
  return h;
}
export function apiKey(env=process.env){
  const key=env.ETSY_API_KEY;
  const secret=env.ETSY_SHARED_SECRET;
  if(!key||!secret) throw new Error('Missing ETSY_API_KEY/ETSY_SHARED_SECRET');
  return `${key}:${secret}`;
}
export async function getListing({listingId,token,apiKeyValue,fetchImpl=fetch}){
  return readJson(await fetchImpl(publicListingUrl(listingId),{headers:headers(token,apiKeyValue)}));
}
export async function updateListing({shopId,listingId,patch,token,apiKeyValue,fetchImpl=fetch}){
  const form=new URLSearchParams();
  for(const [k,v] of Object.entries(patch||{})){
    if(v==null) continue;
    if(Array.isArray(v)) for(const item of v) form.append(k,String(item));
    else form.set(k,String(v));
  }
  return readJson(await fetchImpl(listingUrl(shopId,listingId),{method:'PATCH',headers:headers(token,apiKeyValue,true),body:form}));
}
export async function updateShop({shopId,patch,token,apiKeyValue,fetchImpl=fetch}){
  const form=new URLSearchParams();
  for(const [k,v] of Object.entries(patch||{})) if(v!=null) form.set(k,String(v));
  return readJson(await fetchImpl(shopUrl(shopId),{method:'PUT',headers:headers(token,apiKeyValue,true),body:form}));
}
export async function createSection({shopId,title,token,apiKeyValue,fetchImpl=fetch}){
  const form=new URLSearchParams({title});
  return readJson(await fetchImpl(sectionsUrl(shopId),{method:'POST',headers:headers(token,apiKeyValue,true),body:form}));
}


export async function uploadListingFile({shopId,listingId,filename,bytes,rank=1,token,apiKeyValue,fetchImpl=fetch}){
  if(!(bytes instanceof Uint8Array)) throw new Error('bytes must be Uint8Array');
  const form=new FormData();
  form.set('name',filename);
  form.set('rank',String(rank));
  form.set('file',new Blob([bytes]),filename);
  const res=await fetchImpl(listingFilesUrl(shopId,listingId),{
    method:'POST',
    headers:{'x-api-key':apiKeyValue,Authorization:`Bearer ${token}`},
    body:form
  });
  return readJson(res);
}
export async function listListingFiles({shopId,listingId,token,apiKeyValue,fetchImpl=fetch}){
  return readJson(await fetchImpl(listingFilesUrl(shopId,listingId),{headers:headers(token,apiKeyValue)}));
}
