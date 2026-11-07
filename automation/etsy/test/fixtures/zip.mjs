import {deflateRawSync} from 'node:zlib';
import {crc32} from '../../zip-entries.mjs';

export function syntheticZip(entries,{deflate=false}={}){
  const local=[],central=[]; let offset=0;
  for(const [name,value] of Object.entries(entries)){
    const bytes=Buffer.from(value),filename=Buffer.from(name),body=deflate?deflateRawSync(bytes):bytes;
    const head=Buffer.alloc(30); head.writeUInt32LE(0x04034b50); head.writeUInt16LE(20,4); head.writeUInt16LE(deflate?8:0,8);
    head.writeUInt32LE(crc32(bytes),14); head.writeUInt32LE(body.length,18); head.writeUInt32LE(bytes.length,22); head.writeUInt16LE(filename.length,26);
    const record=Buffer.concat([head,filename,body]); local.push(record);
    const cd=Buffer.alloc(46); cd.writeUInt32LE(0x02014b50); cd.writeUInt16LE(20,4); cd.writeUInt16LE(20,6); cd.writeUInt16LE(deflate?8:0,10);
    cd.writeUInt32LE(crc32(bytes),16); cd.writeUInt32LE(body.length,20); cd.writeUInt32LE(bytes.length,24); cd.writeUInt16LE(filename.length,28); cd.writeUInt32LE(offset,42);
    central.push(Buffer.concat([cd,filename])); offset+=record.length;
  }
  const directory=Buffer.concat(central),end=Buffer.alloc(22); end.writeUInt32LE(0x06054b50); end.writeUInt16LE(local.length,8); end.writeUInt16LE(local.length,10); end.writeUInt32LE(directory.length,12); end.writeUInt32LE(offset,16);
  return Buffer.concat([...local,directory,end]);
}
