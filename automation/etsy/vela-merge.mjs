import fs from 'node:fs/promises';

export function parseCsv(text){
  const rows=[]; let row=[], field='', q=false;
  for(let i=0;i<text.length;i++){
    const ch=text[i];
    if(q){
      if(ch==='"' && text[i+1]==='"'){field+='"'; i++;}
      else if(ch==='"') q=false;
      else field+=ch;
    } else {
      if(ch==='"') q=true;
      else if(ch===','){row.push(field); field='';}
      else if(ch==='\n'){row.push(field.replace(/\r$/,'')); rows.push(row); row=[]; field='';}
      else field+=ch;
    }
  }
  if(field.length || row.length){row.push(field.replace(/\r$/,'')); rows.push(row);}
  return rows;
}

function quote(v=''){
  const s=String(v??'');
  return /[",\r\n]/.test(s)?'"'+s.replaceAll('"','""')+'"':s;
}
export function stringifyCsv(rows){return rows.map(r=>r.map(quote).join(',')).join('\r\n')+'\r\n';}

function norm(s){return String(s||'').trim().toLowerCase().replace(/[^a-z0-9]+/g,' ');}
function find(headers,aliases){
  const n=headers.map(norm);
  for(const a of aliases){
    const i=n.indexOf(norm(a)); if(i>=0) return i;
  }
  return -1;
}

export function detectColumns(headers){
  return {
    id:find(headers,['Listing ID','ListingID','Etsy Listing ID','listing_id','ID']),
    title:find(headers,['Title','Listing Title']),
    description:find(headers,['Description','Listing Description']),
    price:find(headers,['Price','Listing Price']),
    tags:find(headers,['Tags','Tag','Listing Tags']),
    type:find(headers,['Type','Listing Type','Digital/Physical','Digital']),
    section:find(headers,['Section','Shop Section','Section Name']),
    state:find(headers,['State','Status','Listing State'])
  };
}

function normalizePatch(p){
  const tags=Array.isArray(p.tags)?p.tags.join(','):p.tags;
  return {
    listing_id:String(p.listing_id??p['Listing ID']??'').trim(),
    title:p.title??p.Title,
    description:p.description??p.Description,
    price:p.price??p.Price,
    tags
  };
}

export function mergeRows(velaRows,patchInput){
  if(!velaRows.length) throw new Error('Vela CSV is empty');
  const headers=velaRows[0];
  const cols=detectColumns(headers);
  if(cols.id<0) throw new Error('Could not find Vela Listing ID column');
  const patchRows=patchInput.map(normalizePatch).filter(p=>p.listing_id);
  const patchMap=new Map(patchRows.map(p=>[p.listing_id,p]));

  const seen=new Map();
  for(let i=1;i<velaRows.length;i++){
    const id=String(velaRows[i][cols.id]??'').trim();
    if(id) seen.set(id,(seen.get(id)||0)+1);
  }
  const duplicateIds=[...seen.entries()].filter(([,n])=>n>1).map(([id])=>id).sort();

  let updated=0;
  const matched=new Set();
  const rows=velaRows.map((r,i)=>{
    if(i===0) return [...r];
    const out=[...r];
    while(out.length<headers.length) out.push('');
    const id=String(out[cols.id]??'').trim();
    const p=patchMap.get(id);
    if(!p) return out;
    matched.add(id);
    if(cols.title>=0 && p.title!=null) out[cols.title]=String(p.title);
    if(cols.description>=0 && p.description!=null) out[cols.description]=String(p.description);
    if(cols.price>=0 && p.price!=null) out[cols.price]=String(p.price);
    if(cols.tags>=0 && p.tags!=null) out[cols.tags]=String(p.tags);
    updated++;
    return out;
  });

  const unmatchedPatches=[...patchMap.keys()].filter(id=>!matched.has(id)).sort();
  const unpatchedVela=[...seen.keys()].filter(id=>!patchMap.has(id)).sort();
  return {rows,report:{updated,totalVelaRows:Math.max(0,velaRows.length-1),patchCount:patchRows.length,duplicateIds,unmatchedPatches,unpatchedVela,columns:cols}};
}

function patchFromCsv(rows){
  if(!rows.length) return [];
  const h=rows[0], c=detectColumns(h);
  if(c.id<0) throw new Error('Patch CSV missing Listing ID column');
  return rows.slice(1).map(r=>({
    listing_id:r[c.id],
    title:c.title>=0?r[c.title]:undefined,
    description:c.description>=0?r[c.description]:undefined,
    price:c.price>=0?r[c.price]:undefined,
    tags:c.tags>=0?r[c.tags]:undefined
  }));
}

async function main(){
  const args=process.argv.slice(2);
  const get=(name)=>{const i=args.indexOf(name); return i>=0?args[i+1]:null;};
  const velaPath=get('--vela'), patchPath=get('--patch'), outPath=get('--out')||'VELA-READY-IMPORT.csv', reportPath=get('--report')||'VELA-MERGE-QA.json';
  if(!velaPath||!patchPath) throw new Error('Usage: node vela-merge.mjs --vela <vela-export.csv> --patch <cyzor-patch.csv|json> [--out file.csv] [--report qa.json]');
  const vela=parseCsv(await fs.readFile(velaPath,'utf8'));
  let patch;
  if(patchPath.toLowerCase().endsWith('.json')){
    const j=JSON.parse(await fs.readFile(patchPath,'utf8'));
    patch=j.items||j.replacements||j.flagship||j.extensions||j;
    if(!Array.isArray(patch)) throw new Error('Patch JSON must contain an array (items/replacements/flagship) or be an array');
  } else patch=patchFromCsv(parseCsv(await fs.readFile(patchPath,'utf8')));
  const merged=mergeRows(vela,patch);
  await fs.writeFile(outPath,stringifyCsv(merged.rows));
  await fs.writeFile(reportPath,JSON.stringify(merged.report,null,2)+'\n');
  console.log(JSON.stringify({outPath,reportPath,...merged.report},null,2));
  if(merged.report.duplicateIds.length || merged.report.unmatchedPatches.length) process.exitCode=2;
}

if(import.meta.url===new URL(process.argv[1], 'file:').href) main();
