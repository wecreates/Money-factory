import test from 'node:test';
import assert from 'node:assert/strict';
import {API,VERIFY,KINDS,clientId,watchPayload} from '../spec.mjs';
test('uses production CYZOR routes',()=>{
 assert.equal(API,'https://cyzorcreations.com/api/v1/ext');
 assert.equal(VERIFY,'https://cyzorcreations.com/tools/pro/verify');
});
test('smoke kinds cover monitor products',()=>assert.deepEqual(KINDS,['change','hiring','price']));
test('smoke payload is isolated and harmless',()=>{
 const c=clientId(123);
 const p=watchPayload(c,'price');
 assert.equal(c,'cyzor-release-smoke-123');
 assert.equal(p.targetUrl,'https://example.com/');
 assert.equal(p.clientId,c);
});
