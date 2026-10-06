import fs from 'node:fs/promises';
import path from 'node:path';
import config from './config.json' with {type:'json'};
import {refreshAccessToken,fetchStatus,uploadPackage,publishItem,cancelSubmission} from './api.mjs';

const [action,target='all']=process.argv.slice(2);
if (!['status','upload','publish','cancel'].includes(action)) {
  throw new Error('Usage: node cli.mjs <status|upload|publish|cancel> <all|extension name|extension id>');
}
const publisherId=process.env.CWS_PUBLISHER_ID;
if (!publisherId) throw new Error('Missing CWS_PUBLISHER_ID');
const chosen=target==='all' ? config.extensions : config.extensions.filter(x =>
  x.name.toLowerCase()===target.toLowerCase() || x.id===target
);
if (!chosen.length) throw new Error('No matching extension');
const token=await refreshAccessToken();

for (const ext of chosen) {
  let result;
  if (action==='status') result=await fetchStatus({publisherId,extensionId:ext.id,token});
  if (action==='upload') {
    const file=path.resolve(process.env.CWS_PACKAGES_ROOT || config.packages_root,ext.package_file);
    const bytes=new Uint8Array(await fs.readFile(file));
    result=await uploadPackage({publisherId,extensionId:ext.id,token,bytes});
  }
  if (action==='publish') result=await publishItem({publisherId,extensionId:ext.id,token});
  if (action==='cancel') result=await cancelSubmission({publisherId,extensionId:ext.id,token});
  console.log(JSON.stringify({extension:ext.name,id:ext.id,action,result}));
}
