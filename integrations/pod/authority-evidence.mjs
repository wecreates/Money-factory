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
  if(typeof value==='function'){
   if(utilTypes.isProxy(value))fail();
   // JSON.stringify resolves toJSON on callable objects before omitting them.
   // Inspect that resolution path without a property read so an invalid
   // function-valued field stays inert until its domain validator rejects it.
   let cursor=value,prototypeDepth=0;
   while(cursor!==null){
    if(utilTypes.isProxy(cursor)||prototypeDepth++>MAX_SNAPSHOT_DEPTH)fail();
    const descriptor=Object.getOwnPropertyDescriptor(cursor,'toJSON');
    if(descriptor){
     if(!Object.hasOwn(descriptor,'value')||typeof descriptor.value==='function')fail();
     break;
    }
    cursor=Object.getPrototypeOf(cursor);
   }
  }
  return value;
 }
 if(!value||typeof value!=='object'||utilTypes.isProxy(value)||depth>MAX_SNAPSHOT_DEPTH)fail();
 if(state.active.has(value))fail();
 // JSON serialization expands every alias occurrence. Re-copy shared values so
 // the object, value and text budgets measure that same expanded evidence tree.
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
  copy=[];
  for(let index=0;index<length;index++){
   const descriptor=Object.getOwnPropertyDescriptor(value,String(index));
   if(!descriptor||!descriptor.enumerable||!Object.hasOwn(descriptor,'value'))fail();
   copy[index]=copyAuthorityValue(descriptor.value,state,depth+1);
  }
 }else{
  const prototype=Object.getPrototypeOf(value);
  if(!state.strict&&[String.prototype,Number.prototype,Boolean.prototype,BigInt.prototype,Symbol.prototype].includes(prototype)){
   let primitive;
   try{
    if(prototype===String.prototype)primitive=String.prototype.valueOf.call(value);
    else if(prototype===Number.prototype)primitive=Number.prototype.valueOf.call(value);
    else if(prototype===Boolean.prototype)primitive=Boolean.prototype.valueOf.call(value);
    else if(prototype===BigInt.prototype)primitive=BigInt.prototype.valueOf.call(value);
    else primitive=Symbol.prototype.valueOf.call(value);
   }catch{fail();}
   if(typeof primitive==='string'){
    addText(primitive);
    // A boxed string exposes one own property per UTF-16 code unit. Bound that
    // reflection work before enumerating the wrapper's canonical descriptors.
    if(primitive.length>MAX_SNAPSHOT_VALUES-state.values)fail();
   }
   const clean=Object(primitive),keys=Reflect.ownKeys(value),cleanKeys=Reflect.ownKeys(clean);
   if(keys.length!==cleanKeys.length||cleanKeys.some((key,index)=>keys[index]!==key))fail();
   for(const key of cleanKeys){
    const descriptor=Object.getOwnPropertyDescriptor(value,key),cleanDescriptor=Object.getOwnPropertyDescriptor(clean,key);
    if(!descriptor||!Object.hasOwn(descriptor,'value')||descriptor.value!==cleanDescriptor.value||
     descriptor.enumerable!==cleanDescriptor.enumerable||descriptor.configurable!==cleanDescriptor.configurable||
     descriptor.writable!==cleanDescriptor.writable)fail();
   }
   state.active.delete(value);
   return clean;
  }
  if(prototype!==Object.prototype&&prototype!==null)fail();
  const keys=Reflect.ownKeys(value);
  if(keys.length>MAX_SNAPSHOT_VALUES-state.values)fail();
  copy=Object.create(null);
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
 return copyAuthorityValue(value,{active:new WeakSet(),objects:0,values:0,textBytes:0,strict},0);
}
