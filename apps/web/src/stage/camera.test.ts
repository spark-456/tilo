/**
 * P0-08a camera motion acceptance test (PRD 18.2 "Motion: ... 320 ms camera;
 * ... reduced motion respected").
 *
 * Expects apps/web/src/stage/camera.ts to export a pure
 * `getCameraPanDurationMs(reducedMotion: boolean): number` the stage's pan/zoom
 * code uses for its CSS transition-duration (see
 * apps/web/e2e/stage-motion.spec.ts for the rendered-DOM version of this
 * check). This module does not exist yet, so the import below fails now.
 */
import { expect, test } from "vitest";
import { getCameraPanDurationMs } from "./camera";

test("PRD-18.2 camera motion: pan/zoom takes 320ms normally", () => {
  expect(getCameraPanDurationMs(false)).toBe(320);
});

test("PRD-18.2 camera motion: reduced motion makes the camera move instantly (0ms), not 320ms", () => {
  expect(getCameraPanDurationMs(true)).toBe(0);
});
