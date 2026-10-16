import { writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { chromium } from "@playwright/test";

const [url, output, cpuRate = "4"] = process.argv.slice(2);
if (!url || !output) throw new Error("Usage: node perf-measure.mjs <url> <output-prefix>");

const browser = await chromium.launch({
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  headless: true,
});
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const client = await context.newCDPSession(page);
  await client.send("Emulation.setCPUThrottlingRate", { rate: Number(cpuRate) });
  await page.addInitScript(() => {
    window.__longTasks = [];
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) window.__longTasks.push(entry.duration);
    }).observe({ entryTypes: ["longtask"] });
  });
  const trace = [];
  client.on("Tracing.dataCollected", ({ value }) => trace.push(...value));
  await client.send("Tracing.start", {
    categories:
      "devtools.timeline,v8,blink.user_timing,loading,disabled-by-default-devtools.timeline.frame",
    transferMode: "ReportEvents",
  });
  const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForTimeout(1000);
  const scroll = await page.evaluate(async () => {
    const gaps = [];
    let previous = performance.now();
    const start = previous;
    while (performance.now() - start < 3000) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
      const now = performance.now();
      gaps.push(now - previous);
      previous = now;
      window.scrollBy(0, 9);
    }
    return gaps;
  });
  await page.waitForTimeout(1000);
  const result = await page.evaluate(() => ({
    title: document.title,
    path: location.pathname,
    longTasks: window.__longTasks,
    navigation: performance.getEntriesByType("navigation").map((entry) => ({
      duration: entry.duration,
      domContentLoadedEventEnd: entry.domContentLoadedEventEnd,
      loadEventEnd: entry.loadEventEnd,
    })),
  }));
  await client.send("Tracing.end");
  await new Promise((resolve) => client.once("Tracing.tracingComplete", resolve));
  writeFileSync(`${output}.json.gz`, gzipSync(JSON.stringify({ traceEvents: trace })));
  writeFileSync(
    `${output}.metrics.json`,
    JSON.stringify(
      {
        url,
        status: response?.status(),
        ...result,
        scrollFrames: scroll.length,
        scrollOver50ms: scroll.filter((gap) => gap > 50).length,
        maxScrollGapMs: Math.max(...scroll),
        medianScrollGapMs: scroll.sort((a, b) => a - b)[Math.floor(scroll.length / 2)],
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
