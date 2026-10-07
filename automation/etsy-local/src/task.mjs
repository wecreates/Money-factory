
const ALLOWED = new Set(['update_listing','update_shop','create_section','verify_public']);

export function validateTask(raw){
  if(!raw || typeof raw!=='object') throw new Error('task required');
  const id=String(raw.id||'').trim();
  if(!/^[a-z0-9][a-z0-9._-]{0,80}$/i.test(id)) throw new Error('invalid id');
  const type=String(raw.type||'').trim();
  if(!ALLOWED.has(type)) throw new Error('invalid type');
  if(type==='update_listing'){
    const listingId=String(raw.listing_id||'').trim();
    if(!/^\d+$/.test(listingId)) throw new Error('invalid listing_id');
    const patch=raw.patch||{};
    if(patch.tags && (!Array.isArray(patch.tags)||patch.tags.length>13)) throw new Error('tags must be <=13');
    if(patch.title && String(patch.title).length>140) throw new Error('title too long');
    return {id,type,listing_id:listingId,patch};
  }
  if(type==='update_shop') return {id,type,patch:raw.patch||{}};
  if(type==='create_section') return {id,type,title:String(raw.title||'').trim()};
  if(type==='verify_public') return {id,type,url:String(raw.url||'')};
}
