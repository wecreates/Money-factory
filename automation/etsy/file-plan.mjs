import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {safeRelativePath,verifyZipEntries} from './zip-entries.mjs';

// Etsy Help, verified 2026-10-16: five files, 20 MB/file, 70-char names.
export const MAX_FILES=5,MAX_FILE_BYTES=20_000_000;
const extensions=new Set(['.bmp','.doc','.gif','.jpeg','.jpg','.mobi','.mov','.mp3','.mpeg','.pdf','.png','.psp','.rtf','.stl','.txt','.zip','.epub','.ibook']);

const sha256=bytes=>createHash('sha256').update(bytes).digest('hex');
const digestPattern=/^[a-f0-9]{64}$/;

// This binds a supplied review to an exact ordered file set. It does not
// independently certify product quality or grant permission to upload/publish.
export function fileManifestDigest(manifest){
  return sha256(JSON.stringify({schema_version:manifest.schema_version,listing_id:manifest.listing_id,shop_id:manifest.shop_id,type:manifest.type,files:manifest.files?.map(file=>({path:file.path,sha256:file.sha256,...(file.archive_entries?{archive_entries:file.archive_entries}: {})}))}));
}

function inside(root,file){
  const relative=path.relative(root,file);
  return relative!=='' && !relative.startsWith(`..${path.sep}`) && relative!=='..' && !path.isAbsolute(relative);
}

export async function planListingFiles({root,manifest,listingId,shopId,requiredFilenames=[]}){
  if(!manifest || manifest.schema_version!==1) throw new Error('Unsupported file manifest schema');
  if(typeof manifest.listing_id!=='string' || !/^\d+$/.test(manifest.listing_id) || manifest.listing_id!==String(listingId)) throw new Error('Manifest listing ID does not match selected listing');
  if(typeof manifest.shop_id!=='string' || !/^[1-9]\d*$/.test(manifest.shop_id) || manifest.shop_id!==String(shopId)) throw new Error('Manifest shop ID does not match selected shop');
  if(manifest.type!=='download') throw new Error('Manifest must explicitly describe a digital download');
  if(!Array.isArray(manifest.files) || !manifest.files.length) throw new Error('Manifest must contain the complete nonempty deliverable file set');
  if(manifest.files.length>MAX_FILES) throw new Error('Etsy allows at most five digital files per listing');
  const seenPaths=new Set(),seenNames=new Set();
  for(const file of manifest.files){
    if(!file || !safeRelativePath(file.path)) throw new Error('Manifest file path must be a safe relative path');
    if(typeof file.sha256!=='string' || !digestPattern.test(file.sha256)) throw new Error('Every manifest file requires a lowercase SHA-256');
    const filename=path.basename(file.path);
    if(!/^[A-Za-z0-9._-]{1,70}$/.test(filename)) throw new Error('Etsy upload filename must contain at most 70 supported characters');
    if(!extensions.has(path.extname(filename).toLowerCase())) throw new Error('Unsupported Etsy direct file type; package spreadsheets in a reviewed ZIP');
    if(path.extname(filename).toLowerCase()==='.zip' && (!Array.isArray(file.archive_entries)||!file.archive_entries.length)) throw new Error('ZIP requires reviewed archive_entries');
    if(path.extname(filename).toLowerCase()!=='.zip' && file.archive_entries) throw new Error('archive_entries only applies to ZIP files');
    if(seenPaths.has(file.path) || seenNames.has(filename.toLowerCase())) throw new Error('Duplicate manifest path or upload filename');
    seenPaths.add(file.path); seenNames.add(filename.toLowerCase());
  }
  for(const filename of requiredFilenames){
    if(!manifest.files.some(file=>path.basename(file.path)===filename || file.archive_entries?.some(entry=>entry.path===filename))) throw new Error(`Missing required deliverable: ${filename}`);
  }
  const digest=fileManifestDigest(manifest);
  if(manifest.qa?.status!=='PASS' || typeof manifest.qa.review_id!=='string' || !manifest.qa.review_id.trim() || manifest.qa.reviewed_manifest_sha256!==digest) throw new Error('Missing passing QA review bound to this exact file manifest');
  const rootReal=await fs.realpath(root);
  const files=[];
  for(const [index,file] of manifest.files.entries()){
    const resolved=await fs.realpath(path.join(rootReal,file.path));
    if(!inside(rootReal,resolved)) throw new Error('Manifest file resolves outside product root');
    const stat=await fs.stat(resolved);
    if(!stat.isFile() || stat.size===0) throw new Error('Deliverable must be a nonempty regular file');
    if(stat.size>MAX_FILE_BYTES) throw new Error('Etsy file exceeds conservative 20 MB byte limit');
    const bytes=new Uint8Array(await fs.readFile(resolved));
    if(bytes.length>MAX_FILE_BYTES) throw new Error('Etsy file exceeds conservative 20 MB byte limit');
    if(sha256(bytes)!==file.sha256) throw new Error(`Deliverable hash mismatch: ${file.path}`);
    if(file.archive_entries) verifyZipEntries(bytes,file.archive_entries);
    files.push({filename:path.basename(file.path),rank:index+1,sha256:file.sha256,size_bytes:bytes.length,bytes});
  }
  return {listing_id:manifest.listing_id,shop_id:manifest.shop_id,manifest_sha256:digest,qa_review_id:manifest.qa.review_id,files};
}

export function summarizeFilePlan(plan){
  return {listing_id:plan.listing_id,shop_id:plan.shop_id,manifest_sha256:plan.manifest_sha256,qa_review_id:plan.qa_review_id,files:plan.files.map(({bytes,...file})=>file),content_quality_independently_verified:false,publication_authorized:false,live_listing_type_verified:false};
}

export async function uploadFilePlan({plan,listing,existingFiles,upload,verify}){
  if(!listing || String(listing.listing_id)!==plan.listing_id || String(listing.shop_id)!==plan.shop_id || listing.type!=='download') throw new Error('Seller read-back must confirm the exact listing is a digital download before uploading');
  if(!Array.isArray(plan.files) || !plan.files.length || plan.files.some(file=>!(file.bytes instanceof Uint8Array) || !file.bytes.length || sha256(file.bytes)!==file.sha256)) throw new Error('File plan bytes no longer match the verified hashes');
  if(!existingFiles || existingFiles.count!==0 || !Array.isArray(existingFiles.results) || existingFiles.results.length!==0) throw new Error('Existing or ambiguous listing attachments require seller reconciliation before any upload');
  const uploaded=[];
  for(const file of plan.files){
    const response=await upload(file);
    if(!response?.listing_file_id) throw new Error('Upload response missing listing_file_id; reconcile seller state before retrying');
    const id=String(response.listing_file_id);
    if(uploaded.includes(id)) throw new Error('Upload returned duplicate file IDs; reconcile seller state before retrying');
    uploaded.push(id);
  }
  const listingFiles=await verify();
  if(!Array.isArray(listingFiles?.results) || listingFiles.count!==listingFiles.results.length) throw new Error('Invalid listing-file verification response; reconcile seller state before retrying');
  const present=new Set(listingFiles.results.map(file=>String(file.listing_file_id)));
  if(present.size!==uploaded.length || listingFiles.count!==uploaded.length || uploaded.some(id=>!present.has(id))) throw new Error('Uploaded file missing from seller read-back; reconcile seller state before retrying');
  return {uploaded_file_ids:uploaded,attachment_readback_verified:true,live_listing_type_verified:true,buyer_download_verified:false};
}
