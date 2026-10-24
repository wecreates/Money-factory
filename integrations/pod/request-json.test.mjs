import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {parsePodRequestJSON} from './request-json.mjs';
import {acceptPodEvent} from './event-inbox.mjs';
const parse=text=>parsePodRequestJSON(Buffer.from(text));
const key='j'.repeat(32),now=1800000000000,id='12b4c678-1234-4321-abcd-123456789abc';
const signed=payload=>({payload,signature:crypto.createHmac('sha256',key).update(payload).digest('hex')});
const payload=fields=>`{"schema_version":1,"audience":"money-factory:pod:event","issued_at_ms":${now},"event":{"id":"${id}","kind":"pod.test.json","payload":{${fields}}}}`;

test('duplicate JSON member names are rejected at every object depth after escape decoding',()=>{
 for(const text of [
  '{"job_id":"other","job_id":"job"}', '{"job_id":"job","job_id":"job"}',
  '{"job_id":"other","job_\\u0069d":"job"}', '{"nested":[{"x":1,"x":2}]}',
  '{"__proto__":1,"__proto__":2}', '{"":0,"":1}',
  '{"a\\\"b":0,"a\\u0022b":1}', '{"café":0,"caf\\u00e9":1}'
 ])assert.throws(()=>parse(text),{name:'SyntaxError',message:'REQUEST_JSON_DUPLICATE_KEY'},text);
});
test('overflowing JSON numbers cannot silently become null on reserialization',()=>{
 for(const text of ['1e400','-1e400','{"amount":1e400}','[0,{"amount":-1e400}]'])
  assert.throws(()=>parse(text),{name:'SyntaxError',message:'REQUEST_JSON_NONFINITE'},text);
 for(const text of ['NaN','Infinity','-Infinity','{"n":NaN}'])assert.throws(()=>parse(text),SyntaxError);
});
test('unsafe JSON integers cannot be rounded before signed event storage',()=>{
 for(const text of ['9007199254740992','-9007199254740992','9.007199254740992e15',
  '{"amount":9007199254740993}','[0,{"amount":-9007199254740993}]'])
  assert.throws(()=>parse(text),{name:'SyntaxError',message:'REQUEST_JSON_UNSAFE_INTEGER'},text);
 for(const text of ['9007199254740991','-9007199254740991','1.5','1e-7'])assert.deepEqual(parse(text),JSON.parse(text));
});
test('noncanonical JSON numbers cannot change identity before signed event storage',()=>{
 for(const text of ['-0','1e-400','-1e-400','1.0','1e0','1.2300','0.100000000000000005',
  '{"amount":1e-400}','[0,{"amount":0.100000000000000005}]'])
  assert.throws(()=>parse(text),{name:'SyntaxError',message:'REQUEST_JSON_NONCANONICAL_NUMBER'},text);
 for(const text of ['0','1','1.5','0.1','1e-7','0.000001'])assert.deepEqual(parse(text),JSON.parse(text));
});
test('finite JSON, Unicode and quoted punctuation retain native JSON meaning',()=>{
 const text=String.raw`{"a":{"x":1},"b":{"x":2},"list":[{},[],null,true,false,0,1.5,1e-7],"note":"café 🖨️ {,}: \\ \" x","escaped":"\u0061","__proto__":{"ok":true}}`;
 assert.deepEqual(parse(text),JSON.parse(text));
 assert.equal(Object.hasOwn(parse(text),'__proto__'),true);
 for(const text of ['0','"text"','null','true','[]','{}',' \n {"x":1} \t '])assert.deepEqual(parse(text),JSON.parse(text));
});
test('deep valid JSON does not add a recursive validation stack limit',()=>{
 const text='['.repeat(10000)+'{"x":1}'+']'.repeat(10000);
 let value=parse(text);for(let i=0;i<10000;i++)value=value[0];assert.equal(value.x,1);
});
test('signed duplicate fields and nonfinite values fail before any database acquisition',async()=>{
 let connects=0;const pool={connect:async()=>{connects++;throw Error('UNEXPECTED_DATABASE_ACCESS');}};
 for(const fields of ['"approved":false,"approved":true','"x":1,"\\u0078":2','"amount":1e400',
  '"amount":9007199254740993','"amount":1e-400','"amount":0.100000000000000005',
  '"nested":[{"x":1,"x":2}]'])
  await assert.rejects(acceptPodEvent(pool,signed(payload(fields)),key,()=>now),SyntaxError);
 assert.equal(connects,0);
});
test('signature authentication still precedes parsing of the signed payload',async()=>{
 const pool={connect:async()=>{throw Error('UNEXPECTED_DATABASE_ACCESS');}};
 await assert.rejects(acceptPodEvent(pool,{payload:'{bad',signature:'0'.repeat(64)},key,()=>now),/EVENT_SIGNATURE_INVALID/);
});
