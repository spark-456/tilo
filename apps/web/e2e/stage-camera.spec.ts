/**
 * P0-08b camera rework (PRD 9.7, HR-3; FR-WLD-04/FR-WLD-10 partial). The P0-08a camera was
 * CSS `translate/scale` on a div the Pixi canvas mirrored; qa-breaker failed it five times
 * (.claude/agent-memory/qa-breaker/web-stage-attack-patterns.md). Those defects (#2 grid/edges
 * at zoom extremes, #4 wheel direction/step bugs, #6 multi-pointer jumps) are now acceptance
 * criteria (C1-C11 below), and the camera becomes a transform on a PixiJS world container.
 *
 * Public interface this file requires beyond e2e/support/camera.ts's `readCamera` (see there
 * for the data-camera-x/y/zoom contract) and camera.ts's existing exports:
 *   - Wheel is handled by a non-passive native listener (addEventListener(..., {passive:false})
 *     or an `on*` assignment — not React's synthetic onWheel, which Chromium/Edge attaches
 *     passive and logs a console error on preventDefault(); qa-breaker pattern #1).
 *   - `[data-testid="stage-frame"]` itself receives the wheel/pointer/keyboard listeners.
 *
 * This file covers C2-C5, C7 (keyboard modifiers only) and C9. C1 (visual/backing-store) and
 * the corner/round-trip half of C8 (grid drift) are in stage-camera-visual.spec.ts; the
 * long-task-stall half of C8 is in stage-settle.spec.ts and its frozen/backgrounded-tab half is
 * in stage-camera-freeze.spec.ts; C6 (pointerId/touch) is in stage-camera-touch.spec.ts; the
 * eased-vs-instant timing half of C7 is in stage-motion.spec.ts; C10 is in stage-idle.spec.ts;
 * and C11 (focus clipping, then its focus-colour-token half) is in stage-camera-a11y.spec.ts
 * and stage-camera-focus-color.spec.ts.
 */
import { type Page, expect, test } from "@playwright/test";
import { PAN_STEP_PX, ZOOM_MAX, ZOOM_MIN, ZOOM_STEP } from "../src/stage/camera";
import { gotoStage, readCamera, reloadStage } from "./support/camera";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP, reducedMotion: "reduce" }); // instant moves: no easing to wait out

type WheelInit = {
  deltaX?: number;
  deltaY?: number;
  deltaMode?: number;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  clientX: number;
  clientY: number;
};

/** Dispatches a real WheelEvent (not page.mouse.wheel, which only emits deltaMode 0) directly
 * on the stage frame and returns whether the handler called preventDefault(). */
async function dispatchWheel(page: Page, init: WheelInit): Promise<boolean> {
  return page.getByTestId("stage-frame").evaluate((el, i) => {
    const ev = new WheelEvent("wheel", {
      deltaX: i.deltaX ?? 0,
      deltaY: i.deltaY ?? 0,
      deltaMode: i.deltaMode ?? 0,
      ctrlKey: i.ctrlKey ?? false,
      shiftKey: i.shiftKey ?? false,
      clientX: i.clientX,
      clientY: i.clientY,
      bubbles: true,
      cancelable: true,
    });
    el.dispatchEvent(ev);
    return ev.defaultPrevented;
  }, init);
}

async function stageCenter(page: Page): Promise<{ x: number; y: number }> {
  const box = await page.getByTestId("stage-frame").boundingBox();
  if (!box) throw new Error("stage-frame has no layout box");
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

function collectConsoleProblems(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") problems.push(`[${m.type()}] ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`[pageerror] ${e.message}`));
  return problems;
}

test("P0-08b camera C2 PRD-9.7 observable camera: stage-frame starts at the documented INITIAL_CAMERA", async ({
  page,
}) => {
  await gotoStage(page);
  await expect(page.getByTestId("stage-frame").locator("canvas")).toBeVisible();
  const cam = await readCamera(page);
  expect(cam).toEqual({ x: 0, y: 0, zoom: 1 });
});

test("P0-08b camera C9 PRD-9.7 wheel: zero console errors/warnings across a run of wheel ticks (non-passive listener)", async ({
  page,
}) => {
  const problems = collectConsoleProblems(page);
  await gotoStage(page);
  const center = await stageCenter(page);
  for (let i = 0; i < 20; i++) {
    const prevented = await dispatchWheel(page, {
      deltaY: i % 2 === 0 ? -20 : 20,
      clientX: center.x,
      clientY: center.y,
    });
    // A native, non-passive listener can call preventDefault(); this also proves it is not
    // React's synthetic (always-passive) onWheel (qa-breaker pattern #1).
    expect(prevented, `wheel tick ${i} was not preventDefault-able`).toBe(true);
  }
  expect(problems, problems.join("\n")).toEqual([]);
});

test("P0-08b camera C3 PRD-9.7 wheel: deltaMode 0/1/2 zoom by the same amount for the same on-screen distance", async ({
  page,
}) => {
  await gotoStage(page);
  const center = await stageCenter(page);
  const start = (await readCamera(page)).zoom;
  await dispatchWheel(page, { deltaY: -100, deltaMode: 0, clientX: center.x, clientY: center.y });
  const afterPixels = (await readCamera(page)).zoom;
  expect(afterPixels).toBeCloseTo(start + ZOOM_STEP, 5);

  await reloadStage(page);
  await dispatchWheel(page, { deltaY: -2.5, deltaMode: 1, clientX: center.x, clientY: center.y });
  const afterLines = (await readCamera(page)).zoom;
  expect(afterLines).toBeCloseTo(afterPixels, 5);

  await reloadStage(page);
  await dispatchWheel(page, { deltaY: -0.125, deltaMode: 2, clientX: center.x, clientY: center.y });
  const afterPages = (await readCamera(page)).zoom;
  expect(afterPages).toBeCloseTo(afterPixels, 5);
});

test("P0-08b camera C3 PRD-9.7 wheel: a smaller delta zooms proportionally less, one event never exceeds one ZOOM_STEP", async ({
  page,
}) => {
  await gotoStage(page);
  const center = await stageCenter(page);
  const start = (await readCamera(page)).zoom;
  await dispatchWheel(page, { deltaY: -50, clientX: center.x, clientY: center.y });
  const half = (await readCamera(page)).zoom;
  expect(half - start).toBeCloseTo(ZOOM_STEP / 2, 5);

  // A single huge tick (e.g. a fast trackpad fling) still caps at one step.
  await reloadStage(page);
  await dispatchWheel(page, { deltaY: -100000, clientX: center.x, clientY: center.y });
  const capped = (await readCamera(page)).zoom;
  expect(capped - start).toBeCloseTo(ZOOM_STEP, 5);
});

test("P0-08b camera C3 PRD-9.7 wheel: zoom keeps the world point under the pointer fixed, within 1px", async ({
  page,
}) => {
  await gotoStage(page);
  const box = await page.getByTestId("stage-frame").boundingBox();
  if (!box) throw new Error("stage-frame has no layout box");
  // An off-centre pointer, well inside the frame.
  const px = box.x + box.width * 0.25;
  const py = box.y + box.height * 0.75;
  const centreOffsetX = px - (box.x + box.width / 2);
  const centreOffsetY = py - (box.y + box.height / 2);

  const before = await readCamera(page);
  const worldX = (centreOffsetX - before.x) / before.zoom;
  const worldY = (centreOffsetY - before.y) / before.zoom;

  await dispatchWheel(page, { deltaY: -240, clientX: px, clientY: py }); // several steps, clamped to one
  const after = await readCamera(page);
  expect(after.zoom).toBeGreaterThan(before.zoom);
  const worldXAfter = (centreOffsetX - after.x) / after.zoom;
  const worldYAfter = (centreOffsetY - after.y) / after.zoom;
  // "within 1px" is a screen-space tolerance: convert the world-space drift back to screen px.
  expect(Math.abs(worldXAfter - worldX) * after.zoom).toBeLessThanOrEqual(1);
  expect(Math.abs(worldYAfter - worldY) * after.zoom).toBeLessThanOrEqual(1);
});

test("P0-08b camera C3 PRD-9.7 wheel: zoom stays clamped to [ZOOM_MIN, ZOOM_MAX] under a long run of extreme input", async ({
  page,
}) => {
  await gotoStage(page);
  const center = await stageCenter(page);
  for (let i = 0; i < 40; i++) {
    await dispatchWheel(page, { deltaY: -100000, clientX: center.x, clientY: center.y });
  }
  await expect.poll(async () => (await readCamera(page)).zoom).toBeLessThanOrEqual(ZOOM_MAX);
  for (let i = 0; i < 80; i++) {
    await dispatchWheel(page, { deltaY: 100000, clientX: center.x, clientY: center.y });
  }
  await expect.poll(async () => (await readCamera(page)).zoom).toBeGreaterThanOrEqual(ZOOM_MIN);
});

test("P0-08b camera C4 PRD-9.7 trackpad pinch (ctrlKey): zooms about the pointer, is preventDefault-able and never pans", async ({
  page,
}) => {
  await gotoStage(page);
  const center = await stageCenter(page);
  const before = await readCamera(page);
  const prevented = await dispatchWheel(page, {
    deltaY: -50,
    deltaX: 3, // trackpad pinch sometimes carries deltaX jitter; must still not pan
    ctrlKey: true,
    clientX: center.x,
    clientY: center.y,
  });
  expect(prevented, "ctrl+wheel (trackpad pinch) must not trigger the browser's own zoom").toBe(
    true,
  );
  const after = await readCamera(page);
  expect(after.zoom).toBeGreaterThan(before.zoom);
  // Pointer was at the stage centre, so "about the pointer" implies x/y are unchanged.
  expect(after.x).toBeCloseTo(before.x, 5);
  expect(after.y).toBeCloseTo(before.y, 5);
});

test("P0-08b camera C4 PRD-9.7 trackpad pinch: zoom is smooth/proportional to deltaY, not stepped like a mouse-wheel notch", async ({
  page,
}) => {
  await gotoStage(page);
  const center = await stageCenter(page);
  const start = (await readCamera(page)).zoom;
  await dispatchWheel(page, { deltaY: -20, ctrlKey: true, clientX: center.x, clientY: center.y });
  const small = (await readCamera(page)).zoom - start;

  await reloadStage(page);
  await dispatchWheel(page, { deltaY: -60, ctrlKey: true, clientX: center.x, clientY: center.y });
  const big = (await readCamera(page)).zoom - start;

  expect(small).toBeGreaterThan(0);
  expect(big).toBeGreaterThan(small);
  expect(big).toBeCloseTo(small * 3, 5); // proportional to deltaY, same 20px unit
});

test("P0-08b camera C3 C4 PRD-9.7 mouse Ctrl + wheel notch (100px) zooms exactly one ZOOM_STEP, not to the clamp", async ({
  page,
}) => {
  await gotoStage(page);
  const center = await stageCenter(page);
  await page.mouse.move(center.x, center.y);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, 100);
  await page.keyboard.up("Control");
  await expect.poll(async () => (await readCamera(page)).zoom).toBeCloseTo(1 - ZOOM_STEP, 5);
});

test("P0-08b camera C5 PRD-9.7 wheel: deltaX and Shift+vertical both pan horizontally by the same amount, never zoom", async ({
  page,
}) => {
  await gotoStage(page);
  const center = await stageCenter(page);
  const before = await readCamera(page);
  await dispatchWheel(page, { deltaX: -100, clientX: center.x, clientY: center.y });
  const viaDeltaX = await readCamera(page);
  expect(viaDeltaX.zoom).toBeCloseTo(before.zoom, 9);
  expect(viaDeltaX.y).toBeCloseTo(before.y, 5);
  expect(Math.abs(viaDeltaX.x - before.x)).toBeGreaterThan(1);

  await reloadStage(page);
  await dispatchWheel(page, { deltaY: -100, shiftKey: true, clientX: center.x, clientY: center.y });
  const viaShift = await readCamera(page);
  expect(viaShift.zoom).toBeCloseTo(before.zoom, 9);
  expect(viaShift.y).toBeCloseTo(before.y, 5);
  expect(viaShift.x).toBeCloseTo(viaDeltaX.x, 3); // the two horizontal-intent routes agree
});

test("P0-08b camera C5 PRD-9.7 wheel: a plain vertical wheel still zooms (as in P0-08a), not pans", async ({
  page,
}) => {
  await gotoStage(page);
  const center = await stageCenter(page);
  const before = await readCamera(page);
  await dispatchWheel(page, { deltaY: -100, clientX: center.x, clientY: center.y });
  const after = await readCamera(page);
  expect(after.zoom).toBeGreaterThan(before.zoom);
  expect(after.x).toBeCloseTo(before.x, 5);
  expect(after.y).toBeCloseTo(before.y, 5);
});

test("P0-08b camera C7 PRD-9.7 keyboard: Ctrl/Meta/Alt combinations with a camera key are never defaultPrevented (browser shortcuts pass)", async ({
  page,
}) => {
  await gotoStage(page);
  const stage = page.getByTestId("stage-frame");
  await stage.focus();
  const prevented = await stage.evaluate((el) =>
    [
      { key: "-", ctrlKey: true },
      { key: "=", metaKey: true },
      { key: "ArrowLeft", altKey: true },
      { key: "ArrowUp", ctrlKey: true },
    ].map((init) => {
      const ev = new KeyboardEvent("keydown", { ...init, bubbles: true, cancelable: true });
      el.dispatchEvent(ev);
      return ev.defaultPrevented;
    }),
  );
  expect(prevented).toEqual([false, false, false, false]);
});

test("P0-08b camera C7 PRD-9.7 keyboard: arrows pan by PAN_STEP_PX and +/- zoom by ZOOM_STEP (values, reduced motion so instant)", async ({
  page,
}) => {
  await gotoStage(page);
  const stage = page.getByTestId("stage-frame");
  await stage.focus();
  const start = await readCamera(page);

  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await readCamera(page)).x).toBeCloseTo(start.x - PAN_STEP_PX, 3);

  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect.poll(async () => (await readCamera(page)).x).toBeCloseTo(start.x + PAN_STEP_PX, 3);

  await page.keyboard.press("=");
  await expect
    .poll(async () => (await readCamera(page)).zoom)
    .toBeCloseTo(start.zoom + ZOOM_STEP, 3);
  await page.keyboard.press("-");
  await page.keyboard.press("-");
  await expect
    .poll(async () => (await readCamera(page)).zoom)
    .toBeCloseTo(start.zoom - ZOOM_STEP, 3);
});
