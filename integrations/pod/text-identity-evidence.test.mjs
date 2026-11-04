import test from 'node:test';
import assert from 'node:assert/strict';
import {validOpaqueText} from './text-identity.mjs';

test('opaque text rejects a Proxy options object without reading it',()=>{
 const calls={get:0};
 const options=new Proxy({maxLength:256},{get(target,name,receiver){calls.get++;return Reflect.get(target,name,receiver);}});
 assert.equal(validOpaqueText('evidence-id',options),false);
 assert.deepEqual(calls,{get:0});
});

test('opaque text rejects an options accessor without invoking it',()=>{
 const calls={get:0},options={};
 Object.defineProperty(options,'maxLength',{get(){calls.get++;return 256;}});
 assert.equal(validOpaqueText('evidence-id',options),false);
 assert.deepEqual(calls,{get:0});
});

test('opaque text rejects inherited options without invoking them',()=>{
 const calls={get:0},prototype={};
 Object.defineProperty(prototype,'maxLength',{get(){calls.get++;return 256;}});
 const options=Object.create(prototype);
 assert.equal(validOpaqueText('evidence-id',options),false);
 assert.deepEqual(calls,{get:0});
});

test('opaque text rejects coercible length evidence without invoking it',()=>{
 const calls={coerce:0};
 const maxLength={[Symbol.toPrimitive](){calls.coerce++;return 256;}};
 assert.equal(validOpaqueText('evidence-id',{maxLength}),false);
 assert.deepEqual(calls,{coerce:0});
});

test('opaque text preserves default and explicit inert length bounds',()=>{
 assert.equal(validOpaqueText('evidence-id'),true);
 assert.equal(validOpaqueText('four',{maxLength:4}),true);
 assert.equal(validOpaqueText('fives',{maxLength:4}),false);
 const options=Object.assign(Object.create(null),{maxLength:4});
 assert.equal(validOpaqueText('four',options),true);
});

test('opaque text rejects noncanonical primitive length bounds',()=>{
 for(const maxLength of [NaN,Infinity,-1,0.5,Number.MAX_SAFE_INTEGER+1,'256',null])
  assert.equal(validOpaqueText('evidence-id',{maxLength}),false);
});
