// Call only after the handler's wire-size and read-time limits. Decode once so
// multibyte characters split across chunks remain intact. Never repair bytes
// before authenticating signed JSON. Preserve JSON.parse's rejection of a BOM.
export function parsePodRequestJSON(bytes){
 let text;
 try{text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes);}
 catch{throw new SyntaxError('REQUEST_ENCODING_INVALID');}
 return JSON.parse(text);
}
