export const MAX_POD_SHARED_KEY_BYTES=4096;

// POD keys cross HTTP authentication, HMAC and event-envelope boundaries.
// Require a primitive string and bound its encoded bytes before any Buffer or
// crypto operation. The upper bound is deliberately far above ordinary secret
// material while preventing unbounded configuration from reaching those APIs.
export function validPodSharedKey(value){
 if(typeof value!=='string')return false;
 const bytes=Buffer.byteLength(value);
 return bytes>=32&&bytes<=MAX_POD_SHARED_KEY_BYTES;
}
