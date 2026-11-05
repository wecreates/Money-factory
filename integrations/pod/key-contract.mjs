export const MAX_POD_SHARED_KEY_BYTES=4096;

// POD keys cross HMAC and event-envelope boundaries. Require one exact UTF-8
// identity and bound its encoded bytes before any Buffer or crypto operation.
// NUL is never valid secret material, and lone UTF-16 surrogates are silently
// replaced during UTF-8 encoding. The upper bound is deliberately far above
// ordinary secret material while preventing unbounded configuration from
// reaching those APIs.
export function validPodSharedKey(value){
 if(typeof value!=='string')return false;
 const bytes=Buffer.byteLength(value);
 if(bytes<32||bytes>MAX_POD_SHARED_KEY_BYTES)return false;
 return !value.includes('\0')&&Buffer.from(value,'utf8').toString('utf8')===value;
}

// A bearer key is inserted verbatim into an HTTP Authorization field. Enforce
// the RFC 6750 b64token alphabet and terminal padding so proxies and clients do
// not reinterpret whitespace or header punctuation. Unicode remains supported
// for HMAC-only keys through validPodSharedKey.
export function validPodBearerKey(value){
 if(!validPodSharedKey(value))return false;
 let padding=false;
 for(let i=0;i<value.length;i++){
  const code=value.charCodeAt(i);
  if(code===0x3d){padding=true;continue;}
  if(padding||!((code>=0x30&&code<=0x39)||(code>=0x41&&code<=0x5a)||
   (code>=0x61&&code<=0x7a)||code===0x2d||code===0x2e||code===0x5f||
   code===0x7e||code===0x2b||code===0x2f))return false;
 }
 return true;
}
