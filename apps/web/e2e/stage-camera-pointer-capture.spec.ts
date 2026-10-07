/**
 * P0-08b follow-up (#67 item 3): a pointerdown whose pointer capture throws (a synthetic or
 * already-inactive pointerId makes `setPointerCapture` raise NotFoundError) must still anchor the
 * gesture, so the next move pans by its own movement only. With the anchor taken after the capture,
 * the throw left the anchor at its initial (0, 0) and the next move jumped the camera by the
 * pointer's absolute position.
 */
import { expect, test } from "@playwright/test";
import { gotoStage, readCamera } from "./support/camera";
import { DESKTOP } from "./support/viewports";

// The stage address (WEB-CUTOVER: `/` is the Park Home), so nothing covers the stage centre.
const STAGE_URL = "/world/w_village_basic/stage";

test.use({ viewport: DESKTOP, reducedMotion: "reduce" });

test("P0-08b follow-up #67 PRD-9.7 pointer: a throwing setPointerCapture still anchors, the next move does not jump", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await gotoStage(page, STAGE_URL);
  const before = await readCamera(page);

  // pointerId 77 is not an active pointer, so setPointerCapture(77) throws in Chromium.
  await page.getByTestId("stage-frame").evaluate((el) => {
    const init = { pointerId: 77, pointerType: "mouse", button: 0, bubbles: true };
    el.dispatchEvent(new PointerEvent("pointerdown", { ...init, clientX: 700, clientY: 400 }));
    el.dispatchEvent(new PointerEvent("pointermove", { ...init, clientX: 690, clientY: 400 }));
    el.dispatchEvent(new PointerEvent("pointerup", { ...init, clientX: 690, clientY: 400 }));
  });
  await page.evaluate(
    () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
  );

  const after = await readCamera(page);
  expect(after.x - before.x).toBeCloseTo(-10, 0);
  expect(after.y - before.y).toBeCloseTo(0, 0);
  expect(errors).toEqual([]);
});
