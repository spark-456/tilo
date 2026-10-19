// P0-PERF: cold-route Chromium measurements against the production preview.
import { writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { chromium } from "@playwright/test";

const base = `http://127.0.0.1:${process.env.TILO_WEB_PORT || 4133}`;
const output = process.argv[2];
const routes = [
  ["Home", "/"],
  ["Worlds", "/worlds"],
  ["World", "/world/k1"],
  ["Skills", "/skills"],
  ["Agenda", "/agenda"],
  ["World stage", "/world/w_village_basic/stage?fixture=village-basic&seq=44"],
];
const browser = await chromium.launch({ headless: true, channel: "chrome" });
const rows = [];
for (const width of [1440, 390]) {
  for (const [name, path] of routes) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      deviceScaleFactor: 1,
    });
    await context.addInitScript(() => {
      window.__perf = {
        longTasks: [],
        shifts: [],
        adds: 0,
        removes: 0,
        commits: 0,
        mutations: 0,
        revealMs: null,
      };
      const p = window.__perf;
      new PerformanceObserver((list) =>
        p.longTasks.push(...list.getEntries().map((e) => ({ at: e.startTime, ms: e.duration }))),
      ).observe({ type: "longtask", buffered: true });
      new PerformanceObserver((list) =>
        p.shifts.push(
          ...list
            .getEntries()
            .filter((e) => !e.hadRecentInput)
            .map((e) => e.value),
        ),
      ).observe({ type: "layout-shift", buffered: true });
      const add = EventTarget.prototype.addEventListener;
      const remove = EventTarget.prototype.removeEventListener;
      EventTarget.prototype.addEventListener = function (...args) {
        p.adds++;
        return add.apply(this, args);
      };
      EventTarget.prototype.removeEventListener = function (...args) {
        p.removes++;
        return remove.apply(this, args);
      };
      window.__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
        supportsFiber: true,
        renderers: new Map(),
        inject(renderer) {
          this.renderers.set(1, renderer);
          return 1;
        },
        onCommitFiberRoot() {
          p.commits++;
        },
        onCommitFiberUnmount() {},
      };
      add.call(
        document,
        "DOMContentLoaded",
        () => {
          new MutationObserver((entries) => {
            p.mutations += entries.length;
          }).observe(document.body, { childList: true, subtree: true, attributes: true });
          const root = document.getElementById("root");
          if (root) {
            const watch = new MutationObserver(() => {
              if (!root.hasAttribute("inert")) {
                p.revealMs = performance.now();
                watch.disconnect();
              }
            });
            watch.observe(root, { attributes: true, attributeFilter: ["inert"] });
          }
        },
        { once: true },
      );
    });
    const page = await context.newPage();
    const errors = [];
    const requests = [];
    const assets = [];
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => {
      if (r.url().startsWith(`${base}/`))
        requests.push({ at: Date.now(), url: r.url(), type: r.resourceType() });
    });
    page.on("response", async (r) => {
      const type = r.request().resourceType();
      if (type !== "script" && type !== "image") return;
      try {
        const body = await r.body();
        assets.push({
          url: new URL(r.url()).pathname,
          local: r.url().startsWith(`${base}/`),
          protocol: new URL(r.url()).protocol,
          type,
          bytes: body.length,
          gzip: type === "script" ? gzipSync(body).length : undefined,
        });
      } catch {
        /* A cancelled response has no body. */
      }
    });
    const started = Date.now();
    await page.goto(base + path, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page
      .waitForSelector("[data-park], [data-stage-ready='true']", { timeout: 30000 })
      .catch(() => {});
    await page.waitForTimeout(2500);
    const after = Date.now();
    await page.waitForTimeout(2500);
    let fps = null;
    if (name === "World stage") {
      const stage = page.locator("[data-stage-ready='true']").first();
      if (await stage.count()) {
        await stage.focus();
        fps = await page.evaluate(async () => {
          const times = [];
          const end = performance.now() + 1200;
          const sample = (t) => {
            times.push(t);
            if (t < end) requestAnimationFrame(sample);
          };
          requestAnimationFrame(sample);
          document
            .querySelector("[data-stage-ready='true']")
            ?.dispatchEvent(
              new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true }),
            );
          await new Promise((resolve) => setTimeout(resolve, 1250));
          return Math.round(((times.length - 1) * 1000) / (times.at(-1) - times[0]));
        });
      }
    }
    const pageMetrics = await page.evaluate(() => {
      const p = window.__perf;
      const load = performance.getEntriesByType("navigation")[0]?.loadEventEnd || 0;
      const post = p.longTasks.filter((t) => t.at >= load);
      return {
        longTasks: p.longTasks.length,
        postLoadLongTasks: post.length,
        maxPostLoadTaskMs: Math.max(0, ...post.map((t) => t.ms)),
        cls: p.shifts.reduce((a, b) => a + b, 0),
        listenerAdds: p.adds,
        listenerRemoves: p.removes,
        reactCommits: p.commits,
        domMutations: p.mutations,
        imageElements: document.images.length,
        revealMs: p.revealMs,
      };
    });
    const networkAssets = assets.filter((a) => a.local);
    rows.push({
      width,
      name,
      path,
      readyMs: after - started - 2500,
      requests: requests.length,
      laterRequests: requests.filter((r) => r.at >= after).length,
      jsGzipBytes: networkAssets.filter((a) => a.type === "script").reduce((n, a) => n + a.gzip, 0),
      imageBytes: networkAssets.filter((a) => a.type === "image").reduce((n, a) => n + a.bytes, 0),
      images: networkAssets.filter((a) => a.type === "image").length,
      generatedBlobBytes: assets
        .filter((a) => a.protocol === "blob:")
        .reduce((n, a) => n + a.bytes, 0),
      generatedBlobs: assets.filter((a) => a.protocol === "blob:").length,
      topImages: networkAssets
        .filter((a) => a.type === "image")
        .sort((a, b) => b.bytes - a.bytes)
        .slice(0, 8),
      topScripts: networkAssets
        .filter((a) => a.type === "script")
        .sort((a, b) => b.gzip - a.gzip)
        .slice(0, 8),
      fps,
      errors,
      ...pageMetrics,
    });
    await context.close();
  }
}
await browser.close();
if (output) writeFileSync(output, JSON.stringify(rows, null, 2));
else console.log(JSON.stringify(rows, null, 2));
