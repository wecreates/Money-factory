import {inflateRawSync} from 'node:zlib';
import {createHash} from 'node:crypto';

export function crc32(bytes){
  let crc=0xffffffff;
  for(const byte of bytes){crc^=byte; for(let bit=0;bit<8;bit++) crc=(crc>>>1)^((crc&1)?0xedb88320:0);}
  return (crc^0xffffffff)>>>0;
}
export function safeRelativePath(value){
  if(typeof value!=='string' || !value || value.includes('\ufffd')) return false;
  // Apply the Windows rules on every host, including directories and extensions.
  // Unicode escapes keep the three reserved superscript digits unambiguous.
  return value.split('/').every(segment=>segment && segment!=='.' && segment!=='..' &&
    !/[<>:"\\|?*\u0000-\u001f]/.test(segment) && !/[ .]$/.test(segment) &&
    !/^(?:CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])$/i.test(segment.split('.')[0].replace(/ +$/,'')));
}

// Register files and implicit/explicit directories as one case-insensitive tree.
// An explicit directory may follow its children; a file cannot become a parent.
function registerPath(paths,name,isDirectory=false){
  const segments=name.split('/');
  for(let i=0;i<segments.length;i++){
    const leaf=i===segments.length-1,spelling=segments[i];
    // Fold upper and lower variants conservatively (for example sigma/final
    // sigma and long s), rather than assuming ASCII-only entry names.
    const key=spelling.toLowerCase().toUpperCase(),directory=!leaf||isDirectory;
    let entry=paths.get(key);
    if(entry){
      if(entry.spelling!==spelling || entry.directory!==directory || (leaf&&entry.explicit)) return false;
      if(leaf) entry.explicit=true;
    }else{
      entry={spelling,directory,explicit:leaf,children:new Map()};
      paths.set(key,entry);
    }
    paths=entry.children;
  }
  return true;
}

// Read only bounded, ordinary single-disk ZIPs. Never extract to disk.
// Reject encrypted/ZIP64/unsupported archives rather than guess their contents.
export function verifyZipEntries(input,expected){
  const bytes=Buffer.from(input);
  const reject=()=>{throw new Error('Unsupported, unsafe or inconsistent ZIP deliverable');};
  if(!Array.isArray(expected) || !expected.length || expected.length>256) reject();
  const wanted=new Map(),reviewedPaths=new Map();
  for(const entry of expected){
    if(!safeRelativePath(entry?.path) || !/^[a-f0-9]{64}$/.test(entry?.sha256||'') || !registerPath(reviewedPaths,entry.path)) reject();
    wanted.set(entry.path,entry.sha256);
  }
  let end=-1;
  for(let i=bytes.length-22;i>=Math.max(0,bytes.length-65557);i--){
    if(bytes.readUInt32LE(i)===0x06054b50 && i+22+bytes.readUInt16LE(i+20)===bytes.length){end=i;break;}
  }
  if(end<0 || bytes.readUInt16LE(end+4)!==0 || bytes.readUInt16LE(end+6)!==0) reject();
  const count=bytes.readUInt16LE(end+10),size=bytes.readUInt32LE(end+12),start=bytes.readUInt32LE(end+16);
  if(count===0 || count>512 || bytes.readUInt16LE(end+8)!==count || start+size!==end) reject();
  const archivePaths=new Map(),ranges=[]; let cursor=start,total=0;
  for(let i=0;i<count;i++){
    if(cursor+46>end || bytes.readUInt32LE(cursor)!==0x02014b50) reject();
    const flags=bytes.readUInt16LE(cursor+8),method=bytes.readUInt16LE(cursor+10);
    const crc=bytes.readUInt32LE(cursor+16),compressed=bytes.readUInt32LE(cursor+20),uncompressed=bytes.readUInt32LE(cursor+24);
    const nameSize=bytes.readUInt16LE(cursor+28),extra=bytes.readUInt16LE(cursor+30),comment=bytes.readUInt16LE(cursor+32),local=bytes.readUInt32LE(cursor+42);
    const next=cursor+46+nameSize+extra+comment;
    if(next>end || flags&~0x800 || ![0,8].includes(method) || bytes.readUInt16LE(cursor+34)!==0 || local+30>start) reject();
    const nameBytes=bytes.subarray(cursor+46,cursor+46+nameSize),name=nameBytes.toString('utf8');
    const isDirectory=name.endsWith('/');
    const relative=isDirectory?name.slice(0,-1):name;
    if(!safeRelativePath(relative) || !registerPath(archivePaths,relative,isDirectory)) reject();
    if(bytes.readUInt32LE(local)!==0x04034b50 || bytes.readUInt16LE(local+6)!==flags || bytes.readUInt16LE(local+8)!==method) reject();
    const localNameSize=bytes.readUInt16LE(local+26),localExtra=bytes.readUInt16LE(local+28),data=local+30+localNameSize+localExtra;
    if(bytes.readUInt32LE(local+14)!==crc || bytes.readUInt32LE(local+18)!==compressed || bytes.readUInt32LE(local+22)!==uncompressed) reject();
    if(data+compressed>start || !bytes.subarray(local+30,local+30+localNameSize).equals(nameBytes)) reject();
    if(ranges.some(([a,b])=>local<b && data+compressed>a)) reject();
    ranges.push([local,data+compressed]);
    total+=uncompressed;
    if(total>100_000_000 || (isDirectory&&uncompressed!==0)) reject();
    if(!isDirectory&&!wanted.has(name)) reject();
    const raw=bytes.subarray(data,data+compressed);
    const decoded=method===0?raw:inflateRawSync(raw,{maxOutputLength:Math.max(1,uncompressed)});
    if(decoded.length!==uncompressed || crc32(decoded)!==crc) reject();
    if(!isDirectory && createHash('sha256').update(decoded).digest('hex')!==wanted.get(name)) throw new Error(`ZIP entry hash mismatch: ${name}`);
    if(!isDirectory) wanted.delete(name);
    cursor=next;
  }
  if(cursor!==end || wanted.size) throw new Error('ZIP is missing a reviewed deliverable entry');
}
