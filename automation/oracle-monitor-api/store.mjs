import crypto from 'node:crypto';

export function createStore(seed={}){
  return {
    watches: Array.isArray(seed.watches)?seed.watches:[],
    events: Array.isArray(seed.events)?seed.events:[]
  };
}

export function createWatch(store,{clientId,kind='change',targetUrl,label='Watch'}){
  if(!clientId) throw new Error('clientId required');
  const u=new URL(targetUrl);
  if(!['http:','https:'].includes(u.protocol)) throw new Error('http(s) target required');
  const watch={
    id:crypto.randomUUID(),
    client_id:String(clientId),
    kind:String(kind),
    target_url:u.toString(),
    label:String(label),
    last_value:null,
    last_checked_at:null,
    last_change_at:null,
    status:'active'
  };
  store.watches.unshift(watch);
  return watch;
}

export function listWatches(store,clientId){
  return store.watches.filter(w=>w.client_id===String(clientId));
}

export function deleteWatch(store,clientId,id){
  const before=store.watches.length;
  store.watches=store.watches.filter(w=>!(w.client_id===String(clientId)&&w.id===String(id)));
  return store.watches.length!==before;
}

export function listEvents(store,clientId){
  return store.events.filter(e=>e.client_id===String(clientId));
}
