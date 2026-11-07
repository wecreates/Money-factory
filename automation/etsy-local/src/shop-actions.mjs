// Conservative, unverified semantic contract. Never guess at unknown Etsy UI.
const actionTimeout=10000;
export function validateShopPatch(p){
  if(!p||typeof p!=='object'||Array.isArray(p)||!Object.keys(p).length)throw new Error('shop patch must contain requested fields');
  for(const [key,value] of Object.entries(p)){
    if(!['title','announcement'].includes(key))throw new Error(`unsupported shop field: ${key}`);
    if(typeof value!=='string'||(key==='title'&&!value.trim()))throw new Error(`${key} must be text; title must be nonempty`);
  }
}
export function validateSectionTitle(title){
  if(typeof title!=='string'||!title.trim())throw new Error('section title must be nonempty text');
}
async function unique(control,name){
  if(await control.count()!==1||!await control.isVisible())throw new Error(`${name} control missing or ambiguous`);
  return control;
}
async function button(scope,name){
  const control=await unique(scope.getByRole('button',{name,exact:true}),'action');
  if(!await control.isEnabled())throw new Error('action control disabled');
  return control;
}
async function click(scope,name){await (await button(scope,name)).click({timeout:actionTimeout});}
async function clean(page){
  const alerts=page.getByRole('alert');
  for(let i=0;i<await alerts.count();i++)if(await alerts.nth(i).isVisible()&&(await alerts.nth(i).innerText()).trim())throw new Error('shop reported an alert; save not confirmed');
  const busy=page.locator('[role="progressbar"], [aria-busy="true"]');
  for(let i=0;i<await busy.count();i++)if(await busy.nth(i).isVisible())throw new Error('shop is still busy; save not confirmed');
}
async function saveAndReadback(page,scope,name,verify){
  await clean(page);
  const confirmation=page.getByRole('status').filter({hasText:/^(?:(?:Your )?changes (?:have been )?saved|Shop (?:has been )?saved|Section (?:has been )?created)[.!]?$/i});
  await confirmation.waitFor({state:'hidden',timeout:2000});
  const save=await button(scope,name),url=page.url();
  try{
    await save.click({timeout:actionTimeout});
    await confirmation.waitFor({state:'visible',timeout:actionTimeout});
    await unique(confirmation,'save confirmation');
    await clean(page);
    await page.reload({waitUntil:'domcontentloaded',timeout:actionTimeout});
    if(page.url()!==url)throw new Error('shop navigation changed during readback');
    await clean(page);
    await verify();
  }catch(error){
    throw new Error('save attempted but not confirmed by persisted readback; reconcile shop before retrying',{cause:error});
  }
}
async function shopField(page,key){return unique(page.getByLabel(key==='title'?'Shop title':'Announcement',{exact:true}),key);}
async function verifyShop(page,p){
  for(const [key,value] of Object.entries(p))if(await (await shopField(page,key)).inputValue({timeout:actionTimeout})!==value)throw new Error(`${key} readback does not match request`);
}
export async function updateShop(page,p){
  validateShopPatch(p);
  // Resolve every requested control before editing any field.
  const controls={};for(const key of Object.keys(p))controls[key]=await shopField(page,key);
  for(const [key,value] of Object.entries(p))await controls[key].fill(value,{timeout:actionTimeout});
  await verifyShop(page,p);
  await saveAndReadback(page,page,/^(?:Save changes|Save)$/i,()=>verifyShop(page,p));
  return {fields:Object.keys(p),readback:'requested shop fields matched after reload'};
}
async function sectionDialog(page){return unique(page.getByRole('dialog',{name:'Manage sections',exact:true}),'sections dialog');}
async function sectionNames(dialog){
  const list=await unique(dialog.getByRole('list',{name:'Sections',exact:true}),'section inventory');
  const rows=list.getByRole('listitem'),names=[];
  for(let i=0;i<await rows.count();i++){
    const row=rows.nth(i);
    if(!await row.isVisible())throw new Error('section inventory contains hidden records');
    const name=(await row.innerText({timeout:actionTimeout})).trim();
    if(!name)throw new Error('section inventory contains an unnamed record');
    names.push(name);
  }
  if(new Set(names).size!==names.length)throw new Error('section inventory is ambiguous');
  return names.sort();
}
export async function createSection(page,title){
  validateSectionTitle(title);title=title.trim();
  await click(page,'Manage sections');
  const dialog=await sectionDialog(page),before=await sectionNames(dialog);
  if(before.includes(title))throw new Error('section already exists; reconcile shop before retrying');
  await click(dialog,/^(?:Add section|New section)$/i);
  const field=await unique(dialog.getByLabel('Section name',{exact:true}),'section name');
  await field.fill(title,{timeout:actionTimeout});
  if(await field.inputValue({timeout:actionTimeout})!==title)throw new Error('section name readback does not match request');
  await saveAndReadback(page,dialog,/^(?:Save|Create)$/i,async()=>{
    await click(page,'Manage sections');
    const after=await sectionNames(await sectionDialog(page));
    if(JSON.stringify(after)!==JSON.stringify([...before,title].sort()))throw new Error('section inventory readback does not match request');
  });
  return {title,readback:'new section and prior inventory matched after reload'};
}
