// PostgreSQL text is UTF-8 and cannot store NUL. Reject identifiers whose
// JavaScript spelling would be replaced or rejected by the durable boundary.
export function validOpaqueText(value,{maxLength=256}={}){
 if(typeof value!=='string'||value.length>maxLength||value.trim().length===0||value.includes('\0'))return false;
 return Buffer.from(value,'utf8').toString('utf8')===value;
}
