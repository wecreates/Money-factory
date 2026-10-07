import test from 'node:test';
import assert from 'node:assert/strict';
import {preflight} from '../vela-preflight.mjs';

test('passes a complete valid row',()=>{
  const rows=[
    ['Listing ID','Title','Description','Price','Tags'],
    ['123','Good title','Useful description','9.99','one,two,three']
  ];
  const r=preflight(rows,{expectedCount:1});
  assert.equal(r.ok,true);
  assert.equal(r.errors.length,0);
});

test('blocks missing IDs and duplicate IDs',()=>{
  const rows=[
    ['Listing ID','Title','Description','Price','Tags'],
    ['','A','D','1.00','one'],
    ['123','A','D','1.00','one'],
    ['123','B','D','1.00','one']
  ];
  const r=preflight(rows,{expectedCount:3});
  assert.equal(r.ok,false);
  assert.ok(r.errors.some(x=>x.code==='MISSING_LISTING_ID'));
  assert.ok(r.errors.some(x=>x.code==='DUPLICATE_LISTING_ID'));
});

test('blocks titles over 140 chars and tags over 20 chars',()=>{
  const rows=[
    ['Listing ID','Title','Description','Price','Tags'],
    ['123','x'.repeat(141),'D','1.00','this tag is definitely too long']
  ];
  const r=preflight(rows,{expectedCount:1});
  assert.equal(r.ok,false);
  assert.ok(r.errors.some(x=>x.code==='TITLE_TOO_LONG'));
  assert.ok(r.errors.some(x=>x.code==='TAG_TOO_LONG'));
});
