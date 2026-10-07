import { expect, test } from "@playwright/test";
import { fixtureUrl, stageCanvas, stageSeq } from "./support/world";

// FR-WLD-13 (PRD 9.7/9.8): "Mobile world canvas: 30 fps with 20 agents on the reference phone" (a mid-range
// phone). Local run (`TILO_PERF_PHONE=1 TILO_WEB_PORT=<port> pnpm exec playwright test --project=perf-phone
// --no-deps --workers=1`; CI never sets it): the production build served by `vite preview`, a 390x844
// touch phone at device scale 3 (a common mid-range phone), CPU slowed 4x, the 20-agent crowd fixture
// (19 agents emit agent.moved throughout, as in FR-WLD-10).
//
// Asserted: over a 5 s window of requestAnimationFrame deltas, taken once the replay is past its setup
// events and moving, the median fps is >= 30. The p5 fps (the slow tail) is logged, not asserted.
const WINDOW_MS = 5_000;
const FLOOR_FPS = 30;

test.use({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 3,
  isMobile: true,
  hasTouch: true,
});

test("FR-WLD-13 perf: median fps >= 30 on a 390x844 phone, 4x CPU throttle, 20 agents moving", async ({
  page,
}) => {
  await page.goto(fixtureUrl("crowd-20"));
  await expect(stageCanvas(page)).toBeVisible();

  const client = await page.context().newCDPSession(page);
  await client.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await expect.poll(() => stageSeq(page), { timeout: 20_000 }).toBeGreaterThan(25);

  const { medianFps, p5Fps, frames } = await page.evaluate((windowMs) => {
    return new Promise<{ medianFps: number; p5Fps: number; frames: number }>((resolve) => {
      const deltas: number[] = [];
      const start = performance.now();
      let last = start;
      function tick(now: number) {
        deltas.push(now - last);
        last = now;
        if (now - start < windowMs) return void requestAnimationFrame(tick);
        const sorted = [...deltas].sort((a, b) => a - b);
        const at = (q: number) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))] ?? 1;
        // median frame time -> median fps; p5 fps comes from the p95 frame time
        resolve({ medianFps: 1000 / at(0.5), p5Fps: 1000 / at(0.95), frames: deltas.length });
      }
      requestAnimationFrame(tick);
    });
  }, WINDOW_MS);
  await client.detach();

  console.log(
    `FR-WLD-13 perf: median fps=${medianFps.toFixed(1)}, p5 fps=${p5Fps.toFixed(1)}, frames=${frames}`,
  );
  expect(medianFps, `median fps ${medianFps.toFixed(1)} below ${FLOOR_FPS}`).toBeGreaterThanOrEqual(
    FLOOR_FPS,
  );
});
