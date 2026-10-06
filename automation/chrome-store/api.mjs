const API='https://chromewebstore.googleapis.com';
const OAUTH='https://oauth2.googleapis.com/token';

export function itemBase(publisherId, extensionId) {
  if (!publisherId || !extensionId) throw new Error('publisherId and extensionId are required');
  return `${API}/v2/publishers/${encodeURIComponent(publisherId)}/items/${encodeURIComponent(extensionId)}`;
}
export function statusUrl(publisherId, extensionId) { return itemBase(publisherId,extensionId)+':fetchStatus'; }
export function publishUrl(publisherId, extensionId) { return itemBase(publisherId,extensionId)+':publish'; }
export function cancelUrl(publisherId, extensionId) { return itemBase(publisherId,extensionId)+':cancelSubmission'; }
export function uploadUrl(publisherId, extensionId) {
  return `${API}/upload/v2/publishers/${encodeURIComponent(publisherId)}/items/${encodeURIComponent(extensionId)}:upload`;
}

async function readJson(res) {
  const text=await res.text();
  let body=null;
  try { body=text?JSON.parse(text):{}; } catch { body={raw:text}; }
  if (!res.ok) {
    const e=new Error(`HTTP ${res.status}: ${text.slice(0,2000)}`);
    e.status=res.status; e.body=body; throw e;
  }
  return body;
}

export async function refreshAccessToken(env=process.env, fetchImpl=fetch) {
  const client_id=env.CWS_CLIENT_ID;
  const client_secret=env.CWS_CLIENT_SECRET;
  const refresh_token=env.CWS_REFRESH_TOKEN;
  if (!client_id || !client_secret || !refresh_token) throw new Error('Missing CWS_CLIENT_ID/CWS_CLIENT_SECRET/CWS_REFRESH_TOKEN');
  const body=new URLSearchParams({client_id,client_secret,refresh_token,grant_type:'refresh_token'});
  const res=await fetchImpl(OAUTH,{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body});
  const data=await readJson(res);
  if (!data.access_token) throw new Error('OAuth response missing access_token');
  return data.access_token;
}

function auth(token){ return {Authorization:`Bearer ${token}`}; }

export async function fetchStatus({publisherId,extensionId,token,fetchImpl=fetch}) {
  return readJson(await fetchImpl(statusUrl(publisherId,extensionId),{headers:auth(token)}));
}
export async function uploadPackage({publisherId,extensionId,token,bytes,fetchImpl=fetch}) {
  if (!(bytes instanceof Uint8Array)) throw new Error('bytes must be Uint8Array');
  return readJson(await fetchImpl(uploadUrl(publisherId,extensionId),{
    method:'POST',headers:{...auth(token),'content-type':'application/zip'},body:bytes
  }));
}
export async function publishItem({publisherId,extensionId,token,fetchImpl=fetch}) {
  return readJson(await fetchImpl(publishUrl(publisherId,extensionId),{method:'POST',headers:auth(token)}));
}
export async function cancelSubmission({publisherId,extensionId,token,fetchImpl=fetch}) {
  return readJson(await fetchImpl(cancelUrl(publisherId,extensionId),{method:'POST',headers:auth(token)}));
}
