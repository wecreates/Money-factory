import crypto from 'node:crypto';
import {copyAuthoritySnapshot} from './authority-evidence.mjs';
import {validPodSharedKey} from './key-contract.mjs';
const MAX_GRANT_PAYLOAD_BYTES=262144;
export function signPodGrant(payload,key){
 if(!validPodSharedKey(key))throw Error('KEY_REQUIRED');
 payload=copyAuthoritySnapshot(payload);
 if(payload?.schema_version!==1||payload.audience!=='content-control:pod')throw Error('GRANT_SCHEMA_INVALID');
 const body=JSON.stringify(payload);
 // Snapshot text budgets exclude JSON framing and numeric tokens. Bound the
 // actual wire payload before HMAC to match Content Control verifyEnvelope.
 if(Buffer.byteLength(body)>MAX_GRANT_PAYLOAD_BYTES)throw Error('GRANT_PAYLOAD_TOO_LARGE');
 return {payload:body,signature:crypto.createHmac('sha256',key).update(body).digest('hex')};
}
// Call only from MF's authoritative readiness/approval service. This helper does not grant permission.
