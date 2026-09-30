import { expect } from "@playwright/test";

// Shared expectations for the P0-08a layout-frame and stage tests. These
// fix the test-only interface contract the builder implements against
// (PRD 18.2/18.3/9.7 leave exact markup unspecified, so test-writer picked
// this one and notes it here):
//   [data-testid="left-rail"]       desktop-only 72px left rail
//   [data-testid="right-rail"]      desktop-only 360px right rail
//   [data-testid="right-rail-meter"] the honest-empty-state meter inside it
//   [data-testid="bottom-tabs"]     mobile-only bottom tab bar
//   [data-testid="stage-frame"]     the centre stage container (both sizes)
//   [data-testid="stage-fallback"]  the no-WebGL2 fallback panel
//   role=navigation, name "Primary" the left rail / bottom tabs nav landmark
//
// P0-08b camera C2 replaces the P0-08a `[data-testid="camera"]` CSS layer.
// The camera is now a transform on a PixiJS world container (C1): the only
// test-observable surface is three attributes on `[data-testid="stage-frame"]`
// itself, always equal to the camera currently drawn on the canvas:
//   data-camera-x      screen-px offset of the world origin from the stage centre (number, may be negative)
//   data-camera-y      screen-px offset of the world origin from the stage centre (number, may be negative)
//   data-camera-zoom   world scale, clamped to [ZOOM_MIN, ZOOM_MAX] (see src/stage/camera.ts)
// See ./camera.ts (readCamera) for the shared reader.

export function expectWithinPx(actual: number, expected: number, tolerancePx = 3): void {
  expect(
    Math.abs(actual - expected),
    `expected ~${expected}px, got ${actual}px (tolerance ${tolerancePx}px)`,
  ).toBeLessThanOrEqual(tolerancePx);
}

/** Asserts a Playwright boundingBox() result is non-null and returns it narrowed,
 * without a `!` non-null assertion (forbidden by this repo's Biome config). */
export function requireBox(
  box: { x: number; y: number; width: number; height: number } | null,
  what: string,
): { x: number; y: number; width: number; height: number } {
  expect(box, `${what} has no layout box`).not.toBeNull();
  if (box === null) throw new Error(`unreachable: ${what} has no layout box`);
  return box;
}

/** P0-08b camera C1: the canvas must exactly fill the stage frame (all four edges), not just
 * match width/height while drifting off-centre (the P0-08a CSS-camera bug: qa-breaker
 * web-stage-attack-patterns.md #2). */
export function expectSameBox(
  actual: { x: number; y: number; width: number; height: number },
  expected: { x: number; y: number; width: number; height: number },
  tolerancePx = 3,
): void {
  expectWithinPx(actual.x, expected.x, tolerancePx);
  expectWithinPx(actual.y, expected.y, tolerancePx);
  expectWithinPx(actual.width, expected.width, tolerancePx);
  expectWithinPx(actual.height, expected.height, tolerancePx);
}
