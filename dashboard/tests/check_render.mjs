// Render checks for the themed dashboard (issue 257). Needs Node and Playwright with Chromium.
// Usage: node dashboard/tests/check_render.mjs <snapshot.json> [screenshot-dir]
// Checks, in light and dark at 390, 800 and 1400 px: no console errors, no network requests, no horizontal
// overflow, hatched cells == unobserved or unavailable cells for every heat map, and the data-label chip
// for simulated, real and mixed snapshots. Exits 1 on any failure.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const { chromium } = createRequire(import.meta.url)("playwright");
const [snapPath, shots] = process.argv.slice(2);
if (!snapPath) { console.error("usage: node dashboard/tests/check_render.mjs <snapshot.json> [screenshot-dir]"); process.exit(2); }
const base = JSON.parse(readFileSync(snapPath, "utf8"));
const page_url = "file://" + path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "index.html");
const MAPS = ["normal", "obs_vs_exp", "unusual", "exposure"];
const failures = [];
const check = (ok, what) => { if (!ok) failures.push(what); };
const expectedHatched = (snap, name) => snap.cells.weeks[snap.meta.week].filter(c =>
  c[name] === null || (name === "exposure" && !c.observed) || !snap.cells.legends[name].breaks.length).length;

const browser = await chromium.launch();
for (const mode of ["light", "dark"]) {
  for (const width of [390, 800, 1400]) {
    for (const label of width === 1400 ? ["simulated", "real", "mixed"] : [base.meta.data_label]) {
      const snap = { ...base, meta: { ...base.meta, data_label: label } };
      const page = await browser.newPage({ viewport: { width, height: 900 }, colorScheme: mode });
      const errors = [], requests = [];
      page.on("pageerror", e => errors.push(e.message));
      page.on("console", m => m.type() === "error" && errors.push(m.text()));
      page.on("request", r => { if (!r.url().startsWith("file:")) requests.push(r.url()); });
      await page.addInitScript(s => { window.pywebview = { api: { get_snapshot: async () => s } }; }, snap);
      await page.goto(page_url);
      await page.waitForSelector("#sites li:not(.skeleton)");
      const tag = `${mode} ${width}px ${label}`;
      check(await page.evaluate(() => document.documentElement.dataset.mode) === mode, `${tag}: theme follows the system`);
      check((await page.textContent("#banner")).includes(`Data: ${label}`), `${tag}: chip shows the data label`);
      check(await page.getAttribute("#banner", "data-label") === label, `${tag}: chip is styled for the label`);
      for (const name of MAPS) {
        await page.click(`#map button[data-value="${name}"]`);
        const got = await page.locator("#heat rect.hatched").count(), want = expectedHatched(snap, name);
        check(got === want, `${tag} ${name}: ${got} hatched cells, expected ${want}`);
      }
      const over = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      check(over <= 0, `${tag}: horizontal overflow of ${over}px`);
      check(errors.length === 0, `${tag}: console errors ${JSON.stringify(errors)}`);
      check(requests.length === 0, `${tag}: network requests ${JSON.stringify(requests)}`);
      if (shots && label === base.meta.data_label) {
        await page.click('#map button[data-value="normal"]');
        await page.screenshot({ path: path.join(shots, `dashboard-${mode}-${width}.png`), fullPage: width < 1400 });
      }
      await page.close();
    }
  }
}
// Radar backdrop (contract #263): an embedded PNG is drawn with its chip; a web address is never fetched.
const { deflateSync, crc32 } = await import("node:zlib");
const chunk = (type, data) => {
  const head = Buffer.alloc(8); head.writeUInt32BE(data.length); head.write(type, 4);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(Buffer.concat([Buffer.from(type), data])));
  return Buffer.concat([head, data, crc]);
};
const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(8); ihdr.writeUInt32BE(4, 4); ihdr[8] = 8; // 8 x 4 greyscale
const rows = Buffer.concat([...Array(4)].map(() => Buffer.from([0, ...[...Array(8)].map((_, x) => x * 32)])));
const png = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(rows)), chunk("IEND", Buffer.alloc(0))]);
const g = Object.values(base.cells.geometry), bounds = [Math.min(...g.map(b => b[0])), Math.min(...g.map(b => b[1])), Math.max(...g.map(b => b[2])), Math.max(...g.map(b => b[3]))];
for (const [what, image, drawn] of [["embedded png", "data:image/png;base64," + png.toString("base64"), 1], ["web address", "https://example.invalid/radar.png", 0]]) {
  const snap = { ...base, basemap: { ...base.basemap, backdrop: { image, bounds, attribution: "Contains modified Copernicus Sentinel data", from: "2026-08-30", to: "2026-11-27" } } };
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const requests = [], errors = [];
  page.on("request", r => { if (!r.url().startsWith("file:") && !r.url().startsWith("data:")) requests.push(r.url()); });
  page.on("pageerror", e => errors.push(e.message));
  await page.addInitScript(s => { window.pywebview = { api: { get_snapshot: async () => s } }; }, snap);
  await page.goto(page_url);
  await page.waitForSelector("#sites li:not(.skeleton)");
  const tag = `backdrop (${what})`;
  check(await page.locator("#ov-backdrop image").count() === drawn, `${tag}: image drawn ${drawn ? "once" : "never"}`);
  check(await page.isVisible("#t-backdrop") === !!drawn, `${tag}: chip ${drawn ? "shown" : "hidden"}`);
  check(requests.length === 0 && errors.length === 0, `${tag}: requests ${JSON.stringify(requests)} errors ${JSON.stringify(errors)}`);
  if (drawn) {
    const seeThrough = () => page.evaluate(() => document.getElementById("svg").classList.contains("see-through"));
    check(await seeThrough(), `${tag}: cells see-through while the image is on`);
    check((await page.textContent("#legend")).includes("Copernicus"), `${tag}: attribution in the legend`);
    await page.click("#t-backdrop");
    check(!(await seeThrough()) && !(await page.isVisible("#ov-backdrop")), `${tag}: chip turns the image off and restores exact colours`);
    const hatchedOpaque = await page.evaluate(() => getComputedStyle(document.querySelector("#heat rect.hatched") ?? document.body).fillOpacity);
    check(hatchedOpaque === "1", `${tag}: hatched cells stay opaque`);
    if (shots) { await page.click("#t-backdrop"); await page.screenshot({ path: path.join(shots, "dashboard-backdrop.png") }); }
  }
  await page.close();
}

await browser.close();
console.log(failures.length ? `FAIL\n${failures.join("\n")}` : "All render checks passed.");
process.exit(failures.length ? 1 : 0);
