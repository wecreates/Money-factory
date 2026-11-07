// Conservative semantic controls: unknown/ambiguous editor markup fails closed.
const supported=new Set(['title','description','price','type','tags','images','files']);
async function field(page,name){
  const control=page.getByLabel(name,{exact:true});
  if(await control.count()!==1)throw new Error(`${name} control missing or ambiguous`);
  return control;
}
function matches(name,actual,expected){
  if(name==='Price')return String(actual).trim()!==''&&Number.isFinite(Number(actual))&&Number(actual)===Number(expected);
  return actual===String(expected);
}
async function tagGroup(page){
  const group=page.getByRole('group',{name:'Tags',exact:true});
  if(await group.count()!==1)throw new Error('Tags group missing or ambiguous');
  return group;
}
async function readTags(group){
  const buttons=group.getByRole('button',{name:/^Remove tag /});
  const tags=[];
  for(let i=0;i<await buttons.count();i++){
    const label=await buttons.nth(i).getAttribute('aria-label');
    if(!label?.startsWith('Remove tag '))throw new Error('tag readback unavailable');
    tags.push(label.slice('Remove tag '.length));
  }
  return tags.sort();
}
export function validateListingPatch(p){
  for(const key of Object.keys(p))if(!supported.has(key))throw new Error(`unsupported listing field: ${key}`);
  for(const name of ['title','description'])if(p[name]!==undefined&&(typeof p[name]!=='string'||!p[name].trim()))throw new Error(`${name} must be nonempty text`);
  if(p.price!==undefined&&(!['string','number'].includes(typeof p.price)||String(p.price).trim()===''||!Number.isFinite(Number(p.price))||Number(p.price)<=0))throw new Error('price must be positive');
  if(p.type!==undefined&&p.type!=='download')throw new Error('unsupported listing type');
  if(p.tags!==undefined&&(!Array.isArray(p.tags)||p.tags.length>13||p.tags.some(t=>typeof t!=='string'||!t.trim()||t.length>20)||new Set(p.tags).size!==p.tags.length))throw new Error('invalid tags');
}
export async function verifyListingMetadata(page,p){
  for(const [key,name] of [['title','Title'],['description','Description'],['price','Price']]){
    if(p[key]!==undefined&&!matches(name,await (await field(page,name)).inputValue(),p[key]))throw new Error(`${name} readback does not match request`);
  }
  if(p.type==='download'){
    const control=page.getByRole('radio',{name:/^(?:Digital|Digital files|Digital item)$/i});
    if(await control.count()!==1||!await control.isChecked())throw new Error('digital type readback does not match request');
  }
  if(p.tags!==undefined&&JSON.stringify(await readTags(await tagGroup(page)))!==JSON.stringify([...p.tags].sort()))throw new Error('tags readback does not match request');
}
export async function applyListingMetadata(page,p){
  validateListingPatch(p);
  for(const [key,name] of [['title','Title'],['description','Description'],['price','Price']])if(p[key]!==undefined)await (await field(page,name)).fill(String(p[key]));
  if(p.type==='download'){
    const control=page.getByRole('radio',{name:/^(?:Digital|Digital files|Digital item)$/i});
    if(await control.count()!==1)throw new Error('digital type control missing or ambiguous');
    await control.check();
  }
  if(p.tags!==undefined){
    const group=await tagGroup(page);
    const buttons=group.getByRole('button',{name:/^Remove tag /});
    for(let i=(await buttons.count())-1;i>=0;i--)await buttons.nth(i).click();
    const input=group.getByRole('textbox');
    if(await input.count()!==1)throw new Error('tag input missing or ambiguous');
    for(const tag of p.tags){await input.fill(tag);await input.press('Enter');}
  }
  await verifyListingMetadata(page,p);
}
