
import test from 'node:test';
import assert from 'node:assert/strict';
import {validateTask} from '../src/task.mjs';

test('accepts listing update',()=>{
  const t=validateTask({id:'x',type:'update_listing',listing_id:'123',patch:{title:'A',tags:['a']}});
  assert.equal(t.listing_id,'123');
});
test('rejects too many tags',()=>{
  assert.throws(()=>validateTask({id:'x',type:'update_listing',listing_id:'123',patch:{tags:Array(14).fill('x')}}));
});
test('rejects bad listing id',()=>{
  assert.throws(()=>validateTask({id:'x',type:'update_listing',listing_id:'abc',patch:{}}));
});
