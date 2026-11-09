import {createPodAuthorityHandler} from './authority-handler.mjs';
import {createPodEventHandler} from './event-handler.mjs';
import {exactHandlerConfig} from './handler-config.mjs';
import {validPodBearerKey,validPodSharedKey} from './key-contract.mjs';

const invalid='POD_BRIDGE_CONFIG_INVALID';
const validPath=path=>typeof path==='string'&&path.length<=128&&/^\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_-]+$/.test(path);

// Install in the existing authoritative host before body parsing. This only
// dispatches configured POD routes; it does not create a server, pool or grants.
export function createPodBridgeDispatcher(config){
 const {grantPath,eventPath,loadSnapshot,pool,authKey,signingKey,outboxKey}=exactHandlerConfig(config,
  ['grantPath','eventPath','loadSnapshot','pool','authKey','signingKey','outboxKey'],{},invalid);
 if(!validPath(grantPath)||!validPath(eventPath)||grantPath===eventPath||
  !validPodBearerKey(authKey)||!validPodSharedKey(signingKey)||!validPodSharedKey(outboxKey)||
  new Set([authKey,signingKey,outboxKey]).size!==3)throw Error(invalid);
 const grant=createPodAuthorityHandler({loadSnapshot,authKey,signingKey});
 const event=createPodEventHandler({pool,key:outboxKey});
 return async(req,res)=>{
  // Match the unmodified origin-form target. No decoding, path normalization,
  // query stripping or re-routing after an auth failure.
  const target=req.url;
  if(target===grantPath)await grant(req,res);
  else if(target===eventPath)await event(req,res);
  else return false;
  return true;
 };
}
