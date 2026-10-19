// Call only after the handler's wire-size and read-time limits. Decode once so
// multibyte characters split across chunks remain intact. Never repair bytes
// before authenticating signed JSON. Preserve JSON.parse's rejection of a BOM.
export function parsePodRequestJSON(bytes){
 let text;
 try{text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes);}
 catch{throw new SyntaxError('REQUEST_ENCODING_INVALID');}
 return parsePodJSON(text);
}

// Native parsing owns JSON grammar. The iterative token walk additionally rejects
// duplicate decoded member names and numbers that native parsing turns into
// Infinity (JSON.stringify would silently store those as null). Do not normalize
// signed bytes: event authentication must happen before calling this function.
export function parsePodJSON(text){
 const value=JSON.parse(text),stack=[];
 for(let i=0;i<text.length;){
  const ch=text[i];
  if(ch==='"'){
   const start=i++;
   while(text[i]!=='"'){if(text[i]==='\\')i++;i++;}
   i++;
   const object=stack.at(-1);
   if(object?.expectKey){
    const key=JSON.parse(text.slice(start,i));
    if(object.keys.has(key))throw new SyntaxError('REQUEST_JSON_DUPLICATE_KEY');
    object.keys.add(key);object.expectKey=false;
   }
  }else if(ch==='{'){stack.push({keys:new Set(),expectKey:true});i++;}
  else if(ch==='['){stack.push(null);i++;}
  else if(ch==='}'||ch===']'){stack.pop();i++;}
  else if(ch===','){const object=stack.at(-1);if(object)object.expectKey=true;i++;}
  else if(ch===':'||/\s/.test(ch)){i++;}
  else{
   const start=i++;
   while(i<text.length&&!/[\s,}\]]/.test(text[i]))i++;
   if((ch==='-'||(ch>='0'&&ch<='9'))&&!Number.isFinite(Number(text.slice(start,i))))
    throw new SyntaxError('REQUEST_JSON_NONFINITE');
  }
 }
 return value;
}
