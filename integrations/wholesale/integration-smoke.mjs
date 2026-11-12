import {readFile,mkdtemp,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {SandboxLedger,retryPlan} from './ledger.mjs';
import {inventoryPlan} from './engine.mjs';
import {ingestMockPage} from './pipeline.mjs';
import {shipmentRequest,inventoryRequest} from './marketplaces.mjs';

export async function integrationSmoke(input) {
 if(input.mode!=='sandbox'||input.fixture_data!==true)throw Error('MOCK_SANDBOX_REQUIRED');
 const mocks=JSON.parse(await readFile(new URL('./mock-responses.json',import.meta.url),'utf8'));
 const dir=await mkdtemp(join(tmpdir(),'wholesale-smoke-'));
 try {
  const path=join(dir,'ledger.json'),ledger=new SandboxLedger(path);
  await ledger.initialize({inventory:inventoryPlan(input.catalog,input.snapshots,[],input.now).map(s=>({...s,quantity:s.available}))});
  const pages=[];
  for(const marketplace of ['amazon','walmart','ebay']){
   pages.push(await ingestMockPage({...input,marketplace,account_id:'MOCK-ACCOUNT',response:mocks[marketplace],ledger,mappings:[{marketplace,account_id:'MOCK-ACCOUNT',seller_sku:'DEMO-001',supplier_id:'SYNTHETIC-ONLY',supplier_sku:'DEMO-001'}]}));
  }
  if(pages.some(p=>p.results.some(r=>r.status!=='SIMULATED_RESERVED')))throw Error('MOCK_PIPELINE_BLOCKED');
  const before=await ledger.read(),order=Object.values(before.orders).find(o=>o.marketplace==='amazon');
  const identity={marketplace:'amazon',account_id:order.account_id,order_id:order.order_id},line_id=order.lines[0].line_id;
  const shipment={type:'ship',identity,package_id:'1',carrier:'UPS',tracking_number:'MOCK-NOT-REAL',tendered_at_ms:input.now,evidence_id:'MOCK-TENDER',lines:[{line_id,quantity:1}]};
  await ledger.transact(shipment,{now:input.now});
  await new SandboxLedger(path).transact(shipment,{now:input.now}); // restart replay is a no-op
  await ledger.transact({type:'cancel',identity,evidence_id:'MOCK-CANCEL',lines:[{line_id,quantity:1}]});
  await ledger.transact({type:'return',identity,return_id:'MOCK-RECEIVED-RETURN',lines:[{line_id,quantity:1}]});
  await ledger.transact({type:'refund',identity,refund_id:'MOCK-REFUND',amount_cents:input.catalog[0].price_cents});
  const final=await new SandboxLedger(path).read();
  const available=Object.values(final.inventory)[0];
  // Split the shared pool for previews. Never advertise the whole pool on all channels.
  const amounts=[Math.ceil(available/3),Math.floor((available+1)/3),Math.floor(available/3)];
  const inventory_previews=['amazon','walmart','ebay'].map((p,i)=>inventoryRequest(p,{sku:'DEMO-001',quantity:amounts[i],seller_id:'MOCK-SELLER',marketplace_id:'ATVPDKIKX0DER',product_type:'MOCK_PRODUCT_TYPE',schema_evidence_id:'MOCK-SCHEMA-NOT-VALIDATED'}));
  return {schema_version:1,mode:'sandbox',classification:'AUTHORED_MOCK_INTEGRATION',fixture_data:true,publication_enabled:false,orders_placed:0,financial_transactions:0,verified_revenue_cents:0,provider_validated:false,
   pages,state:final,inventory_previews,
   shipment_preview:shipmentRequest('amazon',{...shipment,order_id:identity.order_id,remaining:[{line_id,quantity:2}],marketplace_id:'ATVPDKIKX0DER',now:input.now}),
   retry_example:retryPlan({method:'POST',status:503}),
   scope:'Local schema/policy/ledger composition and request previews; no provider response, account or deployment validation'};
 }finally{await rm(dir,{recursive:true,force:true});}
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
 try{const [source,output]=process.argv.slice(2);if(!source||!output)throw Error('Usage: node integration-smoke.mjs input.json NEW-output.json');
  const result=await integrationSmoke(JSON.parse(await readFile(source,'utf8')));await writeFile(output,JSON.stringify(result,null,2)+'\n',{flag:'wx'});console.log('Mock integration receipt written; zero external calls');
 }catch(error){console.error(error.message);process.exitCode=1;}
}
