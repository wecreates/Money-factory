import test from 'node:test';
import assert from 'node:assert/strict';
import {buildCadenceEvidence,CADENCE_ACCEPTANCE_WINDOW_MS} from '../cadence.mjs';

const interval=300_000;
const runtime=(startedAt,cadence)=>({type:'monitor_runtime_resources',started_at:startedAt,
  ...(cadence===undefined?{}:{cadence})});
const scheduled=(startedAt,priorRuntime,extra={})=>buildCadenceEvidence({startedAt,priorRuntime,
  targetIntervalMs:interval,invocationSource:'schedule',
  invocationId:String(Math.floor(Date.parse(startedAt)/1000)),
  invocationAttempt:1,...extra});

test('first scheduled observation is explicitly insufficient and cannot satisfy the prerequisite',()=>{
  const evidence=scheduled('2026-11-24T19:00:30.000Z');
  assert.equal(evidence.status,'insufficient_scheduled_history');
  assert.equal(evidence.last_scheduled_slot_at,'2026-11-24T19:00:00.000Z');
  assert.equal(evidence.scheduled_start_drift_ms,30_000);
  assert.equal(evidence.acceptance_window_verified,false);
  assert.equal(evidence.prerequisite_passed,false);
  assert.equal(evidence.publication_enabled,false);
  assert.equal(evidence.external_delivery_performed,false);
});

test('18 and 57 minute durable gaps remain visible even when invocations are pushes',()=>{
  const eighteen=buildCadenceEvidence({startedAt:'2026-11-24T19:18:00.000Z',targetIntervalMs:interval,
    invocationSource:'push',priorRuntime:runtime('2026-11-24T19:00:00.000Z')});
  assert.equal(eighteen.durable_observed_gap_ms,18*60_000);
  assert.equal(eighteen.durable_missed_intervals,3);
  assert.equal(eighteen.status,'non_scheduled_invocation_no_history');
  assert.equal(eighteen.prerequisite_passed,false);
  const fiftySeven=buildCadenceEvidence({startedAt:'2026-11-24T19:57:00.000Z',targetIntervalMs:interval,
    invocationSource:'push',priorRuntime:runtime('2026-11-24T19:00:00.000Z')});
  assert.equal(fiftySeven.durable_missed_intervals,11);
  assert.equal(fiftySeven.prerequisite_passed,false);
});

test('push and manual invocations cannot build a scheduled acceptance chain',()=>{
  const first=scheduled('2026-11-24T19:00:30.000Z');
  const push=buildCadenceEvidence({startedAt:'2026-11-24T19:05:15.000Z',targetIntervalMs:interval,
    invocationSource:'push',priorRuntime:runtime(first.observed_at,first)});
  assert.equal(push.status,'non_scheduled_invocation');
  assert.equal(push.consecutive_scheduled_intervals,0);
  const manual=buildCadenceEvidence({startedAt:'2026-11-24T19:05:30.000Z',targetIntervalMs:interval,
    invocationSource:'workflow_dispatch',priorRuntime:runtime(push.observed_at,push)});
  assert.equal(manual.consecutive_scheduled_intervals,0);
  assert.equal(manual.prerequisite_passed,false);
});

test('manual reruns and non-increasing scheduled run IDs cannot advance unattended acceptance',()=>{
  const first=scheduled('2026-11-24T19:00:10.000Z',undefined,{invocationId:'1001'});
  const rerun=scheduled('2026-11-24T19:05:10.000Z',runtime(first.observed_at,first),
    {invocationId:'1001',invocationAttempt:2});
  assert.equal(rerun.status,'unqualified_scheduled_invocation');
  assert.equal(rerun.last_scheduled_observed_at,first.observed_at);
  assert.equal(rerun.consecutive_scheduled_intervals,0);
  assert.equal(rerun.prerequisite_passed,false);
  const duplicate=scheduled('2026-11-24T19:05:10.000Z',runtime(first.observed_at,first),
    {invocationId:'1001',invocationAttempt:1});
  assert.equal(duplicate.status,'non_increasing_scheduled_invocation_id');
  assert.equal(duplicate.scheduled_chain_status,'invalid_scheduled_observation');
  assert.equal(duplicate.prerequisite_passed,false);
  const decreasing=scheduled('2026-11-24T19:05:10.000Z',runtime(first.observed_at,first),
    {invocationId:'1000',invocationAttempt:1});
  assert.equal(decreasing.status,'non_increasing_scheduled_invocation_id');
  const arbitrary=scheduled('2026-11-24T19:05:10.000Z',runtime(first.observed_at,first),
    {invocationId:'run-A',invocationAttempt:1});
  assert.equal(arbitrary.status,'unqualified_scheduled_invocation');
  const missingId=buildCadenceEvidence({startedAt:'2026-11-24T19:05:10.000Z',
    targetIntervalMs:interval,invocationSource:'schedule',invocationAttempt:1,
    priorRuntime:runtime(first.observed_at,first)});
  assert.equal(missingId.status,'unqualified_scheduled_invocation');
  assert.equal(missingId.consecutive_scheduled_intervals,0);
});

test('alternating arbitrary IDs cannot create scheduled continuity',()=>{
  let evidence=scheduled('2026-11-24T19:00:10.000Z',undefined,{invocationId:'run-A'});
  assert.equal(evidence.status,'unqualified_scheduled_invocation');
  for(let index=1;index<=300;index++){
    const current=new Date(Date.parse('2026-11-24T19:00:10.000Z')+index*interval).toISOString();
    evidence=scheduled(current,runtime(evidence.observed_at,evidence),
      {invocationId:index%2?'run-B':'run-A'});
    assert.equal(evidence.prerequisite_passed,false);
  }
});

test('a non-scheduled run detects an overdue missing scheduled invocation',()=>{
  const first=scheduled('2026-11-24T19:00:30.000Z');
  const boundaryPush=buildCadenceEvidence({startedAt:'2026-11-24T19:06:01.000Z',targetIntervalMs:interval,
    invocationSource:'push',priorRuntime:runtime(first.observed_at,first)});
  assert.equal(boundaryPush.status,'scheduled_interval_overdue');
  assert.equal(boundaryPush.scheduled_deadline_gap_ms,361_000);
  assert.equal(boundaryPush.scheduled_missed_intervals,1);
  const push=buildCadenceEvidence({startedAt:'2026-11-24T19:18:00.000Z',targetIntervalMs:interval,
    invocationSource:'push',priorRuntime:runtime(first.observed_at,first)});
  assert.equal(push.status,'scheduled_interval_overdue');
  assert.equal(push.scheduled_missed_intervals,3);
  assert.equal(push.continuity_started_slot_at,null);
  assert.equal(push.prerequisite_passed,false);
});

test('fixed cron slots prevent one-minute grace from accumulating into false acceptance',()=>{
  const first=scheduled('2026-11-24T19:00:00.000Z');
  const second=scheduled('2026-11-24T19:06:00.000Z',runtime(first.observed_at,first));
  assert.equal(second.status,'building_scheduled_continuity');
  assert.equal(second.consecutive_scheduled_intervals,1);
  const third=scheduled('2026-11-24T19:12:00.000Z',runtime(second.observed_at,second));
  assert.equal(third.status,'scheduled_slot_drift_exceeded');
  assert.equal(third.scheduled_chain_status,'invalid_scheduled_observation');
  assert.equal(third.prerequisite_passed,false);
  const push=buildCadenceEvidence({startedAt:'2026-11-24T19:13:00.000Z',targetIntervalMs:interval,
    invocationSource:'push',priorRuntime:runtime(third.observed_at,third)});
  assert.equal(push.scheduled_chain_status,'invalid_scheduled_observation');
  const baseline=scheduled('2026-11-24T19:15:10.000Z',runtime(push.observed_at,push));
  assert.equal(baseline.status,'prior_scheduled_chain_not_qualifying');
  assert.equal(baseline.scheduled_chain_status,'insufficient_scheduled_history');
  const resumed=scheduled('2026-11-24T19:20:10.000Z',runtime(baseline.observed_at,baseline));
  assert.equal(resumed.status,'building_scheduled_continuity');
  assert.equal(resumed.consecutive_scheduled_intervals,1);
});

test('240 six-minute observations cannot accumulate a false 24-hour window',()=>{
  let evidence=scheduled('2026-11-23T19:00:00.000Z');
  let everAccepted=false;
  for(let index=1;index<=240;index++){
    const current=new Date(Date.parse('2026-11-23T19:00:00.000Z')+index*6*60_000).toISOString();
    evidence=scheduled(current,runtime(evidence.observed_at,evidence));
    everAccepted ||= evidence.prerequisite_passed;
  }
  assert.equal(everAccepted,false);
  assert.equal(evidence.prerequisite_passed,false);
  assert.notEqual(evidence.scheduled_chain_status,'continuous_scheduled_window_verified');
});

test('a missing cron slot resets continuity and records the exact missed slot count',()=>{
  const first=scheduled('2026-11-24T19:00:10.000Z');
  const next=scheduled('2026-11-24T19:15:10.000Z',runtime(first.observed_at,first));
  assert.equal(next.status,'missed_scheduled_intervals');
  assert.equal(next.scheduled_missed_intervals,2);
  assert.equal(next.consecutive_scheduled_intervals,0);
  assert.equal(next.prerequisite_passed,false);
});

test('only 288 consecutive scheduled slots can satisfy the 24-hour prerequisite',()=>{
  let evidence=scheduled('2026-11-23T19:00:10.000Z');
  for(let index=1;index<=288;index++){
    const current=new Date(Date.parse('2026-11-23T19:00:10.000Z')+index*interval).toISOString();
    evidence=scheduled(current,runtime(evidence.observed_at,evidence));
  }
  assert.equal(evidence.status,'continuous_scheduled_window_verified');
  assert.equal(evidence.scheduled_continuity_window_ms,CADENCE_ACCEPTANCE_WINDOW_MS);
  assert.equal(evidence.consecutive_scheduled_intervals,288);
  assert.equal(evidence.acceptance_window_verified,true);
  assert.equal(evidence.prerequisite_passed,true);
  const timelyPush=buildCadenceEvidence({startedAt:'2026-11-24T19:04:00.000Z',targetIntervalMs:interval,
    invocationSource:'push',priorRuntime:runtime(evidence.observed_at,evidence)});
  assert.equal(timelyPush.status,'non_scheduled_invocation');
  assert.equal(timelyPush.consecutive_scheduled_intervals,288);
  assert.equal(timelyPush.prerequisite_passed,true);
});

test('internally impossible retained chains fail closed',()=>{
  const first=scheduled('2026-11-24T19:00:10.000Z');
  const forged={...first,status:'building_scheduled_continuity',
    continuity_started_slot_at:'2026-11-24T18:00:00.000Z',scheduled_continuity_window_ms:3_600_000,
    consecutive_scheduled_intervals:0};
  const result=scheduled('2026-11-24T19:05:10.000Z',runtime(first.observed_at,forged));
  assert.equal(result.status,'invalid_prior_chain');
  assert.equal(result.prerequisite_passed,false);
  assert.equal(result.consecutive_scheduled_intervals,0);
  const detached={...first,observed_at:'2026-11-24T18:55:10.000Z'};
  const detachedResult=scheduled('2026-11-24T19:05:10.000Z',runtime(first.observed_at,detached));
  assert.equal(detachedResult.status,'invalid_prior_chain');
  assert.equal(detachedResult.prerequisite_passed,false);
  const validSecond=scheduled('2026-11-24T19:05:10.000Z',runtime(first.observed_at,first));
  const hiddenMiss={...validSecond,scheduled_missed_intervals:1};
  const hiddenMissResult=scheduled('2026-11-24T19:10:10.000Z',runtime(validSecond.observed_at,hiddenMiss));
  assert.equal(hiddenMissResult.status,'invalid_prior_chain');
  assert.equal(hiddenMissResult.prerequisite_passed,false);
  const future={...first,last_scheduled_observed_at:'2026-11-24T19:10:10.000Z',
    last_scheduled_slot_at:'2026-11-24T19:10:00.000Z'};
  const futureResult=scheduled('2026-11-24T19:15:10.000Z',runtime(first.observed_at,future));
  assert.equal(futureResult.status,'invalid_prior_chain');
  assert.equal(futureResult.prerequisite_passed,false);
  const pushedAsScheduled={...validSecond,invocation_source:'push'};
  const pushedResult=scheduled('2026-11-24T19:10:10.000Z',
    runtime(validSecond.observed_at,pushedAsScheduled));
  assert.equal(pushedResult.status,'invalid_prior_chain');
  assert.equal(pushedResult.prerequisite_passed,false);
  const wrongAttempt={...validSecond,invocation_attempt:2};
  const attemptResult=scheduled('2026-11-24T19:10:10.000Z',
    runtime(validSecond.observed_at,wrongAttempt));
  assert.equal(attemptResult.status,'invalid_prior_chain');
  const badLastId={...validSecond,last_scheduled_invocation_id:'A'};
  const badLastIdResult=scheduled('2026-11-24T19:10:10.000Z',
    runtime(validSecond.observed_at,badLastId));
  assert.equal(badLastIdResult.status,'invalid_prior_chain');
  assert.equal(badLastIdResult.prerequisite_passed,false);
  const impossibleGap={...validSecond,scheduled_observed_gap_ms:361_000};
  const gapResult=scheduled('2026-11-24T19:10:10.000Z',
    runtime(validSecond.observed_at,impossibleGap));
  assert.equal(gapResult.status,'invalid_prior_chain');
  const forgedCount={...validSecond,consecutive_scheduled_intervals:2};
  const countResult=scheduled('2026-11-24T19:10:10.000Z',
    runtime(validSecond.observed_at,forgedCount));
  assert.equal(countResult.status,'invalid_prior_chain');
  const forgedDuration={...validSecond,scheduled_continuity_window_ms:600_000};
  const durationResult=scheduled('2026-11-24T19:10:10.000Z',
    runtime(validSecond.observed_at,forgedDuration));
  assert.equal(durationResult.status,'invalid_prior_chain');
  const forgedStatus={...validSecond,status:'continuous_scheduled_window_verified'};
  const statusResult=scheduled('2026-11-24T19:10:10.000Z',
    runtime(validSecond.observed_at,forgedStatus));
  assert.equal(statusResult.status,'invalid_prior_chain');
});

test('malformed, nonmonotonic and invalid configuration all fail closed',()=>{
  const malformed=scheduled('2026-11-24T19:05:00.000Z',runtime('2026-11-24T19:00:00.000Z',
    {type:'monitor_cadence_evidence',prerequisite_passed:true}));
  assert.equal(malformed.status,'invalid_prior_chain');
  assert.equal(malformed.prerequisite_passed,false);
  const first=scheduled('2026-11-24T19:05:00.000Z');
  const reversed=scheduled('2026-11-24T19:00:00.000Z',runtime(first.observed_at,first));
  assert.equal(reversed.status,'non_monotonic_scheduled_observation');
  assert.throws(()=>buildCadenceEvidence({startedAt:'2026-11-24T19:00:00.000Z',targetIntervalMs:0}),
    /positive integer/);
  assert.throws(()=>buildCadenceEvidence({startedAt:'2026-11-24T19:00:00.000Z',targetIntervalMs:interval,
    allowedStartDriftMs:interval}),/below the interval/);
  assert.throws(()=>buildCadenceEvidence({startedAt:'2026-11-24T19:00:00.000Z',targetIntervalMs:interval,
    requiredContinuityWindowMs:interval+1}),/whole number of intervals/);
});
