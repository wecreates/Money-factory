const ALERT_KINDS=new Set(['outage','recovery']);
export const MONITOR_EVENT_LIMIT=500;

export function isPendingAlertIntent(event){
  if(event===null || typeof event!=='object' || Array.isArray(event)) return false;
  const exact=new Set(['id','watch_id','at','type','alert_kind','outage_started_at','label',
    'target_url','delivery_status','delivery_attempts','external_delivery_performed',
    'publication_enabled']);
  return Object.keys(event).length===exact.size
    && Object.keys(event).every(key=>exact.has(key))
    && typeof event.id==='string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(event.id)
    && typeof event.watch_id==='string' && event.watch_id.length>0
    && Number.isSafeInteger(event.at) && event.at>0
    && event.type==='alert_intent' && ALERT_KINDS.has(event.alert_kind)
    && Number.isSafeInteger(event.outage_started_at) && event.outage_started_at>0
    && event.at>=event.outage_started_at
    && typeof event.label==='string' && event.label.length>0
    && typeof event.target_url==='string'
    && ['http:','https:'].includes(new URL(event.target_url).protocol)
    && event.delivery_status==='pending' && event.delivery_attempts===0
    && event.external_delivery_performed===false && event.publication_enabled===false;
}

export function pendingAlertIntents(events){
  if(!Array.isArray(events)) throw new Error('events must be an array');
  return events.filter(event=>{
    try{return isPendingAlertIntent(event);}catch{return false;}
  }).map(event=>({...event}));
}

export function alertIntentKey(watchId,targetUrl,kind,outageStartedAt){
  return JSON.stringify([watchId,targetUrl,kind,outageStartedAt]);
}
