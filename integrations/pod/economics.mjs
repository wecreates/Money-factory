// Versioned with Money Factory integrations/pod/economics.mjs. No forecasts
// enter the financial ledger here; this is a signed per-unit release budget.
const id=value=>typeof value==='string'&&value.trim().length>0&&value.length<=256;
const minor=value=>Number.isSafeInteger(value)&&value>=0;
export function enforceReleaseEconomics({price,economics:e},job,now=Date.now()){
 if(!e||e.schema_version!==1||e.verified!==true||e.all_variable_costs_included!==true||
  !id(e.evidence_event_id)||!Array.isArray(e.source_evidence_ids)||e.source_evidence_ids.length<1||
  e.source_evidence_ids.length>32||!e.source_evidence_ids.every(id)||new Set(e.source_evidence_ids).size!==e.source_evidence_ids.length||
  !price||price.verified!==true||!id(price.evidence_id)||!e.source_evidence_ids.includes(price.evidence_id)||
  !minor(price.amount_minor)||price.amount_minor===0||!/^[A-Z]{3}$/.test(price.currency||'')||
  e.currency!==price.currency||e.price_minor!==price.amount_minor||
  !minor(e.expected_receipts_minor)||e.expected_receipts_minor===0||e.expected_receipts_minor>e.price_minor||
  !minor(e.variable_cost_minor)||!minor(e.minimum_contribution_minor)||
  !Number.isSafeInteger(e.minimum_margin_bps)||e.minimum_margin_bps<0||e.minimum_margin_bps>10000)
  throw Error('ECONOMICS_EVIDENCE_REQUIRED');
 if(!['job_id','business_id','account_id','platform','package_sha256'].every(k=>
  typeof e[k]==='string'&&e[k]===(k==='job_id'?job.id:job[k]))||
  !/^[a-f0-9]{64}$/.test(e.package_sha256))throw Error('ECONOMICS_SCOPE_MISMATCH');
 if(!Number.isSafeInteger(now)||!Number.isSafeInteger(e.observed_at_ms)||
  !Number.isSafeInteger(e.valid_until_ms)||e.observed_at_ms>now||e.valid_until_ms<=now||
  e.observed_at_ms<0||e.valid_until_ms<=e.observed_at_ms)throw Error('ECONOMICS_EXPIRED_OR_INVALID');
 // Integer cross multiplication avoids rounding or unsafe Number products at
 // exact margin boundaries. Receipts are after platform deductions; costs must
 // include every remaining per-unit variable cost, without double counting.
 const receipts=BigInt(e.expected_receipts_minor),net=receipts-BigInt(e.variable_cost_minor);
 if(net<BigInt(e.minimum_contribution_minor)||net*10000n<receipts*BigInt(e.minimum_margin_bps))
  throw Error('ECONOMICS_MARGIN_BLOCKED');
 return {schema_version:1,verified:true,all_variable_costs_included:true,
  job_id:e.job_id,business_id:e.business_id,account_id:e.account_id,platform:e.platform,package_sha256:e.package_sha256,
  currency:e.currency,price_minor:e.price_minor,expected_receipts_minor:e.expected_receipts_minor,
  variable_cost_minor:e.variable_cost_minor,minimum_contribution_minor:e.minimum_contribution_minor,
  minimum_margin_bps:e.minimum_margin_bps,contribution_minor:Number(net),
  evidence_event_id:e.evidence_event_id,source_evidence_ids:[...e.source_evidence_ids],
  observed_at_ms:e.observed_at_ms,valid_until_ms:e.valid_until_ms};
}
