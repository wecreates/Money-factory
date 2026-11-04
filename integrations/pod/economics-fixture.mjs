import {types as utilTypes} from 'node:util';
import {validOpaqueText} from './text-identity.mjs';

const jobFields=['id','business_id','account_id','platform','package_sha256'];
const platforms=new Set(['kdp','redbubble','teepublic','zazzle','spreadshirt']);

function exactFixtureJob(value){
 const fail=()=>{throw Error('ECONOMICS_FIXTURE_INVALID');};
 if(!value||typeof value!=='object'||utilTypes.isProxy(value))fail();
 const prototype=Object.getPrototypeOf(value);
 if(prototype!==Object.prototype&&prototype!==null)fail();
 const snapshot=Object.create(null);
 for(const field of jobFields){
  const descriptor=Object.getOwnPropertyDescriptor(value,field);
  if(!descriptor||!Object.hasOwn(descriptor,'value'))fail();
  snapshot[field]=descriptor.value;
 }
 if(!['id','business_id','account_id'].every(field=>validOpaqueText(snapshot[field])&&snapshot[field].length<=128)||
  !platforms.has(snapshot.platform)||!/^[a-f0-9]{64}$/.test(snapshot.package_sha256))fail();
 return snapshot;
}

// Synthetic test budget only; never a production price, clearance or revenue.
export function economicsFixture(job,now=Date.now()){
 if(!Number.isSafeInteger(now)||now<1||now>Number.MAX_SAFE_INTEGER-60000)
  throw Error('ECONOMICS_FIXTURE_INVALID');
 job=exactFixtureJob(job);
 return {price:{verified:true,evidence_id:'fixture-price',amount_minor:2000,currency:'USD'},economics:{
  schema_version:1,verified:true,all_variable_costs_included:true,
  job_id:job.id,business_id:job.business_id,account_id:job.account_id,platform:job.platform,package_sha256:job.package_sha256,
  currency:'USD',price_minor:2000,expected_receipts_minor:1000,variable_cost_minor:600,
  minimum_contribution_minor:400,minimum_margin_bps:4000,evidence_event_id:'fixture-economics',
  source_evidence_ids:['fixture-price','fixture-royalty','fixture-cost'],observed_at_ms:now-1,valid_until_ms:now+60000}};
}
