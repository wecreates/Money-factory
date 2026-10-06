import test from 'node:test';
import assert from 'node:assert/strict';
import {patchFromRebuild,normalizeTags,titleFor} from '../patches.mjs';

test('all patches are forced to digital download',()=>{
  const p=patchFromRebuild({listing_id:'1',new_product:'Test Product',category:'digital_planner',conversion_priority:9});
  assert.equal(p.type,'download');
});

test('tags are Etsy-safe',()=>{
  for(const category of ['digital_planner','business_finance','finance_spreadsheet','kawaii_digital_stickers','digital_wall_art_bundle']){
    const tags=normalizeTags(category);
    assert.equal(tags.length,13);
    assert.ok(tags.every(t=>t.length<=20));
  }
});

test('titles stay readable and bounded',()=>{
  const t=titleFor('A '.repeat(100)+'Digital Planner');
  assert.ok(t.length<=118);
});

test('patch includes 13 tags and price',()=>{
  const p=patchFromRebuild({listing_id:'99',new_product:'ADHD Digital Planner + Printable Focus System',category:'digital_planner',conversion_priority:9.6});
  assert.equal(p.tags.length,13);
  assert.equal(p.price,9.99);
  assert.match(p.description,/NO PHYSICAL ITEM/);
});
