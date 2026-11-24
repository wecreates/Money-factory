export const CADENCE_ALLOWED_START_DRIFT_MS=60_000;
export const CADENCE_ACCEPTANCE_WINDOW_MS=24*60*60*1000;

const INVOCATION_SOURCES=new Set(['schedule','push','workflow_dispatch','local','unknown']);
const safePositive=value=>Number.isSafeInteger(value) && value>0;
const isRunId=value=>typeof value==='string' && /^[1-9]\d*$/.test(value);

function parseTimestamp(value){
  if(typeof value!=='string') return null;
  const milliseconds=Date.parse(value);
  if(!safePositive(milliseconds)) return null;
  return {milliseconds,iso:new Date(milliseconds).toISOString()};
}

function missedDeadlines(gap,targetIntervalMs,allowedStartDriftMs){
  const deadline=targetIntervalMs+allowedStartDriftMs;
  return gap<=deadline?0:Math.ceil((gap-deadline)/targetIntervalMs);
}

function emptyScheduled(){
  return {last_scheduled_observed_at:null,last_scheduled_slot_at:null,last_scheduled_invocation_id:null,
    scheduled_start_drift_ms:null,scheduled_observed_gap_ms:null,scheduled_deadline_gap_ms:null,
    scheduled_missed_intervals:null,
    scheduled_chain_status:'insufficient_scheduled_history',consecutive_scheduled_intervals:0,
    continuity_started_slot_at:null,
    scheduled_continuity_window_ms:0,acceptance_window_verified:false,prerequisite_passed:false};
}

function validateScheduledChain(cadence,targetIntervalMs,allowedStartDriftMs,
  requiredContinuityWindowMs){
  if(cadence===null || typeof cadence!=='object' || Array.isArray(cadence)) return false;
  if(cadence.schema_version!==2 || cadence.type!=='monitor_cadence_evidence'
      || cadence.target_interval_ms!==targetIntervalMs
      || cadence.allowed_start_drift_ms!==allowedStartDriftMs
      || cadence.required_continuity_window_ms!==requiredContinuityWindowMs
      || !INVOCATION_SOURCES.has(cadence.invocation_source)
      || (cadence.invocation_id!==null && typeof cadence.invocation_id!=='string')
      || (cadence.invocation_attempt!==null && !safePositive(cadence.invocation_attempt))
      || typeof cadence.scheduled_invocation_qualified!=='boolean'
      || typeof cadence.acceptance_window_verified!=='boolean'
      || cadence.publication_enabled!==false || cadence.external_delivery_performed!==false
      || cadence.prerequisite_passed!==cadence.acceptance_window_verified){
    return false;
  }
  const provenanceQualified=cadence.invocation_source==='schedule'
    && isRunId(cadence.invocation_id)
    && cadence.invocation_attempt===1;
  if(cadence.scheduled_invocation_qualified!==provenanceQualified) return false;
  const qualifiedStatus={
    insufficient_scheduled_history:new Set(['insufficient_scheduled_history','invalid_prior_chain',
      'prior_scheduled_chain_not_qualifying']),
    building_scheduled_continuity:new Set(['building_scheduled_continuity']),
    continuous_scheduled_window_verified:new Set(['continuous_scheduled_window_verified']),
    invalid_scheduled_observation:new Set(['scheduled_slot_drift_exceeded',
      'non_monotonic_scheduled_observation','non_increasing_scheduled_invocation_id',
      'missed_scheduled_intervals'])
  };
  const unqualifiedStatus=new Set(['non_scheduled_invocation_no_history','non_scheduled_invocation',
    'invalid_prior_chain','unqualified_scheduled_invocation',
    'unqualified_scheduled_invocation_overdue','scheduled_interval_overdue',
    'non_monotonic_scheduled_observation']);
  if(cadence.scheduled_invocation_qualified){
    if(!qualifiedStatus[cadence.scheduled_chain_status]?.has(cadence.status)) return false;
  }else if(!unqualifiedStatus.has(cadence.status)) return false;
  if(cadence.last_scheduled_observed_at===null){
    return cadence.last_scheduled_slot_at===null && cadence.last_scheduled_invocation_id===null
      && cadence.scheduled_start_drift_ms===null
      && cadence.scheduled_observed_gap_ms===null
      && cadence.scheduled_deadline_gap_ms===null
      && cadence.scheduled_missed_intervals===null
      && cadence.scheduled_chain_status==='insufficient_scheduled_history'
      && cadence.consecutive_scheduled_intervals===0
      && cadence.continuity_started_slot_at===null
      && cadence.scheduled_continuity_window_ms===0
      && cadence.acceptance_window_verified===false;
  }
  const last=parseTimestamp(cadence.last_scheduled_observed_at);
  const slot=parseTimestamp(cadence.last_scheduled_slot_at);
  const observed=parseTimestamp(cadence.observed_at);
  if(last===null || slot===null || slot.milliseconds%targetIntervalMs!==0
      || observed===null || last.milliseconds>observed.milliseconds
      || (cadence.scheduled_invocation_qualified && last.milliseconds!==observed.milliseconds)
      || !isRunId(cadence.last_scheduled_invocation_id)
      || (cadence.scheduled_invocation_qualified
        && cadence.invocation_id!==cadence.last_scheduled_invocation_id)
      || last.milliseconds<slot.milliseconds
      || cadence.scheduled_start_drift_ms!==last.milliseconds-slot.milliseconds
      || cadence.scheduled_start_drift_ms<0
      || !Number.isSafeInteger(cadence.consecutive_scheduled_intervals)
      || cadence.consecutive_scheduled_intervals<0){
    return false;
  }
  const continuity=parseTimestamp(cadence.continuity_started_slot_at);
  if(continuity===null){
    return cadence.scheduled_chain_status==='invalid_scheduled_observation'
      && cadence.consecutive_scheduled_intervals===0
      && cadence.scheduled_continuity_window_ms===0
      && cadence.acceptance_window_verified===false;
  }
  if(continuity.milliseconds%targetIntervalMs!==0 || continuity.milliseconds>slot.milliseconds) return false;
  const expectedWindow=slot.milliseconds-continuity.milliseconds;
  const expectedIntervals=expectedWindow/targetIntervalMs;
  if(!Number.isSafeInteger(expectedIntervals)
      || cadence.scheduled_continuity_window_ms!==expectedWindow
      || cadence.consecutive_scheduled_intervals!==expectedIntervals
      || cadence.scheduled_start_drift_ms>allowedStartDriftMs){
    return false;
  }
  if(cadence.scheduled_chain_status==='insufficient_scheduled_history'){
    return expectedIntervals===0
      && (cadence.scheduled_missed_intervals===null || cadence.scheduled_missed_intervals===0)
      && cadence.acceptance_window_verified===false;
  }
  if(cadence.scheduled_chain_status==='building_scheduled_continuity'){
    return expectedIntervals>0 && cadence.scheduled_missed_intervals===0
      && safePositive(cadence.scheduled_observed_gap_ms)
      && cadence.scheduled_observed_gap_ms>=targetIntervalMs-allowedStartDriftMs
      && cadence.scheduled_observed_gap_ms<=targetIntervalMs+allowedStartDriftMs
      && expectedWindow<requiredContinuityWindowMs
      && cadence.acceptance_window_verified===false;
  }
  return cadence.scheduled_chain_status==='continuous_scheduled_window_verified'
    && cadence.scheduled_missed_intervals===0
    && safePositive(cadence.scheduled_observed_gap_ms)
    && cadence.scheduled_observed_gap_ms>=targetIntervalMs-allowedStartDriftMs
    && cadence.scheduled_observed_gap_ms<=targetIntervalMs+allowedStartDriftMs
    && cadence.scheduled_continuity_window_ms===expectedWindow
    && cadence.consecutive_scheduled_intervals===expectedIntervals
    && cadence.acceptance_window_verified===(expectedWindow>=requiredContinuityWindowMs)
    && cadence.acceptance_window_verified===true;
}

function durableGap(priorRuntime,current,targetIntervalMs,allowedStartDriftMs){
  if(priorRuntime===undefined){
    return {previous_durable_observed_at:null,durable_observed_gap_ms:null,
      durable_overdue_by_ms:null,durable_missed_intervals:null,durable_status:'insufficient_history'};
  }
  if(priorRuntime===null || typeof priorRuntime!=='object' || Array.isArray(priorRuntime)
      || priorRuntime.type!=='monitor_runtime_resources'){
    return {previous_durable_observed_at:null,durable_observed_gap_ms:null,
      durable_overdue_by_ms:null,durable_missed_intervals:null,durable_status:'invalid_prior_evidence'};
  }
  const previous=parseTimestamp(priorRuntime.started_at);
  if(previous===null){
    return {previous_durable_observed_at:null,durable_observed_gap_ms:null,
      durable_overdue_by_ms:null,durable_missed_intervals:null,durable_status:'invalid_prior_evidence'};
  }
  const gap=current.milliseconds-previous.milliseconds;
  if(gap<=0){
    return {previous_durable_observed_at:previous.iso,durable_observed_gap_ms:gap,
      durable_overdue_by_ms:null,durable_missed_intervals:null,durable_status:'non_monotonic_observation'};
  }
  const missed=missedDeadlines(gap,targetIntervalMs,allowedStartDriftMs);
  return {previous_durable_observed_at:previous.iso,durable_observed_gap_ms:gap,
    durable_overdue_by_ms:Math.max(0,gap-targetIntervalMs),durable_missed_intervals:missed,
    durable_status:missed===0?'within_allowed_gap':'missed_intervals'};
}

function resetAtSchedule(base,current,slot,drift,status,invocationId,scheduledGap=null,missed=null,
  usableBaseline=true){
  return {...base,status,last_scheduled_observed_at:current.iso,last_scheduled_slot_at:slot.iso,
    last_scheduled_invocation_id:invocationId,
    scheduled_start_drift_ms:drift,scheduled_observed_gap_ms:scheduledGap,
    scheduled_missed_intervals:missed,
    scheduled_chain_status:usableBaseline?'insufficient_scheduled_history':'invalid_scheduled_observation',
    consecutive_scheduled_intervals:0,continuity_started_slot_at:usableBaseline?slot.iso:null,
    scheduled_continuity_window_ms:0,
    acceptance_window_verified:false,prerequisite_passed:false};
}

export function buildCadenceEvidence({startedAt,priorRuntime,targetIntervalMs,invocationSource='unknown',
  invocationId=null,invocationAttempt=null,allowedStartDriftMs=CADENCE_ALLOWED_START_DRIFT_MS,
  requiredContinuityWindowMs=CADENCE_ACCEPTANCE_WINDOW_MS}={}){
  const current=parseTimestamp(startedAt);
  if(current===null) throw new Error('valid cadence start timestamp required');
  if(!safePositive(targetIntervalMs)) throw new Error('cadence interval must be a positive integer');
  if(!Number.isSafeInteger(allowedStartDriftMs) || allowedStartDriftMs<0
      || allowedStartDriftMs>=targetIntervalMs){
    throw new Error('cadence allowed start drift must be a nonnegative integer below the interval');
  }
  if(!safePositive(requiredContinuityWindowMs)
      || requiredContinuityWindowMs%targetIntervalMs!==0){
    throw new Error('cadence continuity window must be a positive whole number of intervals');
  }
  if(!INVOCATION_SOURCES.has(invocationSource)) invocationSource='unknown';
  if(invocationId!==null) invocationId=String(invocationId);
  if(typeof invocationAttempt==='string' && /^\d+$/.test(invocationAttempt)) invocationAttempt=Number(invocationAttempt);
  if(!safePositive(invocationAttempt)) invocationAttempt=null;
  const scheduledInvocationQualified=invocationSource==='schedule'
    && isRunId(invocationId) && invocationAttempt===1;
  const base={schema_version:2,type:'monitor_cadence_evidence',observed_at:current.iso,
    invocation_source:invocationSource,invocation_id:invocationId,invocation_attempt:invocationAttempt,
    scheduled_invocation_qualified:scheduledInvocationQualified,target_interval_ms:targetIntervalMs,
    allowed_start_drift_ms:allowedStartDriftMs,required_continuity_window_ms:requiredContinuityWindowMs,
    ...durableGap(priorRuntime,current,targetIntervalMs,allowedStartDriftMs),...emptyScheduled(),
    status:'insufficient_scheduled_history',publication_enabled:false,external_delivery_performed:false};
  const priorCadence=priorRuntime?.cadence;
  const priorStarted=parseTimestamp(priorRuntime?.started_at);
  const priorChainValid=priorCadence!==undefined && priorStarted!==null
    && priorCadence.observed_at===priorStarted.iso && validateScheduledChain(priorCadence,
      targetIntervalMs,allowedStartDriftMs,requiredContinuityWindowMs);
  if(!scheduledInvocationQualified){
    if(!priorChainValid){
      const status=invocationSource==='schedule'?'unqualified_scheduled_invocation'
        :priorCadence===undefined?'non_scheduled_invocation_no_history':'invalid_prior_chain';
      return {...base,status};
    }
    const carried={...base,last_scheduled_observed_at:priorCadence.last_scheduled_observed_at,
      last_scheduled_slot_at:priorCadence.last_scheduled_slot_at,
      last_scheduled_invocation_id:priorCadence.last_scheduled_invocation_id,
      scheduled_start_drift_ms:priorCadence.scheduled_start_drift_ms,
      scheduled_observed_gap_ms:priorCadence.scheduled_observed_gap_ms,
      scheduled_deadline_gap_ms:priorCadence.scheduled_deadline_gap_ms,
      scheduled_missed_intervals:priorCadence.scheduled_missed_intervals,
      scheduled_chain_status:priorCadence.scheduled_chain_status,
      consecutive_scheduled_intervals:priorCadence.consecutive_scheduled_intervals,
      continuity_started_slot_at:priorCadence.continuity_started_slot_at,
      scheduled_continuity_window_ms:priorCadence.scheduled_continuity_window_ms,
      acceptance_window_verified:priorCadence.acceptance_window_verified,
      prerequisite_passed:priorCadence.prerequisite_passed,
      status:invocationSource==='schedule'?'unqualified_scheduled_invocation':'non_scheduled_invocation'};
    const lastSlot=parseTimestamp(carried.last_scheduled_slot_at);
    if(lastSlot===null) return carried;
    const deadlineGap=current.milliseconds-lastSlot.milliseconds;
    const missed=deadlineGap>0
      ?missedDeadlines(deadlineGap,targetIntervalMs,allowedStartDriftMs):null;
    if(missed===null || missed>0){
      const overdueStatus=invocationSource==='schedule'
        ?'unqualified_scheduled_invocation_overdue':'scheduled_interval_overdue';
      return {...carried,status:missed===null?'non_monotonic_scheduled_observation':overdueStatus,
        scheduled_deadline_gap_ms:deadlineGap,scheduled_missed_intervals:missed,
        scheduled_chain_status:'invalid_scheduled_observation',
        consecutive_scheduled_intervals:0,continuity_started_slot_at:null,
        scheduled_continuity_window_ms:0,acceptance_window_verified:false,prerequisite_passed:false};
    }
    return carried;
  }
  const slotMilliseconds=Math.floor(current.milliseconds/targetIntervalMs)*targetIntervalMs;
  const slot={milliseconds:slotMilliseconds,iso:new Date(slotMilliseconds).toISOString()};
  const drift=current.milliseconds-slot.milliseconds;
  if(drift>allowedStartDriftMs){
    return resetAtSchedule(base,current,slot,drift,'scheduled_slot_drift_exceeded',invocationId,null,null,false);
  }
  if(!priorChainValid || priorCadence.last_scheduled_observed_at===null){
    return resetAtSchedule(base,current,slot,drift,
      priorCadence===undefined || priorCadence?.last_scheduled_observed_at===null
        ?'insufficient_scheduled_history':'invalid_prior_chain',invocationId);
  }
  const previous=parseTimestamp(priorCadence.last_scheduled_observed_at);
  const previousSlot=parseTimestamp(priorCadence.last_scheduled_slot_at);
  const gap=current.milliseconds-previous.milliseconds;
  const slotGap=slot.milliseconds-previousSlot.milliseconds;
  if(gap<=0 || slotGap<=0){
    return resetAtSchedule(base,current,slot,drift,'non_monotonic_scheduled_observation',invocationId,
      gap,null,false);
  }
  if(BigInt(invocationId)<=BigInt(priorCadence.last_scheduled_invocation_id)){
    return resetAtSchedule(base,current,slot,drift,'non_increasing_scheduled_invocation_id',invocationId,
      gap,null,false);
  }
  const missed=Math.max(0,slotGap/targetIntervalMs-1);
  if(!Number.isSafeInteger(missed) || missed>0){
    return resetAtSchedule(base,current,slot,drift,'missed_scheduled_intervals',invocationId,gap,
      Number.isSafeInteger(missed)?missed:null);
  }
  if(!['insufficient_scheduled_history','building_scheduled_continuity',
    'continuous_scheduled_window_verified'].includes(priorCadence.scheduled_chain_status)){
    return resetAtSchedule(base,current,slot,drift,'prior_scheduled_chain_not_qualifying',invocationId,gap,0);
  }
  const continuity=parseTimestamp(priorCadence.continuity_started_slot_at);
  const window=slot.milliseconds-continuity.milliseconds;
  const intervals=window/targetIntervalMs;
  const acceptance=window>=requiredContinuityWindowMs && Number.isSafeInteger(intervals)
    && intervals>=requiredContinuityWindowMs/targetIntervalMs;
  return {...base,status:acceptance?'continuous_scheduled_window_verified':'building_scheduled_continuity',
    last_scheduled_observed_at:current.iso,last_scheduled_slot_at:slot.iso,
    last_scheduled_invocation_id:invocationId,
    scheduled_start_drift_ms:drift,scheduled_observed_gap_ms:gap,scheduled_missed_intervals:0,
    scheduled_chain_status:acceptance?'continuous_scheduled_window_verified':'building_scheduled_continuity',
    consecutive_scheduled_intervals:intervals,continuity_started_slot_at:continuity.iso,
    scheduled_continuity_window_ms:window,acceptance_window_verified:acceptance,
    prerequisite_passed:acceptance};
}
