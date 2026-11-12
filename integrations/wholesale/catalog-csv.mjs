import {readFile,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {importCatalog} from './engine.mjs';
export const columns=['supplier_id','sku','currency','price_cents','cost_cents','shipping_cents','handling_cents','tax_cents','fee_bps','fixed_fee_cents','min_fee_cents','return_reserve_bps','quote_expires_at_ms','safety_stock'];
// Strict RFC-style quoted CSV. Reject stray quotes and unexpected columns.
export function parseCatalogCsv(text) {
  const rows=[]; let row=[],field='',quoted=false,closed=false;
  text=text.replace(/^\uFEFF/,'');
  for(let i=0;i<text.length;i++) {
    const c=text[i];
    if(quoted){if(c==='"'){if(text[i+1]==='"'){field+='"';i++;}else{quoted=false;closed=true;}}else field+=c;continue;}
    if(c==='"'){if(field||closed)throw Error('Malformed CSV quote');quoted=true;continue;}
    if(c===','||c==='\r'||c==='\n'){
      row.push(field);field='';closed=false;
      if(c!==','){rows.push(row);row=[];if(c==='\r'&&text[i+1]==='\n')i++;}continue;
    }
    if(closed)throw Error('Characters after CSV quote');field+=c;
  }
  if(quoted)throw Error('Unclosed CSV quote');
  if(field||closed||row.length){row.push(field);rows.push(row);}
  if(JSON.stringify(rows.shift())!==JSON.stringify(columns))throw Error('CSV header mismatch');
  const parsed=rows.map((values,index)=>{
    if(values.length!==columns.length)throw Error(`CSV row ${index+2} field count`);
    return Object.fromEntries(columns.map((name,i)=>{
      if(i<3)return[name,values[i]];
      if(!/^\d+$/.test(values[i]))throw Error(`CSV row ${index+2} invalid ${name}`);
      return[name,Number(values[i])];
    }));
  });
  return importCatalog(parsed);
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  try{const [source,destination]=process.argv.slice(2);if(!source||!destination)throw Error('Usage: node catalog-csv.mjs catalog.csv NEW-catalog.json');
    const result=parseCatalogCsv(await readFile(source,'utf8'));await writeFile(destination,JSON.stringify(result,null,2)+'\n',{flag:'wx'});console.log(`Imported ${result.length} rows; no publication`);
  }catch(error){console.error(error.message);process.exitCode=1;}
}
