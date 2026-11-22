import {readFile, writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {importCatalog, economics, inventoryPlan, supplierBlockers, SandboxOrders} from './engine.mjs';

export function run(input) {
  if (input.mode !== 'sandbox') throw Error('Only sandbox execution is implemented');
  if (!Number.isSafeInteger(input.now) || input.now < 0) throw Error('Explicit simulation clock required');
  const catalog = importCatalog(input.catalog);
  const orders = new SandboxOrders({...input, catalog});
  const results = [];
  const actions = new Set(['accept','track','requestCancel','confirmCancel','denyCancel','requestReturn','authorizeReturn','receiveReturn','refund']);
  for (const command of input.commands ?? []) {
    if(command.action === 'route') results.push(orders.route(command.order));
    else if(command.action === 'syncInventory') results.push(orders.syncInventory(command.snapshots,command.now));
    else if(actions.has(command.action)) results.push(orders[command.action](command.id, command.value));
    else throw Error('Unsupported sandbox action');
  }
  return {schema_version:1, lane:'wholesale', mode:'sandbox', fixture_data:true,
    publication_enabled:false, orders_placed:0, financial_transactions:0, verified_revenue_cents:0,
    simulation_clock_ms:input.now,
    estimates:catalog.map(row=>({supplier_id:row.supplier_id,sku:row.sku,...economics(row)})),
    initial_inventory:inventoryPlan(catalog,input.snapshots,[],input.now),
    supplier_checks:catalog.flatMap(row=>['amazon','walmart','ebay'].map(marketplace=>({
      marketplace,sku:row.sku, blockers:supplierBlockers(input.suppliers.find(s=>s.id===row.supplier_id),marketplace,row.sku,input.now)
    }))),
    state:orders.snapshot(), command_results:results,
    production_blockers:['Owner marketplace verification and approved API access','Verified supplier agreement and channel/SKU authorization','Real catalog, current landed-cost quotes and inventory feeds','Authenticated durable production adapter and reconciliation not implemented']};
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const [inputPath, outputPath] = process.argv.slice(2);
    if (!inputPath || !outputPath) throw Error('Usage: node run.mjs input.json NEW-output.json');
    const report = run(JSON.parse(await readFile(inputPath,'utf8')));
    await writeFile(outputPath,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
    console.log(`Sandbox receipt written: ${outputPath}; no external actions`);
  } catch(error) { console.error(error.message); process.exitCode=1; }
}
