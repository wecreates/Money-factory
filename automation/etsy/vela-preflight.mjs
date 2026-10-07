import fs from 'node:fs/promises';
import {parseCsv,detectColumns} from './vela-merge.mjs';

export function preflight(rows,{expectedCount=59}={}){
  if(!rows.length) return {ok:false,errors:[{code:'EMPTY_CSV'}],warnings:[],summary:{rows:0}};
  const headers=rows[0];
  const c=detectColumns(headers);
  const errors=[], warnings=[];
  if(c.id<0) errors.push({code:'MISSING_ID_COLUMN'});
  if(c.title<0) errors.push({code:'MISSING_TITLE_COLUMN'});
  if(c.description<0) errors.push({code:'MISSING_DESCRIPTION_COLUMN'});
  if(c.price<0) errors.push({code:'MISSING_PRICE_COLUMN'});
  if(c.tags<0) errors.push({code:'MISSING_TAGS_COLUMN'});
  const ids=new Map();
  let dataRows=0;
  for(let i=1;i<rows.length;i++){
    const r=rows[i]; if(r.every(v=>!String(v||'').trim())) continue;
    dataRows++;
    const row=i+1;
    const id=c.id>=0?String(r[c.id]||'').trim():'';
    const title=c.title>=0?String(r[c.title]||'').trim():'';
    const desc=c.description>=0?String(r[c.description]||'').trim():'';
    const price=c.price>=0?String(r[c.price]||'').trim():'';
    const tags=c.tags>=0?String(r[c.tags]||'').split(',').map(x=>x.trim()).filter(Boolean):[];
    if(!id) errors.push({code:'MISSING_LISTING_ID',row});
    else ids.set(id,(ids.get(id)||0)+1);
    if(!title) errors.push({code:'BLANK_TITLE',row,id});
    if(title.length>140) errors.push({code:'TITLE_TOO_LONG',row,id,length:title.length});
    if(!desc) errors.push({code:'BLANK_DESCRIPTION',row,id});
    if(!price || !/^\d+(?:\.\d{1,2})?$/.test(price)) errors.push({code:'INVALID_PRICE',row,id,value:price});
    if(tags.length===0) errors.push({code:'BLANK_TAGS',row,id});
    if(tags.length>13) errors.push({code:'TOO_MANY_TAGS',row,id,count:tags.length});
    for(const tag of tags) if(tag.length>20) errors.push({code:'TAG_TOO_LONG',row,id,tag,length:tag.length});
    if(tags.length<13) warnings.push({code:'FEWER_THAN_13_TAGS',row,id,count:tags.length});
  }
  for(const [id,n] of ids) if(n>1) errors.push({code:'DUPLICATE_LISTING_ID',id,count:n});
  if(dataRows!==expectedCount) errors.push({code:'UNEXPECTED_ROW_COUNT',expected:expectedCount,actual:dataRows});
  return {ok:errors.length===0,errors,warnings,summary:{rows:dataRows,uniqueListingIds:ids.size,expectedCount}};
}

async function main(){
  const [file,expected='59']=process.argv.slice(2);
  if(!file) throw new Error('Usage: node vela-preflight.mjs <ready-import.csv> [expected-count]');
  const result=preflight(parseCsv(await fs.readFile(file,'utf8')),{expectedCount:Number(expected)});
  console.log(JSON.stringify(result,null,2));
  if(!result.ok) process.exitCode=2;
}
if(import.meta.url===new URL(process.argv[1],'file:').href) main();
