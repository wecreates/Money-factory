import test from 'node:test';
import assert from 'node:assert/strict';
import {columns,parseCatalogCsv} from './catalog-csv.mjs';
const header=columns.join(',');
const line='demo,SKU-1,USD,3000,1000,200,0,0,1500,30,0,500,1792587600000,1';
test('CSV imports CRLF, BOM, escaped quoted SKU and exact cents',()=>{
  const rows=parseCatalogCsv('\uFEFF'+header+'\r\n'+line.replace('SKU-1','"SKU,""1"""')+'\r\n');
  assert.equal(rows[0].sku,'SKU,"1"');assert.equal(rows[0].price_cents,3000);
});
test('CSV rejects malformed values, duplicates, headers and quote syntax',()=>{
  for(const text of [header+'\n'+line+'\n'+line,header+'\n'+line.replace('3000','NaN'),header+'\n'+line.replace('3000','-1'),header+'\n'+line.replace('3000','1.2'),header+'\n'+line.replace('SKU-1','"unfinished'),header+'\n'+line.replace('SKU-1','"sku"extra'),'wrong\n'+line])assert.throws(()=>parseCatalogCsv(text));
});
