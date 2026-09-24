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
//   [data-testid="camera"]          the element the camera pan/zoom transform
//                                   and transition-duration are read from
//                                   (falls back to stage-frame itself if a
//                                   test cannot find a more specific node)
//   role=navigation, name "Primary" the left rail / bottom tabs nav landmark

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
