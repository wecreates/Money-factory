import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeWatch, evaluateCheck, dueForCheck, isMainEntry} from '../worker.mjs';

test('normalizeWatch accepts an active HTTPS watch',()=>{
  const w=normalizeWatch({id:'demo',kind:'change',targetUrl:'https://example.com/',label:'Demo',status:'active'});
  assert.equal(w.id,'demo');
  assert.equal(w.targetUrl,'https://example.com/');
  assert.equal(w.status,'active');
});

test('dueForCheck is true when no prior check exists',()=>{
  assert.equal(dueForCheck({status:'active',last_checked_at:null},Date.now(),300000),true);
});

test('dueForCheck honors cadence interval',()=>{
  const now=1_000_000;
  assert.equal(dueForCheck({status:'active',last_checked_at:now-299999},now,300000),false);
  assert.equal(dueForCheck({status:'active',last_checked_at:now-300000},now,300000),true);
});

test('evaluateCheck records baseline without false change event',()=>{
  const out=evaluateCheck({last_value:null,last_checked_at:null},{hash:'abc',checkedAt:123,status:200});
  assert.equal(out.changed,false);
  assert.equal(out.next.last_value,'abc');
  assert.equal(out.next.last_checked_at,123);
});

test('evaluateCheck flags changed content after baseline',()=>{
  const out=evaluateCheck({last_value:'abc',last_checked_at:100},{hash:'def',checkedAt:200,status:200});
  assert.equal(out.changed,true);
  assert.equal(out.next.last_value,'def');
  assert.equal(out.next.last_checked_at,200);
});


test('isMainEntry matches a file URL to the executable path',()=>{
  assert.equal(isMainEntry('file:///tmp/free-monitor/worker.mjs','/tmp/free-monitor/worker.mjs'),true);
  assert.equal(isMainEntry('file:///tmp/free-monitor/worker.mjs','/tmp/free-monitor/other.mjs'),false);
});


test('normalizeWatch preserves status metadata',()=>{
  const w=normalizeWatch({id:'demo2',targetUrl:'https://example.com/',status:'active',last_status:200});
  assert.equal(w.last_status,200);
});
