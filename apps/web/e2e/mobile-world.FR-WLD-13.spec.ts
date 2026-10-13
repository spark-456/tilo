import { mkdir, writeFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { fixtureUrl, stageCanvas, stageSeq } from "./support/world";

test.use({ viewport: { width: 390, height: 844 } });

test("FR-WLD-13 mobile 20-agent recorded replay sustains median 30fps with a 4x CPU proxy", async ({
  page,
}, info) => {
  await page.goto(fixtureUrl("crowd-20"));
  await expect(stageCanvas(page)).toBeVisible();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  try {
    await expect.poll(() => stageSeq(page), { timeout: 15000 }).toBeGreaterThan(25);
    const windows: number[][] = [];
    for (let window = 0; window < 3; window++) {
      windows.push(
        await page.evaluate(
          () =>
            new Promise<number[]>((resolve) => {
              const samples: number[] = [];
              let last = performance.now();
              const start = last;
              const tick = (now: number) => {
                samples.push(now - last);
                last = now;
                if (now - start < 3000) requestAnimationFrame(tick);
                else resolve(samples);
              };
              requestAnimationFrame(tick);
            }),
        ),
      );
    }
    const fps = windows.map((w) => (w.length * 1000) / w.reduce((sum, n) => sum + n, 0));
    const medianFps = [...fps].sort((a, b) => a - b)[1] ?? 0;
    const metrics = JSON.stringify(
      {
        requirement: "FR-WLD-13",
        viewport: [390, 844],
        cpuThrottle: 4,
        fixture: "crowd-20",
        agents: 20,
        fps,
        medianFps,
        frameTimesMs: windows,
        limitation:
          "Desktop Chromium throttle proxy; actual reference-phone acceptance is still required.",
      },
      null,
      2,
    );
    await mkdir("reports", { recursive: true });
    await writeFile("reports/FR-WLD-13-mobile-metrics.json", metrics);
    await info.attach("FR-WLD-13 frame times", { body: metrics, contentType: "application/json" });
    expect(medianFps).toBeGreaterThanOrEqual(30);
  } finally {
    await cdp.detach();
  }
});
