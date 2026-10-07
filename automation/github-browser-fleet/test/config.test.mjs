
import test from 'node:test';
import assert from 'node:assert/strict';
import {selectBusinesses} from '../src/config.mjs';

const cfg={businesses:[
 {id:'a',enabled:true,schedule_group:'frequent'},
 {id:'b',enabled:true,schedule_group:'normal'},
 {id:'c',enabled:false,schedule_group:'frequent'}
]};
test('filters enabled',()=>assert.deepEqual(selectBusinesses(cfg).map(x=>x.id),['a','b']));
test('filters schedule group',()=>assert.deepEqual(selectBusinesses(cfg,{group:'frequent'}).map(x=>x.id),['a']));
test('filters one business',()=>assert.deepEqual(selectBusinesses(cfg,{only:'b'}).map(x=>x.id),['b']));
