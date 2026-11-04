import test from 'node:test';
import assert from 'node:assert/strict';
import {assertEventStorageText} from './event-storage.mjs';

const invalidWithoutReads=(name,make)=>test(name,()=>{
 const reads={count:0};
 assert.throws(()=>assertEventStorageText(make(reads)),/EVENT_STORAGE_TEXT_INVALID/);
 assert.equal(reads.count,0);
});

invalidWithoutReads('event storage validation rejects a root proxy without running traps',reads=>new Proxy({note:'safe'},{
 ownKeys(target){reads.count++;return Reflect.ownKeys(target);}
}));

invalidWithoutReads('event storage validation rejects a nested proxy without running traps',reads=>({payload:new Proxy({note:'safe'},{
 ownKeys(target){reads.count++;return Reflect.ownKeys(target);}
})}));

invalidWithoutReads('event storage validation rejects object accessors without reading them',reads=>Object.defineProperty({},'note',{
 enumerable:true,get(){reads.count++;return 'safe';}
}));

invalidWithoutReads('event storage validation rejects array accessors without reading them',reads=>{
 const value=[];
 Object.defineProperty(value,'0',{enumerable:true,get(){reads.count++;return 'safe';}});
 value.length=1;
 return value;
});

invalidWithoutReads('event storage validation rejects custom array iterators without reading them',reads=>{
 const value=['safe'];
 Object.defineProperty(value,Symbol.iterator,{get(){reads.count++;return Array.prototype[Symbol.iterator];}});
 return value;
});

test('event storage validation rejects ambiguous container shapes',()=>{
 const inherited=Object.create({inherited:'safe'});
 inherited.note='safe';
 const sparse=[];sparse.length=2;sparse[1]='safe';
 const symbolic={note:'safe'};symbolic[Symbol('evidence')]='ignored';
 for(const value of [inherited,sparse,symbolic])
  assert.throws(()=>assertEventStorageText(value),/EVENT_STORAGE_TEXT_INVALID/);
});

test('event storage validation is cycle- and depth-bounded without rejecting shared evidence',()=>{
 const cyclic={};cyclic.self=cyclic;
 let deep={note:'safe'};for(let index=0;index<65;index++)deep=[deep];
 for(const value of [cyclic,deep,{amount:Infinity}])
  assert.throws(()=>assertEventStorageText(value),/EVENT_STORAGE_TEXT_INVALID/);
 const shared={note:'safe'};
 assert.doesNotThrow(()=>assertEventStorageText({first:shared,second:shared}));
});
