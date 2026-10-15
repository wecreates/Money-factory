import test from 'node:test';
import assert from 'node:assert/strict';
import {enforceReleaseEconomics} from './economics.mjs';
import {economicsFixture} from './economics-fixture.mjs';
const now=5000000,job={id:'fixture-job',business_id:'fixture-business',account_id:'fixture-account',
 platform:'redbubble',package_sha256:'a'.repeat(64)};
const run=f=>enforceReleaseEconomics(f,job,now);
test('exact signed contribution and margin thresholds pass without trusting a supplied profit',()=>{
 const f=economicsFixture(job,now);f.economics.contribution_minor=999999;
 assert.equal(run(f).contribution_minor,400);assert.notEqual(run(f).source_evidence_ids,f.economics.source_evidence_ids);
});
test('one minor unit or one basis point below minimum fails closed',()=>{
 for(const change of [e=>e.variable_cost_minor++,e=>e.minimum_contribution_minor++,e=>e.minimum_margin_bps++,e=>e.variable_cost_minor=1001]){
  const f=economicsFixture(job,now);change(f.economics);assert.throws(()=>run(f),/ECONOMICS_MARGIN_BLOCKED/);
 }
});
test('integer cross multiplication remains exact beyond safe Number product range',()=>{
 const f=economicsFixture(job,now),n=Number.MAX_SAFE_INTEGER;
 f.price.amount_minor=n;Object.assign(f.economics,{price_minor:n,expected_receipts_minor:n,
  variable_cost_minor:0,minimum_contribution_minor:n,minimum_margin_bps:10000});
 assert.equal(run(f).contribution_minor,n);
 f.economics.minimum_contribution_minor=0;f.economics.variable_cost_minor=1;
 assert.throws(()=>run(f),/ECONOMICS_MARGIN_BLOCKED/);
});
test('unknown, incomplete, inconsistent and malformed economic evidence is rejected',()=>{
 const edits=[f=>delete f.economics,f=>f.economics.verified=false,f=>f.economics.all_variable_costs_included=false,
  f=>f.economics.schema_version=2,f=>f.price=null,f=>f.price.verified=false,f=>f.price.evidence_id='unknown',
  f=>f.economics.currency='EUR',f=>f.economics.price_minor=1999,f=>f.economics.source_evidence_ids=[],
  f=>f.economics.source_evidence_ids=['fixture-price','fixture-price'],f=>f.economics.evidence_event_id=' ',
  f=>f.economics.expected_receipts_minor=2001,f=>f.economics.expected_receipts_minor=0];
 for(const key of ['expected_receipts_minor','variable_cost_minor','minimum_contribution_minor','minimum_margin_bps'])
  for(const value of [true,'1',null,-1,1.1,NaN,Infinity,Number.MAX_SAFE_INTEGER+1])
   edits.push(f=>f.economics[key]=value);
 edits.push(f=>f.economics.minimum_margin_bps=10001);
 for(const edit of edits){const f=economicsFixture(job,now);edit(f);assert.throws(()=>run(f),/ECONOMICS_EVIDENCE_REQUIRED/);}
});
test('economic evidence is tied to the exact business, account, platform, job and package',()=>{
 for(const key of ['job_id','business_id','account_id','platform','package_sha256']){
  const f=economicsFixture(job,now);f.economics[key]='wrong';assert.throws(()=>run(f),/ECONOMICS_SCOPE_MISMATCH/);
 }
});
test('economic observation and validity dates are checked at execution time',()=>{
 for(const change of [e=>e.observed_at_ms=now+1,e=>e.observed_at_ms=-1,e=>e.observed_at_ms='5000000',
  e=>e.valid_until_ms=now,e=>e.valid_until_ms=NaN,e=>e.valid_until_ms=true]){
  const f=economicsFixture(job,now);change(f.economics);assert.throws(()=>run(f),/ECONOMICS_EXPIRED_OR_INVALID/);
 }
 const f=economicsFixture(job,now);f.economics.valid_until_ms=now+1;assert.equal(run(f).contribution_minor,400);
});
