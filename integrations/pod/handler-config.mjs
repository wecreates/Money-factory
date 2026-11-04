import {types as utilTypes} from 'node:util';

// Handler construction is an authority boundary too. Snapshot only the named
// own data properties before reading credentials, callbacks or timing controls.
export function exactHandlerConfig(value,fields,defaults,errorCode){
 const fail=()=>{throw Error(errorCode);};
 if(!value||typeof value!=='object'||utilTypes.isProxy(value))fail();
 const prototype=Object.getPrototypeOf(value);
 if(prototype!==Object.prototype&&prototype!==null)fail();
 const snapshot=Object.create(null);
 for(const field of fields){
  const descriptor=Object.getOwnPropertyDescriptor(value,field);
  if(!descriptor){snapshot[field]=Object.hasOwn(defaults,field)?defaults[field]:undefined;continue;}
  if(!Object.hasOwn(descriptor,'value'))fail();
  snapshot[field]=descriptor.value;
 }
 return snapshot;
}
