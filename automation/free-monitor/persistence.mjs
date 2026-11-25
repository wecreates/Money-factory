import fs from 'node:fs/promises';
import {constants as fsConstants} from 'node:fs';
import {randomUUID} from 'node:crypto';
import path from 'node:path';

// The pending journal contains both replacement images, so its input ceiling
// also bounds the combined state/events snapshot a worker may resume. It is
// intentionally aligned with the local alert source ceiling.
export const MAX_MONITOR_PERSISTENCE_BYTES=8*1024*1024;

async function resolveFile(file) {
  const absolute=path.resolve(file);
  return path.join(await fs.realpath(path.dirname(absolute)),path.basename(absolute));
}

async function destinations({statePath,eventsPath}) {
  const [state,events]=await Promise.all([resolveFile(statePath),resolveFile(eventsPath)]);
  const pending=`${state}.pending`;
  if (state===events || pending===events) throw new Error('Monitor persistence paths must be distinct');
  return {state,events,pending,eventsKey:path.relative(path.dirname(state),events)};
}

async function readJson(file,label) {
  if(!fsConstants.O_NOFOLLOW || !fsConstants.O_NONBLOCK){
    throw new Error('bounded monitor persistence reads require no-follow and nonblocking file flags');
  }
  let handle;
  try {
    handle=await fs.open(file,fsConstants.O_RDONLY|fsConstants.O_NOFOLLOW|fsConstants.O_NONBLOCK);
  } catch (error) {
    if (error.code==='ENOENT') return undefined;
    if (error.code==='ELOOP') throw new Error(`${label} must be a regular file`);
    throw error;
  }
  try {
    const opened=await handle.stat({bigint:true});
    if (!opened.isFile()) throw new Error(`${label} must be a regular file`);
    if (opened.size>BigInt(MAX_MONITOR_PERSISTENCE_BYTES)) {
      throw new Error(`${label} exceeds ${MAX_MONITOR_PERSISTENCE_BYTES} byte limit`);
    }
    // One extra byte detects growth after the descriptor was opened without
    // ever loading an unbounded file into the process.
    const bytes=Buffer.alloc(Number(opened.size)+1);
    let offset=0;
    while (offset<bytes.length) {
      const {bytesRead}=await handle.read(bytes,offset,bytes.length-offset,offset);
      if (bytesRead===0) break;
      offset+=bytesRead;
    }
    const final=await handle.stat({bigint:true});
    if (offset>MAX_MONITOR_PERSISTENCE_BYTES || final.size!==opened.size
        || final.dev!==opened.dev || final.ino!==opened.ino
        || final.mtimeNs!==opened.mtimeNs || final.ctimeNs!==opened.ctimeNs) {
      throw new Error(`${label} changed while being read`);
    }
    return JSON.parse(bytes.subarray(0,offset).toString('utf8'));
  } finally {
    await handle.close();
  }
}

const record=value=>value!==null && typeof value==='object' && !Array.isArray(value);
const serializeJson=value=>JSON.stringify(value,null,2)+'\n';

function validatePair(state,events) {
  if (!record(state) || !Object.values(state).every(record)) throw new Error('Invalid monitor state');
  if (!Array.isArray(events) || !events.every(record)) throw new Error('Invalid monitor events');
}

function pendingJournalBytes(files,state,events){
  return Buffer.byteLength(serializeJson({schema_version:1,events_path:files.eventsKey,state,events}));
}

function validatePendingJournalSize(files,state,events){
  if(pendingJournalBytes(files,state,events)>MAX_MONITOR_PERSISTENCE_BYTES){
    throw new Error(`combined monitor persistence snapshot exceeds ${MAX_MONITOR_PERSISTENCE_BYTES} byte limit`);
  }
}

async function syncDirectory(file) {
  const directory=await fs.open(path.dirname(file),'r');
  try {
    await directory.sync();
  } finally {
    await directory.close();
  }
}

async function writeSerializedAtomic(file,serialized) {
  const temporary=path.join(path.dirname(file),`.free-monitor-${randomUUID()}.tmp`);
  const handle=await fs.open(temporary,'wx',0o600);
  let moved=false;
  try {
    try {
      await handle.writeFile(serialized);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await fs.rename(temporary,file);
    moved=true;
    await syncDirectory(file);
  } finally {
    if (!moved) await fs.unlink(temporary);
  }
}

export async function writeJsonAtomic(file,value) {
  await writeSerializedAtomic(file,serializeJson(value));
}

function preparePairImages(files,state,events) {
  // Serialize the complete recovery image exactly once. Parsing that image
  // materializes getters and toJSON hooks into ordinary JSON values, so the
  // preflight and all three writes cannot observe different object views.
  const pending=serializeJson({schema_version:1,events_path:files.eventsKey,state,events});
  if(Buffer.byteLength(pending)>MAX_MONITOR_PERSISTENCE_BYTES){
    throw new Error(`combined monitor persistence snapshot exceeds ${MAX_MONITOR_PERSISTENCE_BYTES} byte limit`);
  }
  const materialized=JSON.parse(pending);
  validatePair(materialized.state,materialized.events);
  const stateImage=serializeJson(materialized.state);
  const eventsImage=serializeJson(materialized.events);
  if(Buffer.byteLength(stateImage)>MAX_MONITOR_PERSISTENCE_BYTES
      || Buffer.byteLength(eventsImage)>MAX_MONITOR_PERSISTENCE_BYTES){
    throw new Error(`combined monitor persistence snapshot exceeds ${MAX_MONITOR_PERSISTENCE_BYTES} byte limit`);
  }
  return {pending,state:stateImage,events:eventsImage,
    pair:{state:materialized.state,events:materialized.events}};
}

async function finishPair(files,images) {
  await writeSerializedAtomic(files.events,images.events);
  await writeSerializedAtomic(files.state,images.state);
  await fs.unlink(files.pending);
  await syncDirectory(files.pending);
}

export async function readMonitorPair(options) {
  const files=await destinations(options);
  const pending=await readJson(files.pending,'pending monitor persistence journal');
  if (pending!==undefined) {
    if (!record(pending) || pending.schema_version!==1 || pending.events_path!==files.eventsKey) {
      throw new Error('Invalid pending monitor persistence journal');
    }
    const images=preparePairImages(files,pending.state,pending.events);
    await finishPair(files,images);
    return images.pair;
  }
  const [storedState,storedEvents]=await Promise.all([
    readJson(files.state,'monitor state'),readJson(files.events,'monitor events')]);
  const state=storedState===undefined?{}:storedState;
  const events=storedEvents===undefined?[]:storedEvents;
  validatePair(state,events);
  validatePendingJournalSize(files,state,events);
  return {state,events};
}

// Workers sharing a pair must run serially. The hosted workflows use a common
// concurrency group. Restart replay assumes the same underlying filesystem.
export async function writeMonitorPair(options,state,events) {
  const files=await destinations(options);
  const images=preparePairImages(files,state,events);
  // Both replacement images are durable before changing either legacy file.
  await writeSerializedAtomic(files.pending,images.pending);
  await finishPair(files,images);
}
