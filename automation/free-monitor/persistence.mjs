import fs from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import path from 'node:path';

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

async function readJson(file) {
  let bytes;
  try {
    bytes=await fs.readFile(file,'utf8');
  } catch (error) {
    if (error.code==='ENOENT') return undefined;
    throw error;
  }
  return JSON.parse(bytes);
}

const record=value=>value!==null && typeof value==='object' && !Array.isArray(value);

function validatePair(state,events) {
  if (!record(state) || !Object.values(state).every(record)) throw new Error('Invalid monitor state');
  if (!Array.isArray(events) || !events.every(record)) throw new Error('Invalid monitor events');
}

async function syncDirectory(file) {
  const directory=await fs.open(path.dirname(file),'r');
  try {
    await directory.sync();
  } finally {
    await directory.close();
  }
}

export async function writeJsonAtomic(file,value) {
  const temporary=path.join(path.dirname(file),`.free-monitor-${randomUUID()}.tmp`);
  const handle=await fs.open(temporary,'wx',0o600);
  let moved=false;
  try {
    try {
      await handle.writeFile(JSON.stringify(value,null,2)+'\n');
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

async function finishPair(files,state,events) {
  await writeJsonAtomic(files.events,events);
  await writeJsonAtomic(files.state,state);
  await fs.unlink(files.pending);
  await syncDirectory(files.pending);
}

export async function readMonitorPair(options) {
  const files=await destinations(options);
  const pending=await readJson(files.pending);
  if (pending!==undefined) {
    if (!record(pending) || pending.schema_version!==1 || pending.events_path!==files.eventsKey) {
      throw new Error('Invalid pending monitor persistence journal');
    }
    validatePair(pending.state,pending.events);
    await finishPair(files,pending.state,pending.events);
    return {state:pending.state,events:pending.events};
  }
  const [storedState,storedEvents]=await Promise.all([readJson(files.state),readJson(files.events)]);
  const state=storedState===undefined?{}:storedState;
  const events=storedEvents===undefined?[]:storedEvents;
  validatePair(state,events);
  return {state,events};
}

// Workers sharing a pair must run serially. The hosted workflows use a common
// concurrency group. Restart replay assumes the same underlying filesystem.
export async function writeMonitorPair(options,state,events) {
  const files=await destinations(options);
  validatePair(state,events);
  // Both replacement images are durable before changing either legacy file.
  await writeJsonAtomic(files.pending,{schema_version:1,events_path:files.eventsKey,state,events});
  await finishPair(files,state,events);
}
