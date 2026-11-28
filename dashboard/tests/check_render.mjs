// Render checks for the dashboard (issues 257, 263, 276, 281). Needs Node and Playwright with Chromium; axe-core
// is used when it can be resolved (a dev tool only, never shipped in the page).
// Usage: node dashboard/tests/check_render.mjs <snapshot.json> [screenshot-dir]
//        BASELINE_DIR=<dir> also compares the screenshots with a baseline set (report only).
// Checks, in light and dark at 390, 800 and 1400 px: no console errors, no network requests, no horizontal
// overflow, hatched cells == unobserved or unavailable cells for every heat map, the data-label chip for
// simulated, real and mixed snapshots, land drawn when present. Then: charts and their table views, zoom and
// reset, scale-bar accuracy, list and map selection, the radar backdrop, reduced motion, load time and axe.
// Exits 1 on any failure.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
let axeSource = null;
try { axeSource = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8"); } catch { /* axe-core not installed: skipped */ }
const [snapPath, shots] = process.argv.slice(2);
if (!snapPath) { console.error("usage: node dashboard/tests/check_render.mjs <snapshot.json> [screenshot-dir]"); process.exit(2); }
const base = JSON.parse(readFileSync(snapPath, "utf8"));
const page_url = "file://" + path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "index.html");
const MAPS = ["normal", "obs_vs_exp", "unusual", "exposure"];
const failures = [], notes = [];
const check = (ok, what) => { if (!ok) failures.push(what); };
const expectedHatched = (snap, name) => snap.cells.weeks[snap.meta.week].filter(c =>
  c[name] === null || (name === "exposure" && !c.observed) || !snap.cells.legends[name].breaks.length).length;

const browser = await chromium.launch();
async function open(snap, opts = {}) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, reducedMotion: "reduce", ...opts });
  const errors = [], requests = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", m => m.type() === "error" && errors.push(m.text()));
  page.on("request", r => { if (!r.url().startsWith("file:") && !r.url().startsWith("data:")) requests.push(r.url()); });
  await page.addInitScript(s => { window.pywebview = { api: { get_snapshot: async () => s } }; }, snap);
  await page.goto(page_url);
  await page.waitForSelector("#sites li:not(.skeleton)");
  return { page, errors, requests };
}

// 1. themes x widths x labels
for (const mode of ["light", "dark"]) {
  for (const width of [390, 800, 1400]) {
    for (const label of width === 1400 ? ["simulated", "real", "mixed"] : [base.meta.data_label]) {
      const snap = { ...base, meta: { ...base.meta, data_label: label } };
      const { page, errors, requests } = await open(snap, { viewport: { width, height: 900 }, colorScheme: mode });
      const tag = `${mode} ${width}px ${label}`;
      check(await page.evaluate(() => document.documentElement.dataset.mode) === mode, `${tag}: theme follows the system`);
      check((await page.textContent("#banner")).includes(`Data: ${label}`), `${tag}: chip shows the data label`);
      check(await page.getAttribute("#banner", "data-label") === label, `${tag}: chip is styled for the label`);
      const land = snap.basemap.features.filter(f => f.properties?.kind === "land").length;
      check(land === 0 || (await page.locator("#base path.land").count()) > 0, `${tag}: land drawn when the snapshot has it`);
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
        await page.screenshot({ path: path.join(shots, `dashboard-${mode}-${width}.png`), fullPage: true });
      }
      await page.close();
    }
  }
}

// 2. charts, table views, figures (#276, #279)
{
  const { page, errors } = await open(base);
  if (base.cells.daily?.length) {
    check(await page.locator("#trends .chart-card").count() === 2, "trends: two chart cards");
    const card = page.locator("#trends .chart-card").first();
    await card.getByRole("button", { name: "Table" }).click();
    check(await card.locator("tbody tr").count() === base.cells.daily.length, "trend table: one row per day");
    const gaps = base.cells.daily.filter(d => d.passes === 0).length;
    check(await page.locator("#trends .chart-card").nth(1).locator("text", { hasText: "×" }).count() === gaps, "coverage chart: one × per day with no pass");
  }
  if (base.meta.figures) check(await page.locator("#figures .figure").count() === 5, "figures: five tiles");
  const scored = base.piers.filter(p => p.P_j !== null).length;
  if (scored) check(await page.locator("#piers svg.chart rect.bar").count() === scored, "pier chart: one bar per scored pier");
  const shipStops = base.plan.ship?.length ?? 0;
  if (shipStops > 2 && base.plan.ship.every(s => s.at_h !== undefined))
    check(await page.locator("#plan svg.chart").count() >= 1, "plan: schedule chart drawn");
  if (base.validation?.recall?.length) check(await page.locator("#validation svg.chart").count() >= 1, "validation: recall chart drawn");

  // 3. zoom, reset, scale bar (#280)
  const vbw = () => page.evaluate(() => Number(document.getElementById("svg").getAttribute("viewBox").split(" ")[2]));
  const full = await vbw();
  await page.click("#zin");
  check(await vbw() < full, "zoom in narrows the view");
  await page.hover("#svg"); await page.mouse.wheel(0, 300);
  await page.click("#zreset");
  check(Math.abs(await vbw() - full) < 1e-6, "reset shows the whole map");
  const scale = await page.evaluate(() => {
    const bar = document.getElementById("scaleBar"), svg = document.getElementById("svg"), [, , vw] = svg.getAttribute("viewBox").split(" ").map(Number);
    const lat = (ext.lat0 + ext.lat1) / 2, lon = (ext.lon0 + ext.lon1) / 2, a = project(lon, lat - 0.05), b = project(lon, lat + 0.05);
    return { km: Number(bar.dataset.km), px: Number(bar.dataset.px), mapPx: (Math.abs(a[1] - b[1]) * svg.getBoundingClientRect().width) / vw, lat };
  });
  const R = 6371.0088, dLat = (0.1 * Math.PI) / 180, haversineKm = R * dLat; // great-circle length of 0.1 degree of latitude
  const truePxPerKm = scale.mapPx / haversineKm, barPxPerKm = scale.px / scale.km;
  check(Math.abs(barPxPerKm / truePxPerKm - 1) < 0.02, `scale bar within 2%: bar ${barPxPerKm.toFixed(3)} px/km, true ${truePxPerKm.toFixed(3)}`);

  // 4. selection: list to map and map to list (#280)
  await page.locator("#sites li").first().getByRole("button", { name: "Map" }).click();
  const firstId = await page.getAttribute("#sites li >> nth=0", "data-id");
  check(await vbw() < full, "list 'Map' button zooms to the site");
  check(await page.locator(`.site-g.selected[data-id="${firstId}"]`).count() === 1, "selected site is highlighted on the map");
  await page.click("#zreset");
  const lastSite = page.locator("#ov-sites .site-g").last(), lastId = await lastSite.getAttribute("data-id");
  await lastSite.dispatchEvent("click");
  check(await page.locator(`#sites li.selected[data-id="${lastId}"] details[open]`).count() === 1, "clicking a site on the map selects and opens it in the list");

  // 5. reduced motion: nothing animates
  check(await page.evaluate(() => document.getAnimations().length) === 0, "reduced motion: no running animations");
  check(errors.length === 0, `charts and interaction: console errors ${JSON.stringify(errors)}`);

  // 6. accessibility (axe-core, when available)
  if (axeSource) {
    await page.addScriptTag({ content: axeSource });
    const res = await page.evaluate(async () => (await window.axe.run(document, { resultTypes: ["violations"] })).violations
      .map(v => ({ id: v.id, impact: v.impact, n: v.nodes.length })));
    const bad = res.filter(v => v.impact === "serious" || v.impact === "critical");
    notes.push(`axe: ${res.length} rule(s) with findings${res.length ? ": " + res.map(v => `${v.id} (${v.impact}, ${v.n})`).join(", ") : ""}`);
    check(bad.length === 0, `axe: serious or critical findings ${JSON.stringify(bad)}`);
  } else notes.push("axe: skipped (axe-core not installed)");
  await page.close();
}

// 7. motion on: load time and long tasks (reported, not gated: this machine is not the demo machine)
{
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, reducedMotion: "no-preference" });
  await page.addInitScript(s => {
    window.pywebview = { api: { get_snapshot: async () => s } };
    window.__long = 0;
    try { new PerformanceObserver(l => { window.__long += l.getEntries().length; }).observe({ type: "longtask", buffered: true }); } catch { /* not supported */ }
  }, base);
  const t0 = Date.now();
  await page.goto(page_url);
  await page.waitForSelector("#sites li:not(.skeleton)");
  const loaded = Date.now() - t0;
  await page.click('#map button[data-value="unusual"]');
  await page.waitForTimeout(400);
  const hatched = await page.locator("#heat rect.hatched").count();
  check(hatched === expectedHatched(base, "unusual"), "with motion on, the cross-fade ends on the right map");
  notes.push(`load to first content: ${loaded} ms; long tasks during load and one map change: ${await page.evaluate(() => window.__long)}`);
  await page.close();
}

// 8. Radar backdrop (contract #263): an embedded PNG is drawn with its chip; a web address is never fetched.
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
  const { page, errors, requests } = await open(snap);
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
  }
  await page.close();
}

await browser.close();

// 9. Visual regression (report only): compare each screenshot with the same file in $BASELINE_DIR, using pngjs and
// pixelmatch when they can be resolved. Changed screens are listed for the PR; a human judges them.
if (shots && process.env.BASELINE_DIR) {
  try {
    const { PNG } = require("pngjs"), pixelmatch = require("pixelmatch");
    const { readdirSync, existsSync } = await import("node:fs");
    for (const f of readdirSync(shots).filter(n => n.startsWith("dashboard-") && n.endsWith(".png"))) {
      const ref = path.join(process.env.BASELINE_DIR, f);
      if (!existsSync(ref)) { notes.push(`visual: ${f} has no baseline`); continue; }
      const a = PNG.sync.read(readFileSync(path.join(shots, f))), b = PNG.sync.read(readFileSync(ref));
      if (a.width !== b.width || a.height !== b.height) { notes.push(`visual: ${f} changed size (${b.width}x${b.height} to ${a.width}x${a.height})`); continue; }
      const diff = pixelmatch(a.data, b.data, null, a.width, a.height, { threshold: 0.1 });
      notes.push(`visual: ${f} ${diff ? `${(100 * diff / (a.width * a.height)).toFixed(2)}% of pixels changed` : "unchanged"}`);
    }
  } catch { notes.push("visual: skipped (pngjs and pixelmatch not installed)"); }
}
for (const n of notes) console.log(n);
console.log(failures.length ? `FAIL\n${failures.join("\n")}` : "All render checks passed.");
process.exit(failures.length ? 1 : 0);
