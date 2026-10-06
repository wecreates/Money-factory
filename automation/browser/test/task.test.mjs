import test from 'node:test';
import assert from 'node:assert/strict';
import { validateTask, sanitizeUrl, compileActions } from '../src/task.mjs';

test('accepts a safe inspect task', () => {
  const t = validateTask({ id:'smoke', type:'inspect', url:'https://example.com', actions:[] });
  assert.equal(t.id, 'smoke');
  assert.equal(t.type, 'inspect');
});

test('rejects javascript and file urls', () => {
  assert.throws(() => sanitizeUrl('javascript:alert(1)'));
  assert.throws(() => sanitizeUrl('file:///etc/passwd'));
});

test('rejects credential-like fill fields', () => {
  assert.throws(() => compileActions([{type:'fill', label:'Password', value:'secret'}]));
  assert.throws(() => compileActions([{type:'fill', label:'OTP code', value:'123456'}]));
});

test('accepts bounded public actions', () => {
  const a = compileActions([
    {type:'click', text:'More information'},
    {type:'wait', ms:1000},
    {type:'extract', selector:'main'}
  ]);
  assert.equal(a.length, 3);
});

test('accepts link extraction action', () => {
  const a = compileActions([{type:'links', selector:'a'}]);
  assert.equal(a[0].type, 'links');
});

test('rejects oversized link selector', () => {
  assert.throws(() => compileActions([{type:'links', selector:'a'.repeat(201)}]));
});

test('accepts multi-inspect pages', () => {
  const t = validateTask({
    id:'batch',
    type:'multi-inspect',
    pages:[
      {id:'a',url:'https://example.com/a'},
      {id:'b',url:'https://example.com/b'}
    ]
  });
  assert.equal(t.pages.length, 2);
  assert.equal(t.pages[0].id, 'a');
});

test('rejects too many multi-inspect pages', () => {
  assert.throws(() => validateTask({
    id:'batch',
    type:'multi-inspect',
    pages:Array.from({length:51},(_,i)=>({id:'p'+i,url:'https://example.com/'+i}))
  }));
});
