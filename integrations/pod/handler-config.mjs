import {types as utilTypes} from 'node:util';

const invalidArguments=()=>{throw Error('HANDLER_CONFIG_ARGUMENTS_INVALID');};

function exactFields(value){
 if(!value||typeof value!=='object'||utilTypes.isProxy(value)||!Array.isArray(value)||
  Object.getPrototypeOf(value)!==Array.prototype)invalidArguments();
 const length=Object.getOwnPropertyDescriptor(value,'length')?.value;
 if(!Number.isInteger(length)||length<1||length>64)invalidArguments();
 const fields=[],seen=new Set();
 for(let index=0;index<length;index++){
  const descriptor=Object.getOwnPropertyDescriptor(value,String(index));
  const field=descriptor?.value;
  if(!descriptor||!Object.hasOwn(descriptor,'value')||typeof field!=='string'||
   field.length<1||field.length>128||seen.has(field))invalidArguments();
  seen.add(field);fields.push(field);
 }
 return fields;
}

function exactDefaults(value,fields){
 if(!value||typeof value!=='object'||utilTypes.isProxy(value))invalidArguments();
 const prototype=Object.getPrototypeOf(value);
 if(prototype!==Object.prototype&&prototype!==null)invalidArguments();
 const snapshot=Object.create(null);
 for(const field of fields){
  const descriptor=Object.getOwnPropertyDescriptor(value,field);
  if(!descriptor)continue;
  if(!Object.hasOwn(descriptor,'value'))invalidArguments();
  snapshot[field]=descriptor.value;
 }
 return snapshot;
}

// Handler construction is an authority boundary too. Snapshot only the named
// own data properties before reading credentials, callbacks or timing controls.
export function exactHandlerConfig(value,fields,defaults,errorCode){
 if(typeof errorCode!=='string'||errorCode.length<1||errorCode.length>128)invalidArguments();
 fields=exactFields(fields);defaults=exactDefaults(defaults,fields);
 const fail=()=>{throw Error(errorCode);};
 if(!value||typeof value!=='object'||utilTypes.isProxy(value))fail();
 const prototype=Object.getPrototypeOf(value);
 if(prototype!==Object.prototype&&prototype!==null)fail();
 const keys=Reflect.ownKeys(value);
 if(keys.some(key=>typeof key!=='string'||!fields.includes(key)))fail();
 const snapshot=Object.create(null);
 for(const field of fields){
  const descriptor=Object.getOwnPropertyDescriptor(value,field);
  if(!descriptor){snapshot[field]=Object.hasOwn(defaults,field)?defaults[field]:undefined;continue;}
  if(!Object.hasOwn(descriptor,'value'))fail();
  snapshot[field]=descriptor.value;
 }
 return snapshot;
}
