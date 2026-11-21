import test from 'node:test';
import assert from 'node:assert/strict';
import {assertCompleteText} from './contract.mjs';
test('all words and token-boundary evidence must survive segmentation', () => {
  assert.doesNotThrow(() => assertCompleteText('Same words. Last sentence.', [{text:'Same words.',phoneme_tokens:20},{text:'Last sentence.',phoneme_tokens:511}]));
  assert.throws(() => assertCompleteText('Same words. Last sentence.', [{text:'Same words.',phoneme_tokens:20}]));
  assert.throws(() => assertCompleteText('Same words.', [{text:'Same words.',phoneme_tokens:512}]));
  assert.throws(() => assertCompleteText('Same words.', [{text:'Changed words.',phoneme_tokens:20}]));
});
