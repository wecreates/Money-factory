
export const PORT=Number(process.env.PORT||8787);
export const MAX_PARALLEL=Math.max(1,Number(process.env.MAX_PARALLEL||4));
export const PROFILE_ROOT=process.env.PROFILE_ROOT||'/data/profiles';
export const QUEUE_ROOT=process.env.QUEUE_ROOT||'/data/queue';
export const ARTIFACT_ROOT=process.env.ARTIFACT_ROOT||'/data/artifacts';
export const FARM_TOKEN=process.env.FARM_TOKEN||'';
export const HEADLESS=process.env.HEADLESS!=='false';
