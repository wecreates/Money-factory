import fs from 'node:fs/promises';
const r=await fetch('https://cyzorcreations.com/openapi.json');
const spec=await r.json();
const wanted=[
  '/brain/db.query',
  '/brain/platform.state_probe',
  '/brain/queue.stuck',
  '/brain/business.cron_fanout_test',
  '/brain/heal.tick',
  '/brain/parity.file_self_dev',
  '/brain/parity.preview_self_dev',
  '/brain/platform.ship.codegen',
  '/brain/platform.ship.mark'
];
const out={checked_at:new Date().toISOString(),routes:{}};
for(const p of wanted) out.routes[p]=spec.paths?.[p]||null;
await fs.writeFile('NOVAN_REPAIR_CONTRACTS.json',JSON.stringify(out,null,2)+'\n');
console.log(JSON.stringify(out,null,2));
