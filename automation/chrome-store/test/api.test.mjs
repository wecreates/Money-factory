import test from 'node:test';
import assert from 'node:assert/strict';
import {statusUrl,uploadUrl,publishUrl,cancelUrl,refreshAccessToken} from '../api.mjs';

const p='publisher123', e='abcdefghijklmnopabcdefghijklmnop';
test('builds v2 status url',()=>assert.equal(statusUrl(p,e),'https://chromewebstore.googleapis.com/v2/publishers/publisher123/items/'+e+':fetchStatus'));
test('builds v2 upload url',()=>assert.equal(uploadUrl(p,e),'https://chromewebstore.googleapis.com/upload/v2/publishers/publisher123/items/'+e+':upload'));
test('builds v2 publish url',()=>assert.equal(publishUrl(p,e),'https://chromewebstore.googleapis.com/v2/publishers/publisher123/items/'+e+':publish'));
test('builds v2 cancel url',()=>assert.equal(cancelUrl(p,e),'https://chromewebstore.googleapis.com/v2/publishers/publisher123/items/'+e+':cancelSubmission'));
test('refresh requires secrets',async()=>await assert.rejects(()=>refreshAccessToken({},async()=>{}),/Missing CWS_/));
