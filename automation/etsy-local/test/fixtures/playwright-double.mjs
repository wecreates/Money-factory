// Pure browser transport double. No Playwright, account, profile or network access.
import {appendFileSync} from 'node:fs';
const scenario=process.env.ETSY_TEST_SCENARIO;
let currentUrl='',saved=false;
const record=event=>appendFileSync(process.env.ETSY_TEST_TRACE,event+'\n');
function locator(kind,index=0){
  const missing=kind==='save'&&scenario==='missing-save'||kind==='digital'&&scenario==='missing-digital-input';
  return {
    first(){return this;},nth(i){return locator(kind,i);},
    async count(){return missing?0:kind==='inputs'?(scenario==='missing-digital-input'?1:2):1;},
    async getAttribute(name){return name==='type'?'file':name==='accept'?(index===0?'image/*':'.pdf,.zip'):null;},
    async isVisible(){return !missing;},async isEnabled(){return !missing;},
    async click(){if(missing)throw new Error('missing save');if(kind==='save'){record('save');saved=true;}},
    async setInputFiles(){if(missing)throw new Error('missing digital input');record('upload');},
    async waitFor({state}){
      if(state==='hidden'&&scenario==='stale-confirmation')throw new Error('old confirmation still visible');
      if(state==='visible'&&(!saved||scenario==='missing-confirmation'))throw new Error('no new save confirmation');
    },
    async fill(){},async press(){},
  };
}
const page={
  async goto(url){currentUrl=url;},url(){return currentUrl;},
  getByLabel(label){return locator(label instanceof RegExp?'digital':'field');},
  getByRole(){return locator('save');},
  getByText(text){return locator(text instanceof RegExp?'confirmation':/save|publish/i.test(text)?'save':'field');},
  locator(selector){return locator(selector.includes('accept')?'digital':'inputs');},
  async waitForTimeout(){},
};
export const chromium={async launchPersistentContext(){
  record('launch');
  return {pages(){return [page];},async close(){}};
}};
