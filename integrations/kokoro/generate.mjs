// Existing Kokoro voices; pinned q8 offline audition, never a production asset.
import {readFileSync, writeFileSync, existsSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {assertCompleteText} from './contract.mjs';
const job=JSON.parse(readFileSync(0,'utf8'));
if(job.publication_enabled!==false || job.paid_generation_enabled!==false)throw Error('Disabled flags required');
if(!['am_adam','am_fenrir','am_michael'].includes(job.voice))throw Error('Existing male preset required');
if(typeof job.text!=='string'||!job.text.trim()||job.text.length>1200)throw Error('Bounded text required');
if(existsSync(job.output)||existsSync(job.output+'.json'))throw Error('Output must be new');
const expected=JSON.parse(readFileSync(new URL('./model-manifest.json',import.meta.url),'utf8'));
const digest=b=>createHash('sha256').update(b).digest('hex');
for(const [name,entry]of Object.entries(expected.files)){
 const base=name.startsWith('voices/')?join(job.runtime,'node_modules/kokoro-js'):join(job.runtime,'model');
 const bytes=readFileSync(join(base,name));
 if(bytes.length!==entry.size_bytes||digest(bytes)!==entry.sha256)throw Error('Pinned model/voice bytes differ');
}
for(const [name,version]of Object.entries({'kokoro-js':'1.2.1','@huggingface/transformers':'3.5.1'})){
 if(JSON.parse(readFileSync(join(job.runtime,'node_modules',name,'package.json'),'utf8')).version!==version)throw Error('Runtime version differs');
}
const hf=await import(pathToFileURL(join(job.runtime,'node_modules/@huggingface/transformers/dist/transformers.node.mjs')));
const {KokoroTTS,TextSplitterStream}=await import(pathToFileURL(join(job.runtime,'node_modules/kokoro-js/dist/kokoro.js')));
hf.env.allowRemoteModels=false;hf.env.allowLocalModels=true;
globalThis.fetch=async()=>{throw Error('Network disabled during inference')};
const started=performance.now();
const model=await hf.StyleTextToSpeech2Model.from_pretrained(join(job.runtime,'model'),{
 dtype:'q8',device:'cpu',local_files_only:true,session_options:{intraOpNumThreads:2,interOpNumThreads:1}});
const tokenizer=await hf.AutoTokenizer.from_pretrained(join(job.runtime,'model'),{local_files_only:true});
const tts=new KokoroTTS(model,tokenizer);
const input=new TextSplitterStream();input.push(job.text);input.close();
const chunks=[],segments=[];
for await(const piece of tts.stream(input,{voice:job.voice,speed:1.0})){
 const tokens=tokenizer(piece.phonemes,{truncation:false}).input_ids.dims.at(-1);
 if(tokens>511)throw Error('Refusing a truncated utterance');
 const data=piece.audio.audio;
 if(!(data instanceof Float32Array)||!data.length||data.length>24000*90)throw Error('Invalid audio chunk');
 let peak=0;for(const sample of data){if(!Number.isFinite(sample))throw Error('Nonfinite waveform');peak=Math.max(peak,Math.abs(sample));}
 if(peak>1||peak<0.001)throw Error('Clipped or silent chunk');
 chunks.push(data);segments.push({text:piece.text,phoneme_tokens:tokens,samples:data.length});
}
assertCompleteText(job.text,segments);
const count=chunks.reduce((n,a)=>n+a.length,0);if(!count||count>24000*120)throw Error('Audio duration outside bound');
const data=new Float32Array(count);let cursor=0;for(const chunk of chunks){data.set(chunk,cursor);cursor+=chunk.length;}
// PCM16 WAV written exclusively; no encoder, device, service or publication.
const wav=Buffer.alloc(44+count*2);wav.write('RIFF');wav.writeUInt32LE(wav.length-8,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(24000,24);wav.writeUInt32LE(48000,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(count*2,40);
let energy=0,peak=0;for(let i=0;i<count;i++){energy+=data[i]**2;peak=Math.max(peak,Math.abs(data[i]));wav.writeInt16LE(Math.round(Math.max(-1,Math.min(1,data[i]))*32767),44+i*2);}
writeFileSync(job.output,wav,{flag:'wx'});
const receipt={schema_version:1,status:'GENERATED_PENDING_REVIEW',engine:'kokoro-js',runtime_version:'1.2.1',model_repository:expected.model_repository,model_revision:expected.model_revision,quantization:'q8',model_sha256:expected.files['onnx/model_quantized.onnx'].sha256,voice:job.voice,text_sha256:digest(Buffer.from(job.text)),audio_sha256:digest(wav),sample_rate:24000,channels:1,samples:count,duration_seconds:count/24000,rms:Math.sqrt(energy/count),peak,elapsed_seconds:(performance.now()-started)/1000,process_max_rss_bytes:process.resourceUsage().maxRSS*1024,segments,publication_enabled:false,paid_generation_enabled:false,production_approved:false,full_av_review:false,scope:'Isolated offline quantized audition only; no change to existing production voices or assets'};
writeFileSync(job.output+'.json',JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({status:receipt.status,audio_sha256:receipt.audio_sha256,duration_seconds:receipt.duration_seconds,elapsed_seconds:receipt.elapsed_seconds}));
await model.dispose();
