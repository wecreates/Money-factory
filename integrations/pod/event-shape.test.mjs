import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {acceptPodEvent} from './event-inbox.mjs';

const key='test-only-event-shape-key-'.repeat(2),now=1800000000000;
const id='12b4c678-1234-4321-abcd-123456789abc';
const event={id,job_id:null,kind:'pod.test.shape',payload:{publication_enabled:false},created_at:new Date(now).toISOString()};
const signed=payload=>{const text=JSON.stringify(payload);return {
 payload:text,signature:crypto.createHmac('sha256',key).update(text).digest('hex')};};
const envelope=eventValue=>({schema_version:1,audience:'money-factory:pod:event',issued_at_ms:now,event:eventValue});

test('signed envelopes and events must match the bounded Content Control outbox shape',async()=>{
 let connects=0;const pool={connect:async()=>{connects++;throw Error('UNEXPECTED_DATABASE_ACCESS');}};
 const invalid=[
  {...envelope(event),private_token:'must-not-cross-boundary'},
  envelope({...event,private_token:'must-not-cross-boundary'}),
  envelope({...event,payload:[]}),
  envelope({...event,job_id:'not-a-uuid'}),
  envelope({...event,kind:'pod.'}),
  envelope({...event,created_at:'not-a-timestamp'}),
  envelope(Object.fromEntries(Object.entries(event).filter(([name])=>name!=='created_at'))),
 ];
 for(const value of invalid){
  await assert.rejects(acceptPodEvent(pool,signed(value),key,()=>now),/EVENT_SCOPE_INVALID/);
  assert.equal(connects,0);
 }
});
