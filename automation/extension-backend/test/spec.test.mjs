import test from 'node:test';
import assert from 'node:assert/strict';
import {API,VERIFY,KINDS,clientId,watchPayload,resolveMonitorApi} from '../spec.mjs';

test('defaults monitor API to the verified free Render endpoint',()=>{
 assert.equal(API,'https://content-control-render-worker.onrender.com/api/v1/ext');
 assert.equal(VERIFY,'https://cyzorcreations.com/tools/pro/verify');
});

test('monitor API can be rolled back with an environment override',()=>{
 assert.equal(resolveMonitorApi({CYZOR_MONITOR_API:'https://cyzorcreations.com/api/v1/ext'}),'https://cyzorcreations.com/api/v1/ext');
});

test('smoke kinds cover monitor products',()=>assert.deepEqual(KINDS,['change','hiring','price']));

test('smoke payload is isolated and harmless',()=>{
 const c=clientId(123);
 const p=watchPayload(c,'price');
 assert.equal(c,'cyzor-release-smoke-123');
 assert.equal(p.targetUrl,'https://example.com/');
 assert.equal(p.clientId,c);
});
