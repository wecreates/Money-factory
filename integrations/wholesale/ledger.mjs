import {open,readFile,rename,unlink,mkdir} from 'node:fs/promises';
import {dirname} from 'node:path';
import {randomUUID} from 'node:crypto';
const reject=c=>{throw Error(c);};
const str=v=>{if(typeof v!=='string'||!v.trim()||v.length>256||['__proto__','constructor','prototype'].includes(v))reject('INVALID_ID');return v;};
const int=v=>{if(!Number.isSafeInteger(v)||v<0)reject('INVALID_INTEGER');return v;};
const positive=v=>{int(v);if(v===0)reject('ZERO_QUANTITY');return v;};
const identity=o=>{if(!['amazon','walmart','ebay'].includes(o.marketplace))reject('INVALID_MARKETPLACE');return JSON.stringify([o.marketplace,str(o.account_id),str(o.order_id)]);};
const itemKey=o=>JSON.stringify([str(o.supplier_id),str(o.sku)]);
const copy=o=>structuredClone(o);
const canonical=o=>JSON.stringify(o);
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function entries(lines){
 if(!Array.isArray(lines)||!lines.length)reject('LINES_REQUIRED');
 const seen=new Set();return lines.map(l=>{const line_id=str(l.line_id);if(seen.has(line_id))reject('DUPLICATE_LINE');seen.add(line_id);return {line_id,quantity:positive(l.quantity)};}).sort((a,b)=>a.line_id.localeCompare(b.line_id));
}
function replay(events,eventId,payload){if(!Object.hasOwn(events,eventId))return false;const old=events[eventId];if(canonical(old)!==canonical(payload))reject('IDEMPOTENCY_CONFLICT');return true;}
function line(order,id){const l=order.lines.find(l=>l.line_id===id);if(!l)reject('UNKNOWN_LINE');return l;}
export function fulfillmentSummary(order){
 const lines=order.lines.map(l=>({line_id:l.line_id,ordered:l.quantity,shipped:l.shipped,cancelled:l.cancelled,returned:l.returned,remaining:l.quantity-l.shipped-l.cancelled}));
 const closed=lines.every(l=>l.remaining===0);
 const fulfillment_state=lines.every(l=>l.cancelled===l.ordered)?'cancelled':
  closed&&lines.every(l=>l.returned===l.shipped)?'returned':
  lines.some(l=>l.returned>0)?'partially_returned':
  closed?'fulfilled':lines.some(l=>l.shipped>0)?'partially_shipped':
  lines.some(l=>l.cancelled>0)?'partially_cancelled':'reserved';
 return {fulfillment_state,fulfillment_closed:closed,control_status:order.status,refunded_cents:order.refunded_cents,lines};
}
function ingest(state,c){
 const key=identity(c);const base=entries(c.lines);
 const lines=base.map(e=>{const original=c.lines.find(l=>l.line_id===e.line_id);return {...e,supplier_id:str(original.supplier_id),sku:str(original.sku),unit_price_cents:int(original.unit_price_cents)};});
 const signature=canonical(lines),old=state.orders[key];
 if(old){if(old.signature!==signature)reject('IDEMPOTENCY_CONFLICT');return false;}
 const needed={};for(const l of lines){const k=itemKey(l);needed[k]=(needed[k]||0)+l.quantity;int(needed[k]);}
 // Fresh feed ceiling is a total pool limit, not additional stock. Keep all
 // uncancelled units reserved conservatively until explicit reconciliation.
 if(c.inventory_ceiling!==undefined){
  if(!Array.isArray(c.inventory_ceiling))reject('INVALID_INVENTORY_CEILING');
  const ceilings={};for(const r of c.inventory_ceiling){const k=itemKey(r);if(Object.hasOwn(ceilings,k))reject('DUPLICATE_INVENTORY_CEILING');ceilings[k]=int(r.quantity);}
  for(const k of Object.keys(needed))if(!Object.hasOwn(ceilings,k))reject('MISSING_INVENTORY_CEILING');
  const reservations={};for(const order of Object.values(state.orders))for(const l of order.lines){const k=itemKey(l);reservations[k]=(reservations[k]||0)+l.quantity-l.cancelled;int(reservations[k]);}
  for(const [k,ceiling] of Object.entries(ceilings))state.inventory[k]=Math.min(state.inventory[k]??0,Math.max(0,ceiling-(reservations[k]||0)));
 }
 for(const [k,n] of Object.entries(needed))if((state.inventory[k]??0)<n)reject('INSUFFICIENT_INVENTORY');
 for(const [k,n] of Object.entries(needed))state.inventory[k]-=n;
 state.orders[key]={marketplace:c.marketplace,account_id:c.account_id,order_id:c.order_id,signature,status:'reserved',lines:lines.map(l=>({...l,shipped:0,cancelled:0,returned:0})),packages:{},cancellations:{},returns:{},refunds:{},refunded_cents:0};return true;
}
function apply(state,c,now){
 if(c.type==='ingest')return ingest(state,c);
 const order=state.orders[identity(c.identity)];if(!order)reject('UNKNOWN_ORDER');
 // Status guards describe this local simulation; they are not provider status mappings.
 if(c.type==='status'){const status=str(c.status);if(!['reserved','processing','on_hold','completed'].includes(status))reject('INVALID_STATUS');const closed=order.lines.every(l=>l.shipped+l.cancelled===l.quantity);if(status==='completed'&&!closed)reject('ORDER_NOT_FULFILLED');if(status!=='completed'&&(closed||order.status==='completed'))reject('TERMINAL_ORDER');if(order.status===status)return false;order.status=status;return true;}
 if(c.type==='ship'){
  const package_id=str(c.package_id),tendered_at_ms=int(c.tendered_at_ms);if(tendered_at_ms>now)reject('FUTURE_TENDER');
  const payload={carrier:str(c.carrier),tracking_number:str(c.tracking_number),tendered_at_ms,evidence_id:str(c.evidence_id),lines:entries(c.lines)};
  if(replay(order.packages,package_id,payload))return false;
  if(order.status==='on_hold')reject('ORDER_ON_HOLD');
  for(const e of payload.lines){const l=line(order,e.line_id);if(l.shipped+l.cancelled+e.quantity>l.quantity)reject('OVER_SHIPMENT');}
  for(const e of payload.lines)line(order,e.line_id).shipped+=e.quantity;
  order.packages[package_id]=payload;return true;
 }
 if(c.type==='cancel'){
  const evidence_id=str(c.evidence_id),payload={lines:entries(c.lines)};
  if(replay(order.cancellations,evidence_id,payload))return false;
  for(const e of payload.lines){const l=line(order,e.line_id);if(l.shipped+l.cancelled+e.quantity>l.quantity)reject('OVER_CANCELLATION');}
  for(const e of payload.lines){const l=line(order,e.line_id);l.cancelled+=e.quantity;state.inventory[itemKey(l)]+=e.quantity;int(state.inventory[itemKey(l)]);}
  order.cancellations[evidence_id]=payload;return true;
 }
 if(c.type==='return'){
  const return_id=str(c.return_id),payload={lines:entries(c.lines)};
  if(replay(order.returns,return_id,payload))return false;
  for(const e of payload.lines){const l=line(order,e.line_id);if(l.returned+e.quantity>l.shipped)reject('OVER_RETURN');}
  for(const e of payload.lines)line(order,e.line_id).returned+=e.quantity;
  order.returns[return_id]=payload;return true;
 }
 if(c.type==='refund'){
  const refund_id=str(c.refund_id),payload={amount_cents:positive(c.amount_cents)};
  if(replay(order.refunds,refund_id,payload))return false;
  const cap=order.lines.reduce((n,l)=>n+BigInt(l.returned+l.cancelled)*BigInt(l.unit_price_cents),0n);
  const cumulative=BigInt(order.refunded_cents)+BigInt(payload.amount_cents);
  if(cumulative>cap||cumulative>BigInt(Number.MAX_SAFE_INTEGER))reject('REFUND_CAP_EXCEEDED');
  order.refunded_cents=Number(cumulative);order.refunds[refund_id]=payload;return true;
 }
 reject('UNKNOWN_COMMAND');
}
// Refuse stale-lock stealing: uncertain crashed writers require human reconciliation.
export class SandboxLedger {
 constructor(path,{lockTimeoutMs=2000}={}){this.path=path;this.lock=path+'.lock';this.lockTimeoutMs=int(lockTimeoutMs);}
 async withLock(fn){
  await mkdir(dirname(this.path),{recursive:true});const start=Date.now();let handle;
  while(!handle){try{handle=await open(this.lock,'wx');}catch(e){if(e.code!=='EEXIST')throw e;if(Date.now()-start>=this.lockTimeoutMs)reject('LEDGER_LOCK_BUSY_RECONCILE');await sleep(10);}}
  try{return await fn();}finally{await handle.close();await unlink(this.lock);}
 }
 async write(state){
  const temporary=this.path+'.'+randomUUID()+'.tmp';let handle;
  try{handle=await open(temporary,'wx');await handle.writeFile(JSON.stringify(state,null,2)+'\n');await handle.sync();await handle.close();handle=null;await rename(temporary,this.path);}
  finally{if(handle)await handle.close();await unlink(temporary).catch(e=>{if(e.code!=='ENOENT')throw e;});}
 }
 async read(){const state=JSON.parse(await readFile(this.path,'utf8'));if(state.schema_version!==1||state.mode!=='sandbox'||state.classification!=='simulation')reject('INVALID_LEDGER');return state;}
 async initialize({inventory}){
  return this.withLock(async()=>{
   try{await this.read();reject('LEDGER_ALREADY_EXISTS');}catch(e){if(e.code!=='ENOENT')throw e;}
   if(!Array.isArray(inventory))reject('INVALID_INVENTORY');const stock={};
   for(const r of inventory){const k=itemKey(r);if(Object.hasOwn(stock,k))reject('DUPLICATE_INVENTORY');stock[k]=int(r.quantity);}
   const state={schema_version:1,mode:'sandbox',classification:'simulation',version:0,external_effects:0,verified_profit_cents:0,inventory:stock,orders:{}};await this.write(state);return copy(state);
  });
 }
 async transact(command,{expectedVersion,now=Date.now()}={}){
  return (await this.transactWithReceipt(command,{expectedVersion,now})).state;
 }
 async transactWithReceipt(command,{expectedVersion,now=Date.now()}={}){
  int(now);return this.withLock(async()=>{const state=await this.read();if(expectedVersion!==undefined&&(int(expectedVersion)!==state.version))reject('VERSION_CONFLICT');const changed=apply(state,command,now);if(changed){state.version++;int(state.version);await this.write(state);}return {state:copy(state),changed};});
 }
}
export function retryPlan({method,status,attempt=0,retry_after_seconds=0,ambiguous=false}){
 int(attempt);if(typeof method!=='string'||!['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'].includes(method.toUpperCase()))reject('INVALID_METHOD');
 const read=['GET','HEAD','OPTIONS'].includes(method.toUpperCase());
 if(!read&&(ambiguous||status===undefined||status>=500&&status<=599))return {action:'reconcile',reason:'mutation_outcome_unknown',automatic_retry:false};
 if(attempt>=3)return {action:'stop',reason:'retry_limit',automatic_retry:false};
 if(status===429){
  if(typeof retry_after_seconds!=='number'||!Number.isFinite(retry_after_seconds)||retry_after_seconds<0)reject('INVALID_RETRY_AFTER');
  if(retry_after_seconds>300)return {action:'defer',reason:'retry_after_exceeds_automatic_cap',retry_after_seconds,automatic_retry:false};
  return {action:read?'retry':'reconcile',delay_ms:Math.max(retry_after_seconds*1000,1000*2**attempt),automatic_retry:read};
 }
 if(read&&(status===undefined||status>=500&&status<=599))return {action:'retry',delay_ms:1000*2**attempt,automatic_retry:true};
 return {action:'stop',automatic_retry:false};
}
