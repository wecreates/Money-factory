import fs from 'node:fs/promises';
import path from 'node:path';

export async function validateListingUploads(task){
  const uploads={images:[],files:[]};
  if(task.type!=='update_listing')return uploads;
  for(const field of ['images','files']){
    const requested=task.patch[field];
    if(requested===undefined)continue;
    if(!Array.isArray(requested)||!requested.length)throw new Error(`${field} must contain the requested local files`);
    for(const value of requested){
      if(typeof value!=='string'||!value.trim())throw new Error(`invalid ${field} path`);
      const filename=path.resolve(value);
      const entry=await fs.stat(filename);
      if(!entry.isFile()||entry.size===0)throw new Error(`required ${field} must be nonempty regular files`);
      uploads[field].push(filename);
    }
  }
  return uploads;
}

async function digitalFileInput(page){
  // A generic last file input can be an image control. Require digital semantics.
  const labeled=page.getByLabel(/^(?:upload\s+)?(?:digital|downloadable)\s+files?$/i);
  if(await labeled.count()===1&&await labeled.getAttribute('type')==='file')return labeled;
  const accepted=page.locator('input[type="file"][accept*=".pdf"], input[type="file"][accept*=".zip"], input[type="file"][accept*="application/pdf"], input[type="file"][accept*="application/zip"]');
  if(await accepted.count()!==1)throw new Error('digital upload input missing or ambiguous; no save attempted');
  return accepted;
}

export async function uploadAndSaveListing(page,uploads){
  if(uploads.images.length){
    const input=page.locator('input[type="file"][accept*="image"]');
    if(await input.count()!==1)throw new Error('image upload input missing or ambiguous; no save attempted');
    await input.setInputFiles(uploads.images);
  }
  if(uploads.files.length)await (await digitalFileInput(page)).setInputFiles(uploads.files);

  const confirmation=page.getByText(/(?:your )?changes (?:have been )?saved|listing (?:has been )?saved|all changes saved/i).first();
  // An already-visible old message must disappear before a new save can count.
  await confirmation.waitFor({state:'hidden',timeout:2000});
  const save=page.getByRole('button',{name:/^(?:Save changes|Publish changes|Save)$/i});
  if(await save.count()!==1||!await save.isVisible()||!await save.isEnabled())throw new Error('save control missing, ambiguous or disabled');
  await save.click();
  try{
    await confirmation.waitFor({state:'visible',timeout:10000});
  }catch{
    throw new Error('save submitted but not confirmed; reconcile listing before retrying');
  }
}
