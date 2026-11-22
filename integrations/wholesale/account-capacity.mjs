// Offline planning only. Seller snapshot declarations are not authenticated evidence.
// Insertion-fee allowance and increase-request anecdotes never enter this calculation.
export function accountCapacity(account,plan,catalog,inventory,now){
 const blockers=[],add=code=>blockers.push(code),limit=account?.selling_limits;
 const integer=x=>Number.isSafeInteger(x)&&x>=0;
 if(!integer(now))throw Error('INVALID_CLOCK');
 if(limit?.classification!=='declared_seller_snapshot'||!limit.evidence_ref||limit.account_id!==account?.account_id||!account?.account_id||limit.currency!=='USD')add('SELLER_LIMIT_SNAPSHOT_REQUIRED');
 if(!integer(limit?.observed_at_ms)||limit.observed_at_ms>now||now-limit.observed_at_ms>86400000||!integer(limit?.period_end_ms)||limit.period_end_ms<=now)add('CURRENT_SELLER_LIMIT_SNAPSHOT_REQUIRED');
 const fields=['max_quantity','used_quantity','max_value_cents','used_value_cents','pending_quantity','pending_value_cents'];
 if(fields.some(k=>!integer(limit?.[k])))add('SELLER_LIMIT_USAGE_REQUIRED');
 if(!Array.isArray(plan)||!plan.length)add('LISTING_INCREMENT_PLAN_REQUIRED');
 let quantity=0n,value=0n;const seen=new Set();
 for(const item of Array.isArray(plan)?plan:[]){
  const key=JSON.stringify([item?.supplier_id,item?.sku]);
  if(seen.has(key)){add('DUPLICATE_PLANNED_SKU');continue;}seen.add(key);
  const row=catalog.find(r=>r.supplier_id===item?.supplier_id&&r.sku===item?.sku);
  if(!row||!integer(item?.additional_quantity)||item.additional_quantity===0){add('LISTING_INCREMENT_INVALID');continue;}
  quantity+=BigInt(item.additional_quantity);value+=BigInt(item.additional_quantity)*BigInt(row.price_cents);
  const stock=inventory.find(r=>r.supplier_id===row.supplier_id&&r.sku===row.sku);
  if(!stock||stock.feed_status!=='current'||!stock.quote_current||stock.available<item.additional_quantity)add('PLANNED_QUANTITY_EXCEEDS_CURRENT_STOCK');
 }
 if(fields.every(k=>integer(limit?.[k]))){
  if(BigInt(limit.used_quantity)+BigInt(limit.pending_quantity)+quantity>BigInt(limit.max_quantity))add('SELLING_QUANTITY_LIMIT_EXCEEDED');
  if(BigInt(limit.used_value_cents)+BigInt(limit.pending_value_cents)+value>BigInt(limit.max_value_cents))add('SELLING_VALUE_LIMIT_EXCEEDED');
 }
 return {status:blockers.length?'BLOCKED':'WITHIN_DECLARED_LIMITS_UNVERIFIED',blockers:[...new Set(blockers)],planned_quantity:quantity.toString(),planned_value_cents:value.toString(),production_authorized:false};
}
