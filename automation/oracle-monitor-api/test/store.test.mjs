import test from 'node:test';
import assert from 'node:assert/strict';
import {createStore,createWatch,listWatches,deleteWatch,listEvents} from '../store.mjs';

test('createWatch persists an active watch with null timestamps',()=>{
  const store=createStore();
  const w=createWatch(store,{clientId:'c1',kind:'change',targetUrl:'https://example.com/',label:'Demo'});
  assert.equal(w.status,'active');
  assert.equal(w.last_checked_at,null);
  assert.equal(listWatches(store,'c1').length,1);
});

test('watch lists are isolated by clientId',()=>{
  const store=createStore();
  createWatch(store,{clientId:'a',kind:'change',targetUrl:'https://a.example/',label:'A'});
  createWatch(store,{clientId:'b',kind:'change',targetUrl:'https://b.example/',label:'B'});
  assert.equal(listWatches(store,'a').length,1);
  assert.equal(listWatches(store,'b').length,1);
});

test('deleteWatch only deletes a matching client watch',()=>{
  const store=createStore();
  const w=createWatch(store,{clientId:'a',kind:'change',targetUrl:'https://example.com/',label:'A'});
  assert.equal(deleteWatch(store,'b',w.id),false);
  assert.equal(deleteWatch(store,'a',w.id),true);
  assert.equal(listWatches(store,'a').length,0);
});

test('events default to an empty list',()=>{
  const store=createStore();
  assert.deepEqual(listEvents(store,'a'),[]);
});
