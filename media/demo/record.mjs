// Records the demo walkthrough, one block per narration scene.
// node record.mjs <base-url> <out-dir> <seconds per scene, comma-separated>
// Prints the offset (seconds) of the first frame worth keeping.
import { chromium } from 'playwright';

const [base, outDir, durs] = process.argv.slice(2);
const D = durs.split(',').map(Number);
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, recordVideo: { dir: outDir, size: { width: 1280, height: 720 } } });
const page = await ctx.newPage();
const t0 = Date.now();
const until = async (end) => { const left = t0ms + end * 1000 - Date.now(); if (left > 0) await page.waitForTimeout(left); };
const scrollTo = (sel, offset = 80) => page.evaluate(([s, o]) => {
  const el = document.querySelector(s);
  if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - o, behavior: 'smooth' });
}, [sel, offset]);
const scrollBy = (y) => page.evaluate((dy) => window.scrollBy({ top: dy, behavior: 'smooth' }), y);
const ends = D.reduce((a, d) => (a.push((a.at(-1) || 0) + d), a), []);

await page.goto(base + '#/', { waitUntil: 'networkidle' });
await page.waitForTimeout(800);
const t0ms = Date.now();               // narration starts here
const offset = (t0ms - t0) / 1000;

// 1. the problem
await page.waitForTimeout(16000);
await scrollTo('.quote', 120);
await until(ends[0]);

// 2. Amina's receipt
await page.goto(base + '#/receipt/RV-2026-001001-b2.json', { waitUntil: 'networkidle' });
await until(ends[1]);

// 3. what decided it
await scrollTo('.match', 70);
await page.waitForTimeout(14000);
await scrollTo('.match .checks', 300);
await until(ends[2]);

// 4. languages
await scrollTo('.tabs', 140);
await page.waitForTimeout(2500);
await page.click('.tab[data-lang="te"]');
await page.waitForTimeout(5000);
await page.click('.tab[data-lang="hi"]');
await until(ends[3]);

// 5. check against the chain
await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
await page.waitForTimeout(1500);
await page.click('#verify');
await page.waitForTimeout(4000);
await scrollTo('#vlist', 160);
await until(ends[4]);

// 6. try to edit it
await page.click('#tamper');
await page.waitForTimeout(1200);
await page.locator('button[data-t="0"]').click();
await until(ends[5]);

// 7. the appeal
await scrollTo('#appeal', 60);
await page.waitForTimeout(7000);
await scrollBy(320);
await until(ends[6]);

// 8. public record
await page.goto(base + '#/record', { waitUntil: 'networkidle' });
await page.waitForSelector('.chart', { timeout: 20000 });
await page.waitForTimeout(6000);
await scrollTo('h2', 20);
await page.waitForTimeout(9000);
await scrollTo('.note', 200);
await until(ends[7]);

// 9. appeals and the end
await scrollTo('h2:last-of-type', 20);
await page.waitForTimeout(3000);
await scrollBy(500);
await until(ends[8]);

await ctx.close();
await browser.close();
console.log(offset.toFixed(2));
