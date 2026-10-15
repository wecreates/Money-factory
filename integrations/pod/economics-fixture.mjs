// Synthetic test budget only; never a production price, clearance or revenue.
export function economicsFixture(job,now=Date.now()){
 return {price:{verified:true,evidence_id:'fixture-price',amount_minor:2000,currency:'USD'},economics:{
  schema_version:1,verified:true,all_variable_costs_included:true,
  job_id:job.id,business_id:job.business_id,account_id:job.account_id,platform:job.platform,package_sha256:job.package_sha256,
  currency:'USD',price_minor:2000,expected_receipts_minor:1000,variable_cost_minor:600,
  minimum_contribution_minor:400,minimum_margin_bps:4000,evidence_event_id:'fixture-economics',
  source_evidence_ids:['fixture-price','fixture-royalty','fixture-cost'],observed_at_ms:now-1,valid_until_ms:now+60000}};
}
