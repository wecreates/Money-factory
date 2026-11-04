import {types as utilTypes} from 'node:util';

const MAX_SNAPSHOT_DEPTH=64;
const MAX_SNAPSHOT_OBJECTS=8192;
// Bound primitive fanout and text before copying, JSON serialization or HMAC.
// The HTTP grant body has the same 256 KiB ceiling, but that later check cannot
// protect the authoritative process from an oversized server-loaded snapshot.
const MAX_SNAPSHOT_VALUES=8192;
const MAX_SNAPSHOT_TEXT_BYTES=262144;

function copyAuthorityValue(value,state,depth){
 const fail=()=>{throw Error('AUTHORITY_SNAPSHOT_UNVERIFIED');};
 if(++state.values>MAX_SNAPSHOT_VALUES)fail();
 const addText=text=>{
  state.textBytes+=Buffer.byteLength(text,'utf8');
  if(state.textBytes>MAX_SNAPSHOT_TEXT_BYTES)fail();
 };
 if(value===null||typeof value==='boolean')return value;
 if(typeof value==='string'){addText(value);return value;}
 if(typeof value==='number'){if(!state.strict||Number.isFinite(value))return value;fail();}
 if(!state.strict&&['undefined','bigint','symbol','function'].includes(typeof value)){
  if(typeof value==='function'&&utilTypes.isProxy(value))fail();
  return value;
 }
 if(!value||typeof value!=='object'||utilTypes.isProxy(value)||depth>MAX_SNAPSHOT_DEPTH)fail();
 if(state.active.has(value))fail();
 if(state.copies.has(value))return state.copies.get(value);
 if(++state.objects>MAX_SNAPSHOT_OBJECTS)fail();
 state.active.add(value);
 let copy;
 if(Array.isArray(value)){
  if(Object.getPrototypeOf(value)!==Array.prototype)fail();
  const lengthDescriptor=Object.getOwnPropertyDescriptor(value,'length');
  if(!lengthDescriptor||!Object.hasOwn(lengthDescriptor,'value')||!Number.isSafeInteger(lengthDescriptor.value)||lengthDescriptor.value<0)fail();
  const length=lengthDescriptor.value;
  if(length>MAX_SNAPSHOT_VALUES-state.values)fail();
  const keys=Reflect.ownKeys(value);
  if(keys.length!==length+1||!keys.includes('length')||keys.some(key=>key!=='length'&&(typeof key!=='string'||!/^0$|^[1-9]\d*$/.test(key)||Number(key)>=length)))fail();
  copy=[];state.copies.set(value,copy);
  for(let index=0;index<length;index++){
   const descriptor=Object.getOwnPropertyDescriptor(value,String(index));
   if(!descriptor||!descriptor.enumerable||!Object.hasOwn(descriptor,'value'))fail();
   copy[index]=copyAuthorityValue(descriptor.value,state,depth+1);
  }
 }else{
  const prototype=Object.getPrototypeOf(value);
  if(!state.strict&&[String.prototype,Number.prototype,Boolean.prototype,BigInt.prototype,Symbol.prototype].includes(prototype)){
   if(Reflect.ownKeys(value).some(key=>{
    const descriptor=Object.getOwnPropertyDescriptor(value,key);
    return !descriptor||!Object.hasOwn(descriptor,'value');
   }))fail();
   state.active.delete(value);
   return value;
  }
  if(prototype!==Object.prototype&&prototype!==null)fail();
  const keys=Reflect.ownKeys(value);
  if(keys.length>MAX_SNAPSHOT_VALUES-state.values)fail();
  copy=Object.create(null);state.copies.set(value,copy);
  for(const key of keys){
   if(typeof key!=='string')fail();
   addText(key);
   const descriptor=Object.getOwnPropertyDescriptor(value,key);
   if(!descriptor||!descriptor.enumerable||!Object.hasOwn(descriptor,'value'))fail();
   // JSON.stringify invokes an own callable toJSON property while deriving
   // signed evidence hashes. Other function-valued invalid fields must remain
   // inert so the established field validators can reject them precisely.
   if(key==='toJSON'&&typeof descriptor.value==='function')fail();
   copy[key]=copyAuthorityValue(descriptor.value,state,depth+1);
  }
 }
 state.active.delete(value);
 return copy;
}

export function copyAuthoritySnapshot(value,strict=true){
 return copyAuthorityValue(value,{active:new WeakSet(),copies:new WeakMap(),objects:0,values:0,textBytes:0,strict},0);
}
