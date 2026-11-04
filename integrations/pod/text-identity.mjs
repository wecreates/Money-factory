import {types as utilTypes} from 'node:util';

// PostgreSQL text is UTF-8 and cannot store NUL. Reject identifiers whose
// JavaScript spelling would be replaced or rejected by the durable boundary.
export function validOpaqueText(value,options){
 let maxLength=256;
 if(options!==undefined){
  if(!options||typeof options!=='object'||utilTypes.isProxy(options))return false;
  const prototype=Object.getPrototypeOf(options);
  if(prototype!==Object.prototype&&prototype!==null)return false;
  const descriptor=Object.getOwnPropertyDescriptor(options,'maxLength');
  if(descriptor){
   if(!Object.hasOwn(descriptor,'value'))return false;
   if(descriptor.value!==undefined)maxLength=descriptor.value;
  }
 }
 if(!Number.isSafeInteger(maxLength)||maxLength<0)return false;
 if(typeof value!=='string'||value.length>maxLength||value.trim().length===0||value.includes('\0'))return false;
 return Buffer.from(value,'utf8').toString('utf8')===value;
}
