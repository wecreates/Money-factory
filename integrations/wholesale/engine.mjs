// Local simulation only. No transport, credentials, publication or financial ledger writes.
const channels = new Set(['amazon', 'walmart', 'ebay']);
const clone = value => structuredClone(value);
const fail = code => { throw new Error(code); };
const integer = (n, label) => { if (!Number.isSafeInteger(n) || n < 0) fail(`INVALID_${label}`); return n; };
const id = (s, label) => { if (typeof s !== 'string' || !s.trim() || s.length > 256) fail(`INVALID_${label}`); return s; };
const key = row => JSON.stringify([row.supplier_id, row.sku]);
const fields = ['price_cents','cost_cents','shipping_cents','handling_cents','tax_cents','fee_bps','fixed_fee_cents','min_fee_cents','return_reserve_bps','quote_expires_at_ms','safety_stock'];
function validate(row) {
  if (!row || typeof row !== 'object') fail('INVALID_ROW');
  id(row.supplier_id,'SUPPLIER'); id(row.sku,'SKU');
  if (row.currency !== 'USD') fail('UNSUPPORTED_CURRENCY');
  for (const f of fields) integer(row[f],f.toUpperCase());
  if (row.fee_bps > 10000 || row.return_reserve_bps > 10000 || row.price_cents === 0) fail('INVALID_RATE_OR_PRICE');
  return row;
}
export function importCatalog(rows) {
  if (!Array.isArray(rows)) fail('INVALID_CATALOG');
  const seen = new Set();
  return rows.map(row => { validate(row); const k = key(row); if (seen.has(k)) fail('DUPLICATE_SKU'); seen.add(k); return clone(row); });
}
export function economics(row) {
  validate(row);
  const ceilRate = (cents,bps) => Number((BigInt(cents)*BigInt(bps)+9999n)/10000n);
  const marketplace_fee_cents = Math.max(row.min_fee_cents, ceilRate(row.price_cents,row.fee_bps)+row.fixed_fee_cents);
  const return_reserve_cents = ceilRate(row.price_cents,row.return_reserve_bps);
  const landed_cost_cents = row.cost_cents+row.shipping_cents+row.handling_cents+row.tax_cents;
  const total_cost_cents = landed_cost_cents+marketplace_fee_cents+return_reserve_cents;
  integer(total_cost_cents,'TOTAL_COST');
  const projected_profit_cents = row.price_cents-total_cost_cents;
  const numerator=BigInt(projected_profit_cents)*10000n, denominator=BigInt(row.price_cents);
  // BigInt division truncates toward zero; adjust losses to preserve floor semantics.
  const margin_bps=Number((numerator-(numerator<0n?denominator-1n:0n))/denominator);
  if(!Number.isSafeInteger(margin_bps))fail('INVALID_MARGIN');
  return {currency:'USD',landed_cost_cents,marketplace_fee_cents,return_reserve_cents,total_cost_cents,projected_profit_cents,margin_bps,classification:'simulation',verified_profit_cents:0};
}
export function supplierBlockers(supplier, marketplace, sku, now) {
  integer(now,'CLOCK');
  const blockers=[];
  if (!channels.has(marketplace)) blockers.push('UNSUPPORTED_MARKETPLACE');
  if (!supplier || supplier.relationship !== 'wholesale') blockers.push('WHOLESALE_RELATIONSHIP_REQUIRED');
  const a=supplier?.authorization;
  if (!Array.isArray(a?.channels) || !a.channels.includes(marketplace)) blockers.push('CHANNEL_AUTHORIZATION_REQUIRED');
  if (!Array.isArray(a?.skus) || !a.skus.includes(sku)) blockers.push('SKU_AUTHORIZATION_REQUIRED');
  if (typeof a?.evidence_id !== 'string' || !a.evidence_id.trim() || !Number.isSafeInteger(a.expires_at_ms) || a.expires_at_ms<=now) blockers.push('CURRENT_AUTHORIZATION_EVIDENCE_REQUIRED');
  if (supplier?.seller_of_record !== true || supplier?.neutral_packaging !== true) blockers.push('SELLER_OF_RECORD_PACKAGING_REQUIRED');
  const r=supplier?.returns;
  if (typeof r?.evidence_id !== 'string' || !r.evidence_id.trim() || !Number.isSafeInteger(r.expires_at_ms) || r.expires_at_ms<=now) blockers.push('CURRENT_RETURN_AGREEMENT_REQUIRED');
  return blockers;
}
export function inventoryPlan(catalog, snapshots, reservations=[], now=Date.now()) {
  const rows=importCatalog(catalog); integer(now,'CLOCK');
  if (!Array.isArray(snapshots) || !Array.isArray(reservations)) fail('INVALID_INVENTORY');
  const feeds=new Map(), reserved=new Map();
  for (const s of snapshots) {
    id(s.supplier_id,'SUPPLIER'); id(s.sku,'SKU'); integer(s.quantity,'QUANTITY'); integer(s.observed_at_ms,'FEED_CLOCK'); integer(s.max_age_ms,'MAX_AGE');
    // All entry points require the positive freshness policy used by onboarding.
    if (s.max_age_ms === 0) fail('INVALID_MAX_AGE');
    if (feeds.has(key(s))) fail('DUPLICATE_INVENTORY'); feeds.set(key(s),s);
  }
  for (const r of reservations) { id(r.supplier_id,'SUPPLIER'); id(r.sku,'SKU'); integer(r.quantity,'RESERVATION'); const n=(reserved.get(key(r))||0)+r.quantity; integer(n,'RESERVATION_TOTAL'); reserved.set(key(r),n); }
  return rows.map(row => {
    const s=feeds.get(key(row)), reserved_quantity=reserved.get(key(row))||0;
    const fresh=!!s && s.observed_at_ms<=now && now-s.observed_at_ms<=s.max_age_ms;
    const quote_current=row.quote_expires_at_ms>now;
    return {supplier_id:row.supplier_id,sku:row.sku,available: fresh&&quote_current?Math.max(0,s.quantity-reserved_quantity-row.safety_stock):0,reserved_quantity,feed_status:!s?'missing':fresh?'current':'stale_or_future',quote_current,scope:'shared_pool_not_per_channel',classification:'simulation'};
  });
}
export class SandboxOrders {
  constructor({catalog,suppliers,snapshots,now=Date.now(),mode='sandbox'}) {
    if (mode !== 'sandbox') fail('LIVE_MODE_DISABLED');
    integer(now,'CLOCK'); this.now=now; this.catalog=importCatalog(catalog); this.suppliers=clone(suppliers); this.snapshots=clone(snapshots); this.orders=new Map();
    if (!Array.isArray(this.suppliers)) fail('INVALID_SUPPLIERS');
    const seen=new Set(); for (const s of this.suppliers) { id(s.id,'SUPPLIER'); if(seen.has(s.id)) fail('DUPLICATE_SUPPLIER'); seen.add(s.id); }
    inventoryPlan(this.catalog,this.snapshots,[],this.now);
  }
  reservations() { return [...this.orders.values()].filter(o=>o.state!=='cancelled').map(o=>({supplier_id:o.supplier_id,sku:o.sku,quantity:o.quantity})); }
  syncInventory(snapshots,now) {
    integer(now,'CLOCK'); if(now<this.now) fail('CLOCK_REGRESSION');
    const next=clone(snapshots);
    const plan=inventoryPlan(this.catalog,next,this.reservations(),now);
    this.snapshots=next; this.now=now;
    return plan;
  }
  route(input) {
    const order={id:id(input.id,'ORDER'),marketplace:input.marketplace,supplier_id:id(input.supplier_id,'SUPPLIER'),sku:id(input.sku,'SKU'),quantity:integer(input.quantity,'QUANTITY')};
    if (!order.quantity) fail('ZERO_QUANTITY');
    const old=this.orders.get(order.id), signature=JSON.stringify(order);
    if(old) { if(old.signature!==signature) fail('IDEMPOTENCY_CONFLICT'); return clone(old); }
    const row=this.catalog.find(r=>key(r)===key(order)); if(!row) fail('UNKNOWN_SKU');
    const blockers=supplierBlockers(this.suppliers.find(s=>s.id===order.supplier_id),order.marketplace,order.sku,this.now); if(blockers.length) fail(blockers.join(','));
    if(row.quote_expires_at_ms<=this.now) fail('QUOTE_EXPIRED');
    if(economics(row).projected_profit_cents<=0) fail('NONPOSITIVE_PROJECTED_MARGIN');
    const stock=inventoryPlan(this.catalog,this.snapshots,this.reservations(),this.now).find(r=>key(r)===key(order));
    if(stock.available<order.quantity) fail('INSUFFICIENT_CURRENT_INVENTORY');
    const saved={...order,signature,state:'routed',classification:'simulation',external_effects:0}; this.orders.set(order.id,saved); return clone(saved);
  }
  transition(orderId, from, to, extra={}) { const o=this.orders.get(orderId); if(!o) fail('UNKNOWN_ORDER'); if(!from.includes(o.state)) fail('INVALID_TRANSITION'); Object.assign(o,extra,{state:to}); return clone(o); }
  accept(orderId,reference) { return this.transition(orderId,['routed'],'accepted',{supplier_reference:id(reference,'REFERENCE')}); }
  track(orderId,{carrier,tracking_number,tendered_at_ms,evidence_id}) { integer(tendered_at_ms,'TENDER_CLOCK'); if(tendered_at_ms>this.now) fail('FUTURE_TENDER'); return this.transition(orderId,['accepted'],'shipped',{carrier:id(carrier,'CARRIER'),tracking_number:id(tracking_number,'TRACKING'),tendered_at_ms,evidence_id:id(evidence_id,'TENDER_EVIDENCE')}); }
  requestCancel(orderId) { return this.transition(orderId,['routed','accepted'],'cancel_requested',{cancel_origin:this.orders.get(orderId)?.state}); }
  confirmCancel(orderId,evidence_id) { return this.transition(orderId,['cancel_requested'],'cancelled',{cancellation_evidence_id:id(evidence_id,'CANCELLATION_EVIDENCE')}); }
  denyCancel(orderId,reference) { const o=this.orders.get(orderId); if(!o) fail('UNKNOWN_ORDER'); if(!['routed','accepted'].includes(o.cancel_origin)) fail('INVALID_CANCEL_ORIGIN'); return this.transition(orderId,['cancel_requested'],o.cancel_origin,{cancellation_denial_reference:id(reference,'CANCELLATION_DENIAL_REFERENCE')}); }
  requestReturn(orderId) { return this.transition(orderId,['shipped'],'return_requested'); }
  authorizeReturn(orderId,rma) { return this.transition(orderId,['return_requested'],'return_authorized',{rma:id(rma,'RMA')}); }
  receiveReturn(orderId) { return this.transition(orderId,['return_authorized'],'return_received'); }
  refund(orderId) { return this.transition(orderId,['return_received'],'refunded',{refund_status:'simulated_only'}); }
  snapshot() { return {mode:'sandbox',classification:'simulation',external_effects:0,verified_profit_cents:0,orders:clone([...this.orders.values()]),inventory:inventoryPlan(this.catalog,this.snapshots,this.reservations(),this.now)}; }
}
