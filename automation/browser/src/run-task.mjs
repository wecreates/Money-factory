import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import { validateTask } from './task.mjs';

const taskPath = process.argv[2];
if (!taskPath) throw new Error('Usage: node src/run-task.mjs <task.json>');
const raw = JSON.parse(await fs.readFile(taskPath, 'utf8'));
const task = validateTask(raw);
const outDir = path.join('results', task.id);
await fs.mkdir(outDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const startedAt = new Date().toISOString();
const result = { id: task.id, type: task.type, url: task.url, startedAt, actions: [], success: false };

try {
  await page.goto(task.url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  for (const action of task.actions) {
    if (action.type === 'click') {
      await page.getByText(action.text, { exact: action.exact ?? false }).first().click({ timeout: 15000 });
      result.actions.push({ type:'click', text: action.text });
    } else if (action.type === 'fill') {
      await page.getByLabel(action.label, { exact: action.exact ?? false }).fill(action.value, { timeout: 15000 });
      result.actions.push({ type:'fill', label: action.label });
    } else if (action.type === 'wait') {
      await page.waitForTimeout(action.ms);
      result.actions.push({ type:'wait', ms: action.ms });
    } else if (action.type === 'extract') {
      const text = (await page.locator(action.selector).first().innerText({ timeout: 15000 })).slice(0, 12000);
      result.actions.push({ type:'extract', selector: action.selector, text });
    } else if (action.type === 'screenshot') {
      const name = action.name || `step-${result.actions.length + 1}.png`;
      await page.screenshot({ path: path.join(outDir, name), fullPage: true });
      result.actions.push({ type:'screenshot', name });
    }
  }
  result.finalUrl = page.url();
  result.title = await page.title();
  result.bodyText = (await page.locator('body').innerText()).slice(0, 16000);
  if (task.screenshot) {
    await page.screenshot({ path: path.join(outDir, 'final.png'), fullPage: true });
    result.screenshot = 'final.png';
  }
  result.success = true;
} catch (error) {
  result.error = String(error?.stack || error);
  try { await page.screenshot({ path: path.join(outDir, 'error.png'), fullPage: true }); } catch {}
} finally {
  result.finishedAt = new Date().toISOString();
  await fs.writeFile(path.join(outDir, 'result.json'), JSON.stringify(result, null, 2));
  await browser.close();
}

if (!result.success) process.exitCode = 1;
