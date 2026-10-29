// Records the Round 2 presentation: slides and the live site, one block per narration scene.
// node record.mjs <site-url> <slides-url> <out-dir> <seconds per scene, comma-separated>
// Prints the offset (seconds) where the narration starts; everything before it is warm-up.
import { chromium } from 'playwright';

const [site, slides, outDir, durs] = process.argv.slice(2);
const D = durs.split(',').map(Number);
const ends = D.reduce((a, d) => (a.push((a.at(-1) || 0) + d), a), []);
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, recordVideo: { dir: outDir, size: { width: 1280, height: 720 } } });
const page = await ctx.newPage();
const t0 = Date.now();

// Warm the cache so scene cuts don't flash blank while the site loads.
for (const h of ['#/receipt/RV-2026-001001-b2.json', '#/record']) {
  await page.goto(site + h, { waitUntil: 'networkidle' });
}
await page.goto(slides + '#1', { waitUntil: 'networkidle' });
await page.waitForTimeout(600);
const start = Date.now();
const until = async (i) => { const left = start + ends[i] * 1000 - Date.now(); if (left > 0) await page.waitForTimeout(left); };
const slide = async (n) => {
  if (!page.url().startsWith(slides)) await page.goto(slides + '#' + n, { waitUntil: 'networkidle' });
  else await page.evaluate((x) => { location.hash = '#' + x; }, n);
};
const scrollTo = (sel, offset = 80) => page.evaluate(([s, o]) => {
  const el = document.querySelector(s);
  if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - o, behavior: 'smooth' });
}, [sel, offset]);
const scrollBy = (y) => page.evaluate((dy) => window.scrollBy({ top: dy, behavior: 'smooth' }), y);

// 1-5: title, problem, users and solution, architecture, design choices
for (let i = 0; i < 5; i++) { await slide(i + 1); await until(i); }

// 6: Amina's receipt
await page.goto(site + '#/receipt/RV-2026-001001-b2.json', { waitUntil: 'networkidle' });
await page.waitForTimeout(13000);
await scrollTo('.match', 70);
await page.waitForTimeout(11000);
await scrollTo('.match .checks', 300);
await until(5);

// 7: languages
await scrollTo('.tabs', 140);
await page.waitForTimeout(600);
await page.click('.tab[data-lang="te"]');
await page.waitForTimeout(2000);
await page.click('.tab[data-lang="hi"]');
await until(6);

// 8: check against the chain, then edit it
await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
await page.waitForTimeout(800);
await page.click('#verify');
await page.waitForTimeout(6500);
await page.click('#tamper');
await page.waitForTimeout(700);
await page.locator('button[data-t="0"]').click();
await until(7);

// 9: the appeal
await scrollTo('#appeal', 60);
await page.waitForTimeout(5500);
await scrollBy(320);
await until(8);

// 10: public record
await page.goto(site + '#/record', { waitUntil: 'networkidle' });
await page.waitForSelector('.chart', { timeout: 20000 });
await page.waitForTimeout(5000);
await scrollTo('h2', 20);
await page.waitForTimeout(8000);
await scrollTo('h2:last-of-type', 20);
await page.waitForTimeout(1500);
await scrollBy(300);  // the two open appeals are the last rows
await until(9);

// 11-13: what's new, impact and feasibility, close
for (let i = 10; i < 13; i++) { await slide(i - 4); await until(i); }

await ctx.close();
await browser.close();
console.log(((start - t0) / 1000).toFixed(2));
