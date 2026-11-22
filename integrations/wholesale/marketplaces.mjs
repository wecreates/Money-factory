// Request planning only. No HTTP client, token handling, or authenticated writes.
// Schema sources checked 2026-10-21 (fixtures are authored mocks, not recordings).
export const sources = {
 amazon:'https://developer-docs.amazon.com/sp-api/docs/orders-api-migration-guide',
 amazon_ship:'https://raw.githubusercontent.com/amzn/selling-partner-api-models/main/models/orders-api-model/ordersV0.json',
 walmart:'https://developer.walmart.com/us-marketplace/docs/get-all-orders',
 walmart_ship:'https://developer.walmart.com/us-marketplace/reference/shippingupdates',
 ebay:'https://developer.ebay.com/api-docs/master/sell/fulfillment/openapi/3/sell_fulfillment_v1_oas3.json',
 ebay_inventory:'https://developer.ebay.com/api-docs/master/sell/inventory/openapi/3/sell_inventory_v1_oas3.json',
 walmart_inventory:'https://developer.walmart.com/us-marketplace/reference/updateinventoryforanitem',
 amazon_inventory:'https://developer-docs.amazon.com/sp-api/docs/manage-product-listings-guide'
};
const roots={amazon:'https://sellingpartnerapi-na.amazon.com',walmart:'https://marketplace.walmartapis.com',ebay:'https://api.ebay.com'};
const paths={amazon:'/orders/2026-01-01/orders',walmart:'/v3/orders',ebay:'/sell/fulfillment/v1/order'};
const id=x=>{if(typeof x!=='string'||!x.trim()||x.length>1024)throw Error('INVALID_ID');return x;};
const qty=x=>{if(!Number.isSafeInteger(x)||x<1)throw Error('INVALID_QUANTITY');return x;};
const remainingQty=x=>{if(!Number.isSafeInteger(x)||x<0)throw Error('INVALID_QUANTITY');return x;};
const integerString=x=>{if(typeof x!=='string'||!/^\d+$/.test(x))throw Error('INVALID_QUANTITY');return qty(Number(x));};
const list=x=>{if(!Array.isArray(x))throw Error('MISSING_ARRAY');return x;};
const channel=p=>{if(!Object.hasOwn(roots,p))throw Error('UNKNOWN_MARKETPLACE');return p;};
const utc=x=>{id(x);if(!/^\d{4}-\d\d-\d\dT.*Z$/.test(x)||!Number.isFinite(Date.parse(x)))throw Error('INVALID_UTC');return x;};
const descriptor=(p,method,path,body)=>({classification:'request_plan_only',marketplace:p,method,url:roots[p]+path,...(body?{body}:{}),dispatch_enabled:false,authenticated:false});
export const orderKey=(p,account,order)=>JSON.stringify([channel(p),id(account),id(order)]);
export function orderRequest(p,{since,marketplaceId,cursor,orderId}={}){
 channel(p);
 if(orderId)return descriptor(p,'GET',paths[p]+'/'+encodeURIComponent(id(orderId))+(p==='amazon'?'?includedData=FULFILLMENT,CANCELLATION,PACKAGES':''));
 const query=new URLSearchParams();
 if(p==='amazon'){
  query.set('lastUpdatedAfter',utc(since));query.set('marketplaceIds',id(marketplaceId));query.set('fulfilledBy','MERCHANT');query.set('includedData','FULFILLMENT,CANCELLATION,PACKAGES');query.set('maxResultsPerPage','100');
  if(cursor)query.set('paginationToken',id(cursor));
 }else if(p==='walmart'){
  if(cursor){if(!id(cursor).startsWith('?')||cursor.includes('#'))throw Error('INVALID_CURSOR');return descriptor(p,'GET',paths[p]+cursor);}
  query.set('lastModifiedStartDate',utc(since));query.set('shipNodeType','SellerFulfilled');query.set('limit','100');
 }else{
  if(cursor){const u=new URL(id(cursor));if(u.origin!==roots.ebay||u.pathname!==paths.ebay||u.username||u.password||u.hash)throw Error('INVALID_CURSOR');return descriptor(p,'GET',u.pathname+u.search);}
  query.set('filter',`lastmodifieddate:[${utc(since)}..]`);query.set('limit','100');
 }
 return descriptor(p,'GET',paths[p]+'?'+query);
}
function unique(rows,field){const seen=new Set();for(const r of rows){const v=id(r[field]);if(seen.has(v))throw Error('DUPLICATE_'+field);seen.add(v);}return rows;}
// Financial fields are deliberately not booked. Currency validation covers supplied
// provider monetary objects; catalog estimates remain separate from settlements.
function currencyTree(obj){if(!obj||typeof obj!=='object')return;for(const [k,v] of Object.entries(obj)){if((k==='currency'||k==='currencyCode')&&v!=='USD')throw Error('UNSUPPORTED_CURRENCY');if(v&&typeof v==='object')currencyTree(v);}}
export function normalizeOrders(p,account,response){
 channel(p);id(account);currencyTree(response);
 let raw,cursor;
 if(p==='amazon'){raw=list(response.orders);cursor=response.pagination?.nextToken??null;}
 if(p==='walmart'){raw=list(response.list?.elements?.order);cursor=response.list?.meta?.nextCursor??null;}
 if(p==='ebay'){raw=list(response.orders);cursor=response.next??null;}
 if(cursor!==null)id(cursor);
 const orders=raw.map(o=>{
  let order_id,status,lines,ready_to_route=false;
  if(p==='amazon'){
   order_id=id(o.orderId);status=o.fulfillment?.fulfillmentStatus;
   if(!['UNSHIPPED','PARTIALLY_SHIPPED','SHIPPED','CANCELLED','PENDING','UNFULFILLABLE','PENDING_AVAILABILITY','INVOICE_UNCONFIRMED'].includes(status))throw Error('UNKNOWN_STATUS');
   lines=list(o.orderItems).map(l=>({line_id:id(l.orderItemId),sku:id(l.product?.sellerSku),quantity:qty(l.quantityOrdered)}));
   ready_to_route=status==='UNSHIPPED'&&o.fulfillment.fulfilledBy==='MERCHANT'&&!o.orderItems.some(l=>l.cancellation?.cancellationRequest||l.cancellation?.cancellationExecution);
  }else if(p==='walmart'){
   order_id=id(o.purchaseOrderId);status='LINE_STATUS';
   lines=list(o.orderLines?.orderLine).map(l=>{
    const quantity=integerString(l.orderLineQuantity?.amount);
    if(l.orderLineQuantity.unitOfMeasurement!=='EACH')throw Error('UNSUPPORTED_UNIT');
    const statuses=list(l.orderLineStatuses?.orderLineStatus).map(s=>{
     if(!['Created','Acknowledged','Shipped','Delivered','Cancelled'].includes(s.status))throw Error('UNKNOWN_STATUS');
     if(s.statusQuantity?.unitOfMeasurement!=='EACH')throw Error('UNSUPPORTED_UNIT');
     return {status:s.status,quantity:integerString(s.statusQuantity.amount)};
    });
    if(statuses.reduce((sum,s)=>sum+s.quantity,0)!==quantity)throw Error('STATUS_QUANTITY_MISMATCH');
    return {line_id:id(l.lineNumber),sku:id(l.item?.sku),quantity,statuses};
   });
   ready_to_route=o.shipNode?.type==='SellerFulfilled'&&lines.every(l=>l.statuses.every(s=>['Created','Acknowledged'].includes(s.status)));
  }else{
   order_id=id(o.orderId);status=o.orderFulfillmentStatus;
   if(!['NOT_STARTED','IN_PROGRESS','FULFILLED'].includes(status))throw Error('UNKNOWN_STATUS');
   lines=list(o.lineItems).map(l=>({line_id:id(l.lineItemId),sku:id(l.sku),quantity:qty(l.quantity)}));
   ready_to_route=status==='NOT_STARTED'&&o.orderPaymentStatus==='PAID'&&o.cancelStatus?.cancelState==='NONE_REQUESTED';
  }
  if(!lines.length)throw Error('EMPTY_ORDER');unique(lines,'line_id');
  return {key:orderKey(p,account,order_id),marketplace:p,account_id:account,order_id,status,lines,currency:'USD',ready_to_route,classification:'unverified_provider_data',fulfillment_authorized:false};
 });
 unique(orders,'key');return {orders,next_cursor:cursor,complete:cursor===null,classification:'normalization_only',verified_revenue_cents:0};
}

// Absolute quantities must come from a single versioned allocation plan. These are
// previews, not safe-to-send mutations; retain read-back and reconciliation gates.
export function inventoryRequest(p,{sku,quantity,shipNode,offer_id,seller_id,marketplace_id,product_type,schema_evidence_id}={}){
 channel(p);id(sku);if(!Number.isSafeInteger(quantity)||quantity<0)throw Error('INVALID_QUANTITY');
 let r;
 if(p==='walmart')r=descriptor(p,'PUT','/v3/inventory?sku='+encodeURIComponent(sku)+(shipNode?'&shipNode='+encodeURIComponent(id(shipNode)):''),{sku,quantity:{unit:'EACH',amount:quantity}});
 else if(p==='ebay')r=descriptor(p,'POST','/sell/inventory/v1/bulk_update_price_quantity',{requests:[{sku,shipToLocationAvailability:{quantity},...(offer_id?{offers:[{offerId:id(offer_id),availableQuantity:quantity}]}:{})}]});
 else{
  id(schema_evidence_id);id(product_type);id(marketplace_id);id(seller_id);
  r=descriptor(p,'PATCH',`/listings/2021-08-01/items/${encodeURIComponent(seller_id)}/${encodeURIComponent(sku)}?marketplaceIds=${encodeURIComponent(marketplace_id)}`,{productType:product_type,patches:[{op:'replace',path:'/attributes/fulfillment_availability',value:[{fulfillment_channel_code:'DEFAULT',quantity,marketplace_id}]}]});
 }
 return {...r,requires_current_allocation_version:true,requires_provider_readback:true,live_validation:'not_performed'};
}
export function shipmentRequest(p,input){
 channel(p);const {order_id,lines,remaining,carrier,tracking_number,tendered_at_ms,now,evidence_id}=input;
 id(order_id);id(carrier);id(tracking_number);id(evidence_id);
 if(!Number.isSafeInteger(now)||!Number.isSafeInteger(tendered_at_ms)||tendered_at_ms<0||tendered_at_ms>now)throw Error('INVALID_TENDER');
 const selected=unique(list(lines).map(l=>({line_id:id(l.line_id),quantity:qty(l.quantity)})),'line_id');
 if(!selected.length)throw Error('EMPTY_SHIPMENT');
 // A reconciled order includes completed/cancelled lines with no units remaining.
 // Shipment selections remain strictly positive and cannot exceed those ceilings.
 const capacities=unique(list(remaining).map(l=>({line_id:id(l.line_id),quantity:remainingQty(l.quantity)})),'line_id');
 for(const l of selected){if(l.quantity>(capacities.find(r=>r.line_id===l.line_id)?.quantity??0))throw Error('SHIPMENT_EXCEEDS_REMAINING');}
 const oid=encodeURIComponent(order_id),date=new Date(tendered_at_ms).toISOString();let body,path;
 if(p==='amazon'){
  if(!/^\d+-\d+-\d+$/.test(order_id))throw Error('INVALID_AMAZON_ORDER_ID');
  const packageReferenceId=id(input.package_id);if(!/^[1-9]\d*$/.test(packageReferenceId))throw Error('INVALID_PACKAGE_REFERENCE');
  body={marketplaceId:id(input.marketplace_id),packageDetail:{packageReferenceId,carrierCode:carrier,trackingNumber:tracking_number,shipDate:date,orderItems:selected.map(l=>({orderItemId:l.line_id,quantity:l.quantity}))}};
  if(carrier==='Other')body.packageDetail.carrierName=id(input.carrier_name);
  path=`/orders/v0/orders/${oid}/shipmentConfirmation`;
 }else if(p==='ebay'){
  body={lineItems:selected.map(l=>({lineItemId:l.line_id,quantity:l.quantity})),shippingCarrierCode:carrier,trackingNumber:tracking_number,shippedDate:date};path=paths[p]+`/${oid}/shipping_fulfillment`;
 }else{
  if(input.acknowledged!==true)throw Error('WALMART_ACKNOWLEDGMENT_REQUIRED');
  body={orderShipment:{orderLines:{orderLine:selected.map(l=>({lineNumber:l.line_id,orderLineStatuses:{orderLineStatus:[{status:'Shipped',statusQuantity:{unitOfMeasurement:'EACH',amount:String(l.quantity)},trackingInfo:{shipDateTime:tendered_at_ms,carrierName:{carrier},methodCode:id(input.method_code),trackingNumber:tracking_number}}]}}))}}};path=paths[p]+`/${oid}/shipping`;
 }
 return {...descriptor(p,'POST',path,body),retry_policy:'reconcile_before_retry_on_uncertain_outcome',requires_current_remaining_reconciliation:true,financial_side_effect_possible:p==='walmart'};
}
