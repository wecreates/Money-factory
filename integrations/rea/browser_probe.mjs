/** Inspect only a dedicated, ephemeral browser serving an authorized local fixture. */
import {createRequire} from 'node:module';
import {createServer} from 'node:http';
import {mkdtemp, readFile, readdir, realpath, lstat, rm} from 'node:fs/promises';
import {join, resolve, relative, extname, sep} from 'node:path';
import {tmpdir} from 'node:os';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {pathToFileURL} from 'node:url';
const execute = promisify(execFile);

export function hasPageEvidence(evidence, origin) {
  const page = evidence?.normalized_result;
  return !evidence?.error && evidence?.operation === 'inspect_web_page' &&
    page?.target?.origin === origin && page?.dom?.total_nodes > 0 &&
    Array.isArray(page.dom.nodes) && page.dom.nodes.length > 0 &&
    page?.accessibility?.text_capture?.status === 'included' &&
    page.accessibility.text_capture.retained_bytes > 0;
}

export async function main(runtime, target) {
  const directory = resolve(target);
  if ((await lstat(directory)).isSymbolicLink()) throw new Error('Linked inputs are not supported');
  const root = await realpath(directory);
  async function rejectLinks(dir) {
    for (const entry of await readdir(dir, {withFileTypes:true})) {
      if (entry.isSymbolicLink()) throw new Error('Linked inputs are not supported');
      if (entry.isDirectory()) await rejectLinks(join(dir,entry.name));
    }
  }
  await rejectLinks(root);
  await readFile(join(root,'index.html'));
  const require = createRequire(join(resolve(runtime),'package.json'));
  const {chromium} = require('playwright');
  const rea = join(resolve(runtime),'node_modules/rea-agents');
  if (JSON.parse(await readFile(join(rea,'package.json'),'utf8')).version !== '6.4.0') throw new Error('Unexpected REA version');
  const home = await mkdtemp(join(tmpdir(),'cyzor-rea-browser-'));
  const env = {PATH:process.env.PATH || '', HOME:home, TMPDIR:home,
    PUBLICATION_ENABLED:'false', PAID_GENERATION_ENABLED:'false'};
  let context;
  const server = createServer(async (request,response) => {
    try {
      const pathname = decodeURIComponent(new URL(request.url,'http://127.0.0.1').pathname);
      const filename = resolve(root,'.'+(pathname === '/' ? '/index.html' : pathname));
      const rel = relative(root,filename);
      if (rel.startsWith('..'+sep) || rel === '..' || (await realpath(filename)) !== filename) throw new Error('Outside fixture');
      const types = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg'};
      if (!types[extname(filename)]) throw new Error('Unsupported fixture asset');
      const body = await readFile(filename);
      response.writeHead(200, {'Content-Type':types[extname(filename)],
        'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-src 'none'; worker-src 'none'; form-action 'none'"});
      response.end(body);
    } catch { response.writeHead(404); response.end('Not found'); }
  });
  try {
    await new Promise((done,fail) => {server.once('error',fail);server.listen(0,'127.0.0.1',done);});
    const origin = `http://127.0.0.1:${server.address().port}`;
    const profile = join(home,'browser');
    context = await chromium.launchPersistentContext(profile, {headless:true, env,
      serviceWorkers:'block', acceptDownloads:false,
      args:['--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--disable-background-networking']});
    await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    const page = context.pages()[0] || await context.newPage();
    await page.goto(origin+'/',{waitUntil:'load',timeout:15000});
    const port = (await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];
    if (!/^\d+$/.test(port)) throw new Error('Invalid dedicated CDP port');
    const endpoint = `http://127.0.0.1:${port}`;
    const targets = await (await fetch(endpoint+'/json/list')).json();
    const selected = targets.find(item => item.type === 'page' && item.url === origin+'/');
    if (!selected) throw new Error('Dedicated fixture target missing');
    const args = [join(rea,'scripts/rea.mjs'),'inspect-web-page',endpoint,selected.id,
      '--observation-ms','1000','--include-accessibility-text','--json'];
    let run;
    try { run = {...await execute(process.execPath,args,{env,timeout:60000,maxBuffer:16*1024*1024}),code:0}; }
    catch (error) {run = {stdout:error.stdout || '',stderr:error.stderr || error.message,code:error.code || 1};}
    let evidence;
    try {evidence = JSON.parse(run.stdout);} catch {evidence = {error:'REA did not return JSON',details:run.stderr.slice(0,4000)};}
    return {operation:'inspect-web-page',exit_code:run.code,
      status:run.code === 0 && hasPageEvidence(evidence,origin) ? 'PASS' : 'BLOCKED',
      scope:'Dedicated loopback browser; authorized local HTML only; no existing account sessions',
      evidence, publication_enabled:false, paid_generation_enabled:false};
  } finally {
    if (context) await context.close().catch(()=>{});
    server.closeAllConnections();
    if (server.listening) await new Promise(done=>server.close(done));
    await rm(home,{recursive:true,force:true});
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main(process.argv[2],process.argv[3]).then(result=>{
    console.log(JSON.stringify(result)); process.exitCode = result.status === 'PASS' ? 0 : 2;
  }).catch(error=>{console.log(JSON.stringify({status:'BLOCKED',error:error.message}));process.exitCode=2;});
}
