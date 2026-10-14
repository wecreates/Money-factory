import test from 'node:test';
import assert from 'node:assert/strict';
import {hasPageEvidence} from './browser_probe.mjs';
const origin = 'http://127.0.0.1:12345';
const valid = () => ({operation:'inspect_web_page', normalized_result:{
  target:{origin},dom:{total_nodes:4,nodes:[{name:'MAIN'}]},
  accessibility:{text_capture:{status:'included',retained_bytes:42}}
}});
test('requires actual DOM and captured accessibility text from requested origin',()=>{
  assert.equal(hasPageEvidence(valid(),origin),true);
  for (const change of [
    x=>{x.normalized_result.dom.nodes=[];},
    x=>{x.normalized_result.accessibility.text_capture.retained_bytes=0;},
    x=>{x.normalized_result.target.origin='https://example.com';},
    x=>{x.operation='list_browser_targets';},
    x=>{x.error='upstream failure';}
  ]) {const evidence=valid();change(evidence);assert.equal(hasPageEvidence(evidence,origin),false);}
  assert.equal(Boolean(hasPageEvidence({},origin)),false);
});
