import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {normalizeOrders,orderRequest,shipmentRequest,orderKey,inventoryRequest} from './marketplaces.mjs';
import {fulfillmentSummary} from './ledger.mjs';
const mock=JSON.parse(readFileSync(new URL('./mock-responses.json',import.meta.url),'utf8'));
const copy=x=>structuredClone(x);
test('document-shaped authored mocks normalize identities and preserve incomplete pagination',()=>{
 for(const p of ['amazon','walmart','ebay']){
  const r=normalizeOrders(p,'mock-account',mock[p]);assert.equal(r.orders[0].lines[0].quantity,2);assert.equal(r.complete,false);assert.ok(r.next_cursor);assert.equal(r.verified_revenue_cents,0);assert.equal(r.orders[0].fulfillment_authorized,false);
  assert.notEqual(r.orders[0].key,orderKey(p,'different-account',r.orders[0].order_id));
 }
 const response=copy(mock.ebay);delete response.next;assert.equal(normalizeOrders('ebay','account',response).complete,true);
});
test('unknown statuses, duplicate orders/lines, quantity errors and non-USD fail closed',()=>{
 const a=copy(mock.amazon);a.orders[0].fulfillment.fulfillmentStatus='NEW_STATE';assert.throws(()=>normalizeOrders('amazon','a',a),/UNKNOWN_STATUS/);
 const b=copy(mock.ebay);b.orders.push(copy(b.orders[0]));assert.throws(()=>normalizeOrders('ebay','a',b),/DUPLICATE/);
 const c=copy(mock.ebay);c.orders[0].lineItems.push(copy(c.orders[0].lineItems[0]));assert.throws(()=>normalizeOrders('ebay','a',c),/DUPLICATE/);
 const d=copy(mock.ebay);d.orders[0].lineItems[0].quantity=1.5;assert.throws(()=>normalizeOrders('ebay','a',d),/QUANTITY/);
 const e=copy(mock.ebay);e.orders[0].pricingSummary.total.currency='EUR';assert.throws(()=>normalizeOrders('ebay','a',e),/CURRENCY/);
 const f=copy(mock.walmart);f.list.elements.order[0].orderLines.orderLine[0].orderLineStatuses.orderLineStatus[0].statusQuantity.amount='1';assert.throws(()=>normalizeOrders('walmart','a',f),/STATUS_QUANTITY/);
});
test('request descriptors escape path IDs, retain opaque cursors and restrict cursor origins',()=>{
 const r=orderRequest('ebay',{orderId:'abc/def?x=1'});assert.ok(r.url.endsWith('abc%2Fdef%3Fx%3D1'));assert.equal(r.dispatch_enabled,false);
 const a=orderRequest('amazon',{since:'2026-10-20T00:00:00Z',marketplaceId:'US-MOCK',cursor:'a+/='});assert.equal(new URL(a.url).searchParams.get('paginationToken'),'a+/=');assert.match(a.url,/2026-01-01/);
 assert.throws(()=>orderRequest('ebay',{cursor:'https://evil.example/order?token=1'}),/INVALID_CURSOR/);
 assert.throws(()=>orderRequest('walmart',{cursor:'https://evil.example/'}),/INVALID_CURSOR/);
 assert.throws(()=>orderRequest('amazon',{since:'bad',marketplaceId:'US'}),/UTC/);
});
const shipment={order_id:'000-0000000-0000001',package_id:'1',marketplace_id:'MOCK-US',lines:[{line_id:'1',quantity:1}],remaining:[{line_id:'1',quantity:2}],carrier:'UPS',tracking_number:'MOCK-TRACK',tendered_at_ms:1000,now:2000,evidence_id:'MOCK-TENDER',acknowledged:true,method_code:'Value'};

test('shipment planning accepts reconciled zero-remaining siblings without reshipping them',()=>{
 const summary=fulfillmentSummary({status:'processing',refunded_cents:0,lines:[
  {line_id:'1',quantity:2,shipped:1,cancelled:0,returned:0},
  {line_id:'shipped',quantity:1,shipped:1,cancelled:0,returned:0},
  {line_id:'cancelled',quantity:1,shipped:0,cancelled:1,returned:0}
 ]});
 const remaining=summary.lines.map(l=>({line_id:l.line_id,quantity:l.remaining}));
 for(const p of ['amazon','walmart','ebay']){
  const r=shipmentRequest(p,{...shipment,remaining});
  const lines=p==='amazon'?r.body.packageDetail.orderItems:p==='walmart'?r.body.orderShipment.orderLines.orderLine:r.body.lineItems;
  assert.equal(lines.length,1);assert.equal(r.dispatch_enabled,false);assert.equal(r.authenticated,false);
  for(const line_id of ['shipped','cancelled','missing'])assert.throws(()=>shipmentRequest(p,{...shipment,remaining,lines:[{line_id,quantity:1}]}),/EXCEEDS/);
  assert.throws(()=>shipmentRequest(p,{...shipment,remaining,lines:[{line_id:'1',quantity:0}]}),/QUANTITY/);
  for(const quantity of [-1,1.5,'0',Number.MAX_SAFE_INTEGER+1])assert.throws(()=>shipmentRequest(p,{...shipment,remaining:[...remaining,{line_id:'invalid',quantity}]}),/QUANTITY/);
  assert.throws(()=>shipmentRequest(p,{...shipment,remaining:[...remaining,{line_id:'shipped',quantity:0}]}),/DUPLICATE/);
 }
});
test('partial shipment descriptors retain quantities and never dispatch',()=>{
 for(const p of ['amazon','walmart','ebay']){const r=shipmentRequest(p,shipment);assert.equal(r.method,'POST');assert.equal(r.authenticated,false);assert.equal(r.dispatch_enabled,false);assert.equal(r.retry_policy,'reconcile_before_retry_on_uncertain_outcome');}
 assert.equal(shipmentRequest('amazon',shipment).body.packageDetail.orderItems[0].quantity,1);
 assert.equal(shipmentRequest('walmart',shipment).body.orderShipment.orderLines.orderLine[0].orderLineStatuses.orderLineStatus[0].statusQuantity.amount,'1');
 assert.equal(shipmentRequest('ebay',shipment).body.lineItems[0].quantity,1);
});
test('shipment rejects future tender, duplicates, excess quantities and missing Walmart acknowledgment',()=>{
 for(const p of ['amazon','walmart','ebay']){
  assert.throws(()=>shipmentRequest(p,{...shipment,tendered_at_ms:3000}),/TENDER/);
  assert.throws(()=>shipmentRequest(p,{...shipment,lines:[{line_id:'1',quantity:3}]}),/EXCEEDS/);
  assert.throws(()=>shipmentRequest(p,{...shipment,lines:[...shipment.lines,...shipment.lines]}),/DUPLICATE/);
 }
 assert.throws(()=>shipmentRequest('walmart',{...shipment,acknowledged:false}),/ACKNOWLEDGMENT/);
});
test('route readiness excludes unpaid, cancellation, third party fulfillment and already shipped orders',()=>{
 for(const p of ['amazon','walmart','ebay'])assert.equal(normalizeOrders(p,'a',mock[p]).orders[0].ready_to_route,true);
 const a=copy(mock.amazon);a.orders[0].orderItems[0].cancellation={cancellationRequest:{requester:'BUYER'}};assert.equal(normalizeOrders('amazon','a',a).orders[0].ready_to_route,false);
 const b=copy(mock.ebay);b.orders[0].orderPaymentStatus='PENDING';assert.equal(normalizeOrders('ebay','a',b).orders[0].ready_to_route,false);
 const c=copy(mock.walmart);c.list.elements.order[0].shipNode.type='WFSFulfilled';assert.equal(normalizeOrders('walmart','a',c).orders[0].ready_to_route,false);
 const d=copy(mock.amazon);d.orders[0].fulfillment.fulfillmentStatus='PARTIALLY_SHIPPED';assert.equal(normalizeOrders('amazon','a',d).orders[0].ready_to_route,false);
});
test('inventory preview supports zero stock, escaped SKU and requires Amazon product schema reference',()=>{
 const w=inventoryRequest('walmart',{sku:'SKU /?',quantity:0,shipNode:'MOCK-NODE'});assert.match(w.url,/SKU%20%2F%3F/);assert.equal(w.body.quantity.amount,0);assert.equal(w.dispatch_enabled,false);
 const e=inventoryRequest('ebay',{sku:'MOCK-SKU',quantity:2,offer_id:'MOCK-OFFER'});assert.equal(e.body.requests[0].offers[0].availableQuantity,2);
 assert.throws(()=>inventoryRequest('amazon',{sku:'MOCK',quantity:1}),/ID/);
 const a=inventoryRequest('amazon',{sku:'MOCK',quantity:0,seller_id:'MOCK-SELLER',marketplace_id:'MOCK-US',product_type:'MOCK-TYPE',schema_evidence_id:'MOCK-SCHEMA'});assert.equal(a.body.patches[0].path,'/attributes/fulfillment_availability');assert.equal(a.live_validation,'not_performed');
 assert.throws(()=>inventoryRequest('ebay',{sku:'MOCK',quantity:-1}),/QUANTITY/);
});
