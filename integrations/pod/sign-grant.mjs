import crypto from 'node:crypto';
export function signPodGrant(payload,key){
 if(typeof key!=='string'||Buffer.byteLength(key)<32)throw Error('KEY_REQUIRED');
 if(payload?.schema_version!==1||payload.audience!=='content-control:pod')throw Error('GRANT_SCHEMA_INVALID');
 const body=JSON.stringify(payload);
 return {payload:body,signature:crypto.createHmac('sha256',key).update(body).digest('hex')};
}
// Call only from MF's authoritative readiness/approval service. This helper does not grant permission.
