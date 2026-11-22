import {normalizeOrders} from './marketplaces.mjs';
import {importCatalog,inventoryPlan,supplierBlockers,economics} from './engine.mjs';
import {fulfillmentSummary} from './ledger.mjs';

// Account-independent composition: raw authored mock -> schema normalization ->
// supplier/quote/stock checks -> durable sandbox reservation. Never production evidence.
export async function ingestMockPage({mode,fixture_data,marketplace,account_id,response,catalog,suppliers,snapshots,mappings,now,ledger}) {
  if(mode!=='sandbox'||fixture_data!==true)throw Error('MOCK_SANDBOX_REQUIRED');
  const rows=importCatalog(catalog);
  const normalized=normalizeOrders(marketplace,account_id,response);
  const stock=inventoryPlan(rows,snapshots,[],now);
  const results=[];
  for(const order of normalized.orders){
    try{
      if(order.ready_to_route!==true)throw Error('ORDER_NOT_READY_FOR_FULFILLMENT');
      if(marketplace==='amazon'&&order.status!=='UNSHIPPED'||marketplace==='ebay'&&order.status!=='NOT_STARTED'||marketplace==='walmart'&&order.lines.some(l=>l.statuses.some(s=>!['Created','Acknowledged'].includes(s.status))))throw Error('EXISTING_FULFILLMENT_RECONCILIATION_REQUIRED');
      const lines=order.lines.map(line=>{
        const match=mappings.filter(m=>m.marketplace===marketplace&&m.account_id===account_id&&m.seller_sku===line.sku);
        if(match.length!==1)throw Error('UNIQUE_SKU_MAPPING_REQUIRED');
        const mapping=match[0];
        const row=rows.find(r=>r.supplier_id===mapping.supplier_id&&r.sku===mapping.supplier_sku);
        if(!row)throw Error('CATALOG_SKU_REQUIRED');
        const candidates=suppliers.filter(s=>s.id===row.supplier_id);
        if(candidates.length!==1)throw Error('UNIQUE_SUPPLIER_REQUIRED');
        const blockers=supplierBlockers(candidates[0],marketplace,row.sku,now);
        if(blockers.length)throw Error(blockers.join(','));
        // The ledger checks the fresh inventory ceiling under its lock after
        // identifying replays. Existing reservations need no additional stock.
        if(economics(row).projected_profit_cents<=0)throw Error('NONPOSITIVE_PROJECTED_MARGIN');
        return {line_id:line.line_id,supplier_id:row.supplier_id,sku:row.sku,quantity:line.quantity,unit_price_cents:row.price_cents};
      });
      const inventory_ceiling=stock.map(s=>({supplier_id:s.supplier_id,sku:s.sku,quantity:s.available}));
      const {state,changed}=await ledger.transactWithReceipt({type:'ingest',marketplace,account_id,order_id:order.order_id,lines,inventory_ceiling},{now});
      results.push({order_key:order.key,status:changed?'SIMULATED_RESERVED':'SIMULATED_REPLAY',reservation_created:changed,ledger_version:state.version,...fulfillmentSummary(state.orders[order.key])});
    }catch(error){results.push({order_key:order.key,status:'BLOCKED',reason:error.message});}
  }
  return {classification:'mock_pipeline',provider_validated:false,external_effects:0,results,next_cursor:normalized.next_cursor,page_complete:normalized.complete,poll_watermark_advanced:false};
}
