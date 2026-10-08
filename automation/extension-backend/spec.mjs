export function resolveMonitorApi(env=process.env){
  return env.CYZOR_MONITOR_API || 'https://content-control-render-worker.onrender.com/api/v1/ext';
}
export const API=resolveMonitorApi();
export const VERIFY='https://cyzorcreations.com/tools/pro/verify';
export const KINDS=['change','hiring','price'];
export function clientId(now=Date.now()){ return 'cyzor-release-smoke-'+now; }
export function watchPayload(clientId,kind){
  return {clientId,kind,targetUrl:'https://example.com/',label:'CYZOR release smoke test'};
}
