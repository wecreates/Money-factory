import test from 'node:test';
import assert from 'node:assert/strict';
import {createPodAuthorityHandler} from './authority-handler.mjs';
import {createPodEventHandler} from './event-handler.mjs';
import {acceptPodEvent} from './event-inbox.mjs';
import {signPodGrant} from './sign-grant.mjs';

const oversized='x'.repeat(4097);

test('grant signing rejects an oversized shared key before HMAC work',()=>{
 assert.throws(()=>signPodGrant({schema_version:1,audience:'content-control:pod'},oversized),/KEY_REQUIRED/);
});

test('shared key upper bound is inclusive and counts encoded bytes',()=>{
 const payload={schema_version:1,audience:'content-control:pod'};
 assert.equal(signPodGrant(payload,'k'.repeat(4096)).signature.length,64);
 assert.throws(()=>signPodGrant(payload,'é'.repeat(2049)),/KEY_REQUIRED/);
});

test('event handler rejects an oversized shared key during construction',()=>{
 assert.throws(()=>createPodEventHandler({pool:{connect(){}},key:oversized}),/EVENT_HANDLER_CONFIG_INVALID/);
});

for(const field of ['authKey','signingKey'])test(`authority handler rejects an oversized ${field} during construction`,()=>{
 const config={loadSnapshot(){},authKey:'a'.repeat(32),signingKey:'s'.repeat(32)};
 config[field]=oversized;
 assert.throws(()=>createPodAuthorityHandler(config),/AUTHORITY_CONFIG_INVALID/);
});

test('direct event inbox rejects an oversized shared key before authentication',async()=>{
 await assert.rejects(acceptPodEvent({connect(){}},{payload:'',signature:'0'.repeat(64)},oversized),/EVENT_ENVELOPE_INVALID/);
});
