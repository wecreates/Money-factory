// No network or real browser is used by the runtime regression test.
const stub=`export const chromium={launch:async()=>({
  newContext:async(options)=>{
    if(typeof options.storageState!=='object'||options.storageState.cookies[0].value!=='test-only-session') throw new Error('Expected in-memory test session');
    return {
      storageState:async()=>{throw new Error('Session export must not be called');},
      newPage:async()=>({goto:async()=>{},url:()=> 'https://example.invalid',title:async()=> 'Fixture',locator:()=>({innerText:async()=> 'Fixture page'})})
    };
  },
  close:async()=>{}
})};`;
export async function resolve(specifier,context,nextResolve){
  if(specifier==='playwright') return {url:'data:text/javascript,'+encodeURIComponent(stub),shortCircuit:true};
  return nextResolve(specifier,context);
}
