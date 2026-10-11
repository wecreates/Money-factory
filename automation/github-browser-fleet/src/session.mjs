// Playwright accepts a storage-state object; no temporary credential file is needed.
export function sessionForBusiness(raw,business){
  if(!raw) return undefined;
  try{
    const sessions=JSON.parse(raw);
    if(!sessions||typeof sessions!=='object'||Array.isArray(sessions)) throw new Error();
    if(!Object.hasOwn(sessions,business)) return undefined;
    if(typeof sessions[business]!=='string'||!sessions[business]) throw new Error();
    const state=JSON.parse(Buffer.from(sessions[business],'base64').toString('utf8'));
    if(!state||!Array.isArray(state.cookies)||!Array.isArray(state.origins)) throw new Error();
    return state;
  }catch{
    // Never echo malformed input or parser errors, which could contain secrets.
    throw new Error('Invalid browser session configuration');
  }
}
