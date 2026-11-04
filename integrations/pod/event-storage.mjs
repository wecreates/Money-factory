import {types as utilTypes} from 'node:util';

const MAX_EVENT_DEPTH=64;
const MAX_EVENT_OBJECTS=8192;

// PostgreSQL jsonb cannot represent NUL or unpaired UTF-16 surrogates, although
// JavaScript's JSON parser accepts their escaped forms. Validate only the event
// being stored, after authenticating its envelope. Never repair signed text.
export function assertEventStorageText(event){
 const fail=()=>{throw Error('EVENT_STORAGE_TEXT_INVALID');};
 const check=text=>{
  for(let index=0;index<text.length;index++){
   const unit=text.charCodeAt(index);
   if(unit===0)fail();
   if(unit>=0xd800&&unit<=0xdbff){
    const next=text.charCodeAt(++index);
    if(!(next>=0xdc00&&next<=0xdfff))fail();
   }else if(unit>=0xdc00&&unit<=0xdfff)fail();
  }
 };
 const state={active:new WeakSet(),seen:new WeakSet(),objects:0};
 const visit=(value,depth)=>{
  if(typeof value==='string'){check(value);return;}
  if(value===null||typeof value==='boolean')return;
  if(typeof value==='number'){if(Number.isFinite(value))return;fail();}
  if(!value||typeof value!=='object'||utilTypes.isProxy(value)||depth>MAX_EVENT_DEPTH)fail();
  if(state.active.has(value))fail();
  if(state.seen.has(value))return;
  if(++state.objects>MAX_EVENT_OBJECTS)fail();
  state.active.add(value);
  if(Array.isArray(value)){
   if(Object.getPrototypeOf(value)!==Array.prototype)fail();
   const lengthDescriptor=Object.getOwnPropertyDescriptor(value,'length');
   if(!lengthDescriptor||!Object.hasOwn(lengthDescriptor,'value')||
    !Number.isSafeInteger(lengthDescriptor.value)||lengthDescriptor.value<0)fail();
   const length=lengthDescriptor.value,keys=Reflect.ownKeys(value);
   if(keys.length!==length+1||!keys.includes('length')||keys.some(key=>key!=='length'&&
    (typeof key!=='string'||!/^0$|^[1-9]\d*$/.test(key)||Number(key)>=length)))fail();
   for(let index=0;index<length;index++){
    const descriptor=Object.getOwnPropertyDescriptor(value,String(index));
    if(!descriptor||!descriptor.enumerable||!Object.hasOwn(descriptor,'value'))fail();
    visit(descriptor.value,depth+1);
   }
  }else{
   const prototype=Object.getPrototypeOf(value);
   if(prototype!==Object.prototype&&prototype!==null)fail();
   for(const key of Reflect.ownKeys(value)){
    if(typeof key!=='string')fail();
    check(key);
    const descriptor=Object.getOwnPropertyDescriptor(value,key);
    if(!descriptor||!descriptor.enumerable||!Object.hasOwn(descriptor,'value'))fail();
    visit(descriptor.value,depth+1);
   }
  }
  state.active.delete(value);state.seen.add(value);
 };
 visit(event,0);
}
