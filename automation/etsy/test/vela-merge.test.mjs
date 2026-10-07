import test from 'node:test';
import assert from 'node:assert/strict';
import {parseCsv, stringifyCsv, detectColumns, mergeRows} from '../vela-merge.mjs';

test('round-trips quoted multiline CSV',()=>{
  const csv='Listing ID,Title,Description\r\n123,"Old, title","Line 1\nLine 2"\r\n';
  const rows=parseCsv(csv);
  assert.equal(rows[1][1],'Old, title');
  assert.equal(rows[1][2],'Line 1\nLine 2');
  assert.deepEqual(parseCsv(stringifyCsv(rows)),rows);
});

test('detects common Vela column aliases',()=>{
  const m=detectColumns(['Listing ID','Title','Description','Price','Tags']);
  assert.equal(m.id,0); assert.equal(m.title,1); assert.equal(m.description,2);
  assert.equal(m.price,3); assert.equal(m.tags,4);
});

test('merges by listing id and preserves untouched Vela columns',()=>{
  const vela=[
    ['Listing ID','Title','Description','Price','Tags','Quantity'],
    ['123','Old','old desc','5.00','old,tag','99']
  ];
  const patch=[{listing_id:'123',title:'New',description:'new desc',price:'9.99',tags:['one','two']}];
  const out=mergeRows(vela,patch);
  assert.equal(out.rows[1][1],'New');
  assert.equal(out.rows[1][2],'new desc');
  assert.equal(out.rows[1][3],'9.99');
  assert.equal(out.rows[1][4],'one,two');
  assert.equal(out.rows[1][5],'99');
  assert.equal(out.report.updated,1);
  assert.equal(out.report.unmatchedPatches.length,0);
});

test('reports duplicate IDs and missing patch rows instead of silently guessing',()=>{
  const vela=[
    ['Listing ID','Title'],
    ['123','A'],
    ['123','B']
  ];
  const out=mergeRows(vela,[{listing_id:'999',title:'X'}]);
  assert.deepEqual(out.report.duplicateIds,['123']);
  assert.deepEqual(out.report.unmatchedPatches,['999']);
});
