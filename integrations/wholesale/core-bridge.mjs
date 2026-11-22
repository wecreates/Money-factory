import {run} from './run.mjs';

const canonical = value => JSON.stringify(value, function(key, item) {
  return item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.keys(item).sort().map(k=>[k,item[k]])) : item;
});

// Implements the existing src/providers.js interface. Deliberately not a live provider.
export class WholesaleSandboxProvider {
  constructor(){this.name='wholesale-sandbox';this.supportsIdempotency=true;this.pending=new Map();}
  async health(){return {ok:false,provider:this.name,mode:'sandbox',sandbox_ready:true,production_ready:false,reason:'Account and supplier grants not verified'};}
  async execute(action,input,{idempotencyKey}={}){
    if(action!=='simulate')throw Error('WHOLESALE_ACTION_DISABLED');
    if(typeof idempotencyKey!=='string'||!idempotencyKey.trim())throw Error('IDEMPOTENCY_KEY_REQUIRED');
    const signature=canonical({action,input});
    const prior=this.pending.get(idempotencyKey);
    if(prior){if(prior.signature!==signature)throw Error('IDEMPOTENCY_CONFLICT');return structuredClone(await prior.result);}
    const result=Promise.resolve().then(()=>({ok:true,provider:this.name,dryRun:true,classification:'simulation',data:run(structuredClone(input)),verifiedFinancialEvent:false}));
    this.pending.set(idempotencyKey,{signature,result});
    try{return structuredClone(await result);}catch(error){this.pending.delete(idempotencyKey);throw error;}
  }
  normalizeWebhook(){throw Error('SANDBOX_WEBHOOKS_DISABLED');}
}

export function installWholesaleSandbox({providers,handlers}){
  if(typeof providers?.register!=='function'||typeof providers?.get!=='function'||!handlers||typeof handlers!=='object')throw Error('CORE_REGISTRY_AND_HANDLERS_REQUIRED');
  if(Object.hasOwn(handlers,'wholesale_sandbox'))throw Error('WHOLESALE_HANDLER_ALREADY_REGISTERED');
  // Reject overwriting an already registered provider, even if its type is unexpected.
  let existing;
  try{existing=providers.get('wholesale-sandbox');}catch(error){if(error.code!=='PROVIDER_UNAVAILABLE')throw error;}
  if(existing)throw Error('WHOLESALE_PROVIDER_ALREADY_REGISTERED');
  const adapter=new WholesaleSandboxProvider();providers.register(adapter);
  return {...handlers,wholesale_sandbox:async job=>{
    if(job?.payload?.publication_enabled===true||job?.payload?.paid_generation_enabled===true)throw Error('LIVE_MODE_DISABLED');
    return adapter.execute('simulate',job?.payload?.input,{idempotencyKey:job?.idempotencyKey});
  }};
}
