// PostgreSQL jsonb cannot represent NUL or unpaired UTF-16 surrogates, although
// JavaScript's JSON parser accepts their escaped forms. Validate only the event
// being stored, after authenticating its envelope. Never repair signed text.
export function assertEventStorageText(event){
 const check=text=>{
  for(const character of text){
   const point=character.codePointAt(0);
   if(point===0||(point>=0xd800&&point<=0xdfff))throw Error('EVENT_STORAGE_TEXT_INVALID');
  }
 };
 const pending=[event];
 while(pending.length){
  const value=pending.pop();
  if(typeof value==='string')check(value);
  else if(Array.isArray(value)){for(const item of value)pending.push(item);}
  else if(value&&typeof value==='object'){
   for(const [name,item] of Object.entries(value)){check(name);pending.push(item);}
  }
 }
}
