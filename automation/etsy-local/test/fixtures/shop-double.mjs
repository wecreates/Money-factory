import {appendFileSync} from 'node:fs';
export function createPage(scenario='success',record=()=>{}){
  let url='https://www.etsy.com/your/shops/me/appearance',saved=false,reloaded=false,opened=false,adding=false;
  let fields={},sections=['Existing'];
  const target=scenario.replace(/^(missing|ambiguous|disabled|hidden|click-fails)-/,'');
  function loc(kind,name='',index=0){return {
    filter(){return this;},nth(i){return loc(kind,name,i);},
    getByLabel(name){return loc('field',name);},
    getByRole(role,opts={}){return resolve(role,opts);},
    async count(){
      if(scenario.startsWith('missing-')&&target===(name||kind))return 0;
      if(scenario.startsWith('ambiguous-')&&target===(name||kind))return 2;
      if(kind==='dialog')return opened?1:0;
      if(kind==='listitem')return sections.length;
      if(kind==='busy')return scenario==='busy'?1:0;
      if(kind==='alert')return scenario==='alert'||reloaded&&scenario==='post-save-alert'?1:0;
      return 1;
    },
    async isVisible(){return !(scenario.startsWith('hidden-')&&target===(name||kind));},
    async isEnabled(){return !(scenario.startsWith('disabled-')&&target===(name||kind));},
    async innerText(){return kind==='listitem'?sections[index]:'Rejected';},
    async fill(value){record('fill');if(scenario==='fill-fails')throw Error('fill failed');fields[name]=scenario==='ignored-fill'?'wrong':value;},
    async inputValue(){return fields[name]??'';},
    async click(){
      if(scenario.startsWith('click-fails-')&&target===name)throw Error('click failed');
      if(name==='Manage sections'){record('manage');opened=true;}
      if(name==='add'){record('add');adding=true;}
      if(name==='save'){record('save');saved=true;}
    },
    async waitFor({state}){
      if(state==='hidden'&&scenario==='stale-confirmation')throw Error('stale');
      if(state==='visible'&&(!saved||scenario==='missing-confirmation'))throw Error('no confirmation');
    },
  };}
  function resolve(role,opts){
    if(role==='button')return loc('button',typeof opts.name==='string'?opts.name:opts.name.source.includes('Add')?'add':'save');
    return loc(role);
  }
  if(scenario==='already-exists')sections.push('New');
  if(scenario==='duplicate-inventory')sections.push('Existing');
  return {
    async goto(value){url=value;},url(){return url;},
    getByLabel(name){return loc('field',name);},getByRole:resolve,
    locator(){return loc('busy');},
    async reload(){record('reload');reloaded=true;opened=false;
      if(scenario==='login-redirect')url='https://www.etsy.com/signin';
      if(scenario==='lost-field')fields['Shop title']='old';
      if(scenario==='lost-announcement')fields.Announcement='old';
      if(adding&&scenario!=='lost-section')sections.push(fields['Section name']);
      if(scenario==='lost-prior-section')sections=sections.filter(x=>x!=='Existing');
      if(scenario==='extra-section')sections.push('Unexpected');
    },
  };
}
export const chromium={async launchPersistentContext(){
  const record=e=>appendFileSync(process.env.ETSY_TEST_TRACE,e+'\n');record('launch');
  return {pages(){return [createPage(process.env.ETSY_TEST_SCENARIO,record)];},async close(){record('close');}};
}};
