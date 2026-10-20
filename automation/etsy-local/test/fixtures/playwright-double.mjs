// Pure browser transport double: no Playwright, profile, account or network.
import {appendFileSync} from 'node:fs';
import path from 'node:path';
export function createPage(scenario='success',record=()=>{}){
  let currentUrl='https://www.etsy.com/your/shops/me/listing-editor/edit/123';
  let saved=false,reloaded=false,digital=false,fields={},tags=['old'],pendingTag='';
  let attachments=[],ticks=0;
  function locator(kind,index=0,name=''){
    const missing=(kind==='save'&&scenario==='missing-save')||(kind==='digital'&&scenario==='missing-digital-input')||(kind==='field'&&scenario==='missing-field')||(kind==='radio'&&scenario==='missing-type')||(kind==='group'&&scenario==='missing-tags');
    const matching=()=>attachments.filter(a=>!name||a.name===name);
    return {
      first(){return this;},nth(i){return locator(kind,i,name);},
      getByRole(role,opts){return locator(kind==='attachmentGroup'?'attachment':role==='textbox'?'tagInput':'tagButton',0,opts?.name);},
      async count(){
        if(missing)return 0;
        if(kind==='attachment')return matching().length;
        if(kind==='tagButton')return tags.length;
        if(kind==='progress')return scenario==='stalled-upload'||scenario==='delayed-upload'&&ticks<2?1:0;
        if(kind==='attachmentGroup'&&scenario==='missing-attachment-group')return 0;
        if(kind==='field'&&scenario==='ambiguous-field')return 2;
        return 1;
      },
      async allTextContents(){return scenario==='rejected-upload'||reloaded&&scenario==='post-save-error'?['Upload failed: unsupported file']:[];},
      async getAttribute(attribute){
        if(kind==='attachment')return attribute==='download'?(scenario==='not-download-link'?null:name):matching()[index]?.identity;
        if(kind==='tagButton')return 'Remove tag '+tags[index];
        return attribute==='type'?'file':attribute==='accept'?'.pdf,.zip':null;
      },
      async isVisible(){return !missing;},async isEnabled(){return !missing;},
      async isChecked(){return digital;},async check(){if(scenario==='type-check-fails')throw new Error('check failed');digital=scenario!=='type-not-selected';},
      async click(){
        if(kind==='save'){record('save');saved=true;}
        if(kind==='tagButton'){if(scenario==='tag-remove-fails')throw new Error('remove failed');tags.splice(index,1);}
      },
      async fill(value){
        if(scenario==='fill-fails')throw new Error('fill failed');
        if(kind==='tagInput')pendingTag=value;
        else fields[name]=scenario==='field-not-filled'?'unchanged':value;
      },
      async inputValue(){return fields[name]??'';},
      async press(){if(scenario==='tag-add-fails')throw new Error('tag add failed');if(scenario!=='tag-not-added')tags.push(pendingTag);},
      async setInputFiles(files){
        if(missing)throw new Error('missing digital input');record('upload');
        if(scenario==='missing-attachment')return;if(scenario==='drops-old-attachment')attachments=[];
        attachments=attachments.filter(a=>!files.some(f=>path.basename(f)===a.name)).concat(files.map(f=>({name:path.basename(f),identity:scenario==='blob-preview'?'blob:preview':'https://www.etsy.com/file/new/'+path.basename(f)})));
        if(scenario==='partial-upload')attachments.pop();
        if(scenario==='duplicate-attachment')attachments.push({...attachments[0]});
      },
      async waitFor({state}){
        if(state==='hidden'&&scenario==='stale-confirmation')throw new Error('old confirmation still visible');
        if(state==='visible'&&(!saved||scenario==='missing-confirmation'))throw new Error('no new save confirmation');
      },
    };
  }
  if(['drops-old-attachment','preserves-old-attachment','loses-old-on-reload'].includes(scenario))attachments=[{name:'existing.pdf',identity:'https://www.etsy.com/file/old/existing.pdf'}];
  if(scenario==='unchanged-attachment')attachments=[{name:'product.pdf',identity:'https://www.etsy.com/file/new/product.pdf'}];
  return {
    async goto(url){currentUrl=url;},url(){return currentUrl;},
    async reload(){record('reload');reloaded=true;if(scenario==='lost-attachment')attachments=[];if(scenario==='loses-old-on-reload')attachments=attachments.filter(a=>a.name!=='existing.pdf');if(scenario==='reverted-attachment')attachments=attachments.map(a=>({...a,identity:'https://www.etsy.com/file/old/'+a.name}));if(scenario==='lost-field')fields.Title='old';if(scenario==='lost-type')digital=false;if(scenario==='lost-tags')tags=[];if(scenario==='login-redirect')currentUrl='https://www.etsy.com/signin';},
    getByLabel(label){return locator(label instanceof RegExp?'digital':'field',0,label);},
    getByRole(role,options){return locator(({button:'save',link:'attachment',img:'attachment',alert:'alert',radio:'radio',group:options?.name==='Tags'?'group':'attachmentGroup'})[role],0,options?.name);},
    getByText(){return locator('confirmation');},
    locator(selector){return locator(selector.includes('progressbar')?'progress':'digital');},
    async waitForTimeout(ms){ticks++;await new Promise(r=>setTimeout(r,Math.min(ms,1)));},
  };
}
export const chromium={async launchPersistentContext(){
  const record=event=>appendFileSync(process.env.ETSY_TEST_TRACE,event+'\n');
  record('launch');return {pages(){return [createPage(process.env.ETSY_TEST_SCENARIO,record)];},async close(){}};
}};
