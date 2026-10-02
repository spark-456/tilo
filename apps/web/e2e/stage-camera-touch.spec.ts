/**
 * P0-08b camera C6: pointers tracked by pointerId. One active pointer (mouse left button,
 * touch or pen) pans by its own movement only; right/middle mouse buttons never pan; two touch
 * pointers pinch-zoom about their midpoint and pan with the midpoint; landing/lifting a second
 * finger, and pointercancel, must never jump the camera. qa-breaker found (P0-08a head 5757d28,
 * .claude/agent-memory/qa-breaker/web-stage-attack-patterns.md #6) that a single shared "last
 * pointer position" made a two-finger touch alternate deltas between fingers and jump the
 * camera by the finger distance (a 5px pinch produced a 205px translate) — per-pointerId
 * tracking is the fix and is now an acceptance criterion.
 *
 * Touch is driven with CDP `Input.dispatchTouchEvent` (two touchPoints), the only way to send
 * a real multi-touch gesture in a Chromium-family browser; Playwright's own touchscreen API is
 * single-finger only. Requires a `hasTouch: true` browser context.
 *
 * Public interface: e2e/support/camera.ts (readCamera); no new production exports.
 */
import { type Page, expect, test } from "@playwright/test";
import { gotoStage, readCamera } from "./support/camera";

// A world address, not "/": the S-01 Start panel covers the stage centre, where these gestures land.
const STAGE_URL = "/world/w_village_basic";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP, reducedMotion: "reduce", hasTouch: true });

type TouchPoint = { x: number; y: number; id: number };

async function cdp(page: Page) {
  return page.context().newCDPSession(page);
}
async function touchStart(session: Awaited<ReturnType<typeof cdp>>, points: TouchPoint[]) {
  await session.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: points });
}
async function touchMove(session: Awaited<ReturnType<typeof cdp>>, points: TouchPoint[]) {
  await session.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: points });
}
// CDP semantics: the touchPoints of a touchEnd are the fingers that LIFT (none = all lift).
async function touchEnd(session: Awaited<ReturnType<typeof cdp>>, lifted: TouchPoint[] = []) {
  await session.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: lifted });
}
// CDP cannot cancel a single finger (a touchCancel must carry no points), so a one-finger
// pointercancel is a synthetic PointerEvent for the pointerId the browser gave that finger.
async function recordTouchPointerIds(page: Page) {
  await page.getByTestId("stage-frame").evaluate((el) => {
    const w = window as unknown as { __touchIds: { id: number; x: number }[] };
    w.__touchIds = [];
    el.addEventListener(
      "pointerdown",
      (e) =>
        w.__touchIds.push({ id: (e as PointerEvent).pointerId, x: (e as PointerEvent).clientX }),
      true,
    );
  });
}
async function cancelPointerAt(page: Page, x: number) {
  await page.getByTestId("stage-frame").evaluate((el, x) => {
    const w = window as unknown as { __touchIds: { id: number; x: number }[] };
    const hit = w.__touchIds.find((p) => Math.abs(p.x - x) < 1);
    if (!hit) throw new Error(`no touch pointer went down at x=${x}`);
    const init = { pointerId: hit.id, pointerType: "touch", bubbles: true, isPrimary: false };
    el.dispatchEvent(new PointerEvent("pointercancel", init));
  }, x);
}
// data-camera-* is written when a frame is drawn (rAF), so read it after the next frame.
async function drawnCamera(page: Page) {
  await page.evaluate(
    () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
  );
  return readCamera(page);
}

async function stageCenter(page: Page) {
  const box = await page.getByTestId("stage-frame").boundingBox();
  if (!box) throw new Error("stage-frame has no layout box");
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

// ---- mouse: pointerId / button isolation --------------------------------

test("P0-08b camera C6 PRD-9.7 pointer: one left-button drag pans by exactly its own movement", async ({
  page,
}) => {
  await gotoStage(page, STAGE_URL);
  await page.mouse.move(600, 400);
  await page.mouse.down({ button: "left" });
  await page.mouse.move(500, 350);
  await page.mouse.up({ button: "left" });
  await expect.poll(async () => (await readCamera(page)).x).toBeCloseTo(-100, 0);
  expect((await readCamera(page)).y).toBeCloseTo(-50, 0);
});

for (const button of ["right", "middle"] as const) {
  test(`P0-08b camera C6 PRD-9.7 pointer: a ${button}-button drag never pans`, async ({ page }) => {
    await gotoStage(page, STAGE_URL);
    const before = await readCamera(page);
    await page.mouse.move(600, 400);
    await page.mouse.down({ button });
    await page.mouse.move(500, 350);
    await page.mouse.up({ button });
    const after = await readCamera(page);
    expect(after.x).toBeCloseTo(before.x, 5);
    expect(after.y).toBeCloseTo(before.y, 5);
  });
}

// ---- touch: two-pointer pinch -------------------------------------------

test("P0-08b camera C6 PRD-9.7 touch: two fingers moving apart (fixed midpoint) zoom in about the midpoint, without panning", async ({
  page,
}) => {
  await gotoStage(page, STAGE_URL);
  const c = await stageCenter(page);
  const session = await cdp(page);
  const before = await readCamera(page);

  await touchStart(session, [
    { x: c.x - 40, y: c.y, id: 0 },
    { x: c.x + 40, y: c.y, id: 1 },
  ]);
  await touchMove(session, [
    { x: c.x - 80, y: c.y, id: 0 },
    { x: c.x + 80, y: c.y, id: 1 },
  ]);
  await touchEnd(session);

  const after = await readCamera(page);
  expect(after.zoom, "distance doubled, so zoom must have increased").toBeGreaterThan(before.zoom);
  // Midpoint never moved (stage centre throughout), so the pan components stay ~0.
  expect(after.x).toBeCloseTo(before.x, 0);
  expect(after.y).toBeCloseTo(before.y, 0);
});

test("P0-08b camera C6 PRD-9.7 touch: two fingers moving together (fixed distance) pan by the midpoint's movement, without zooming", async ({
  page,
}) => {
  await gotoStage(page, STAGE_URL);
  const c = await stageCenter(page);
  const session = await cdp(page);
  const before = await readCamera(page);

  await touchStart(session, [
    { x: c.x - 40, y: c.y, id: 0 },
    { x: c.x + 40, y: c.y, id: 1 },
  ]);
  await touchMove(session, [
    { x: c.x - 40 - 60, y: c.y - 30, id: 0 },
    { x: c.x + 40 - 60, y: c.y - 30, id: 1 },
  ]);
  await touchEnd(session);

  const after = await readCamera(page);
  expect(after.zoom).toBeCloseTo(before.zoom, 2);
  expect(after.x).toBeCloseTo(before.x - 60, 0);
  expect(after.y).toBeCloseTo(before.y - 30, 0);
});

test("P0-08b camera C6 PRD-9.7 touch: landing a second finger causes no jump (camera unchanged the instant it lands)", async ({
  page,
}) => {
  await gotoStage(page, STAGE_URL);
  const c = await stageCenter(page);
  const session = await cdp(page);

  // Finger A starts and drags a little, establishing a single-pointer pan.
  await touchStart(session, [{ x: c.x - 40, y: c.y, id: 0 }]);
  await touchMove(session, [{ x: c.x - 10, y: c.y, id: 0 }]);
  const beforeLanding = await readCamera(page);

  // Finger B lands (touchstart with both points, no movement yet): must not itself move the
  // camera (qa-breaker: a naive implementation jumped by the inter-finger distance here).
  await touchStart(session, [
    { x: c.x - 10, y: c.y, id: 0 },
    { x: c.x + 90, y: c.y, id: 1 },
  ]);
  const afterLanding = await readCamera(page);
  await touchEnd(session);

  expect(Math.abs(afterLanding.x - beforeLanding.x)).toBeLessThanOrEqual(2);
  expect(Math.abs(afterLanding.y - beforeLanding.y)).toBeLessThanOrEqual(2);
  expect(Math.abs(afterLanding.zoom - beforeLanding.zoom)).toBeLessThanOrEqual(0.02);
});

test("P0-08b camera C6 PRD-9.7 touch: lifting one of two fingers causes no jump, and the remaining finger then pans by its own delta only", async ({
  page,
}) => {
  await gotoStage(page, STAGE_URL);
  const c = await stageCenter(page);
  const session = await cdp(page);

  await touchStart(session, [
    { x: c.x - 40, y: c.y, id: 0 },
    { x: c.x + 40, y: c.y, id: 1 },
  ]);
  await touchMove(session, [
    { x: c.x - 60, y: c.y, id: 0 },
    { x: c.x + 60, y: c.y, id: 1 },
  ]);
  const beforeLift = await drawnCamera(page);

  // Finger 0 lifts; finger 1 stays put at (c.x+60, c.y) — no movement in this event.
  await touchEnd(session, [{ x: c.x - 60, y: c.y, id: 0 }]);
  const afterLift = await drawnCamera(page);
  expect(Math.abs(afterLift.x - beforeLift.x)).toBeLessThanOrEqual(2);
  expect(Math.abs(afterLift.y - beforeLift.y)).toBeLessThanOrEqual(2);
  expect(Math.abs(afterLift.zoom - beforeLift.zoom)).toBeLessThanOrEqual(0.02);

  // Now the lone remaining finger drags; camera must follow only its own delta (35, -20).
  await touchMove(session, [{ x: c.x + 60 + 35, y: c.y - 20, id: 1 }]);
  const afterSoloMove = await drawnCamera(page);
  await touchEnd(session);
  expect(afterSoloMove.x).toBeCloseTo(afterLift.x + 35, 0);
  expect(afterSoloMove.y).toBeCloseTo(afterLift.y - 20, 0);
});

test("P0-08b camera C6 PRD-9.7 touch: pointercancel on one finger causes no jump, and the other finger keeps panning correctly", async ({
  page,
}) => {
  await gotoStage(page, STAGE_URL);
  const c = await stageCenter(page);
  const session = await cdp(page);
  await recordTouchPointerIds(page);

  await touchStart(session, [
    { x: c.x - 40, y: c.y, id: 0 },
    { x: c.x + 40, y: c.y, id: 1 },
  ]);
  const beforeCancel = await drawnCamera(page);

  // Finger 0 is cancelled; finger 1 stays down and then pans alone.
  await cancelPointerAt(page, c.x - 40);
  const afterCancel = await drawnCamera(page);
  expect(Math.abs(afterCancel.x - beforeCancel.x)).toBeLessThanOrEqual(2);
  expect(Math.abs(afterCancel.y - beforeCancel.y)).toBeLessThanOrEqual(2);

  await touchMove(session, [{ x: c.x + 40 + 25, y: c.y + 10, id: 1 }]);
  const afterMove = await drawnCamera(page);
  await touchEnd(session);
  expect(afterMove.x).toBeCloseTo(afterCancel.x + 25, 0);
  expect(afterMove.y).toBeCloseTo(afterCancel.y + 10, 0);
});
