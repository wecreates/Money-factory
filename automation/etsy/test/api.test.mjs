import test from 'node:test';
import assert from 'node:assert/strict';
import {shopUrl,sectionsUrl,listingUrl,publicListingUrl,apiKey} from '../api.mjs';

test('builds shop url',()=>assert.equal(shopUrl(43299966),'https://api.etsy.com/v3/application/shops/43299966'));
test('builds section url',()=>assert.equal(sectionsUrl(43299966),'https://api.etsy.com/v3/application/shops/43299966/sections'));
test('builds listing update url',()=>assert.equal(listingUrl(43299966,123),'https://api.etsy.com/v3/application/shops/43299966/listings/123'));
test('builds public listing url',()=>assert.equal(publicListingUrl(123),'https://api.etsy.com/v3/application/listings/123'));
test('api key requires both halves',()=>assert.throws(()=>apiKey({}),/Missing ETSY_API_KEY/));
test('api key joins key and secret',()=>assert.equal(apiKey({ETSY_API_KEY:'k',ETSY_SHARED_SECRET:'s'}),'k:s'));
