/**
 * P0-08a camera motion acceptance test (PRD 18.2 "Motion: ... 320 ms camera;
 * ... reduced motion respected"), plus P0-08b camera unit tests for the new
 * pure helpers the rework needs (PRD 9.7, HR-3; wheel/pinch bugs are
 * acceptance criteria per .claude/agent-memory/qa-breaker/web-stage-attack-patterns.md).
 *
 * Public interface this file requires of apps/web/src/stage/camera.ts, in
 * addition to its existing P0-08a exports (CAMERA_PAN_MS, PAN_STEP_PX,
 * ZOOM_STEP, ZOOM_MIN, ZOOM_MAX, CameraState, INITIAL_CAMERA,
 * getCameraPanDurationMs, panCamera, zoomCamera — all kept unchanged):
 *
 *   export type WheelInput = {
 *     deltaX: number; deltaY: number; deltaMode: number; // 0 px, 1 line (40px), 2 page (800px)
 *     ctrlKey: boolean; shiftKey: boolean;
 *   };
 *   export type WheelNormalized = { panDx: number; panDy: number; zoomDelta: number };
 *
 *   // Normalises a wheel/trackpad event into a pan and/or a zoom delta (never both
 *   // nonzero from one event). ctrlKey (trackpad pinch) always zooms and never pans.
 *   // Horizontal intent (deltaX !== 0, or shiftKey with a vertical-only delta) always
 *   // pans and never zooms. Otherwise a plain vertical wheel zooms. deltaMode scales
 *   // the raw delta to a px-equivalent (1 / 40 / 800) before either branch, so the same
 *   // on-screen distance in any deltaMode yields the same result. The zoom branch caps
 *   // at one ZOOM_STEP per event and is 0 for a zero delta.
 *   export function normalizeWheel(e: WheelInput): WheelNormalized;
 *
 *   // Zooms `s` to zoom + delta (clamped to [ZOOM_MIN, ZOOM_MAX]) about the screen point
 *   // (px, py) — a screen-px offset from the stage centre, the same frame data-camera-x/y
 *   // use — so the world point currently under (px, py) is still under it afterwards.
 *   // (px, py) = (0, 0) is "about the stage centre" (used for keyboard zoom, C7).
 *   export function zoomAt(s: CameraState, delta: number, px: number, py: number): CameraState;
 */
import { expect, test } from "vitest";
import {
  type CameraState,
  INITIAL_CAMERA,
  ZOOM_MAX,
  ZOOM_MIN,
  ZOOM_STEP,
  getCameraPanDurationMs,
  normalizeWheel,
  zoomAt,
} from "./camera";

test("PRD-18.2 camera motion: pan/zoom takes 320ms normally", () => {
  expect(getCameraPanDurationMs(false)).toBe(320);
});

test("PRD-18.2 camera motion: reduced motion makes the camera move instantly (0ms), not 320ms", () => {
  expect(getCameraPanDurationMs(true)).toBe(0);
});

// A small seeded PRNG (mulberry32) stands in for fast-check, which is not a dependency
// of apps/web (the test-writer for the sibling P0-08b-player sub-ticket owns adding it;
// this sub-ticket was told not to add dependencies and to write property tests without
// it, or say so — this comment is that "saying so").
function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rnd = mulberry32(0xc0ffee);
const between = (lo: number, hi: number) => lo + rnd() * (hi - lo);
const N = 200;

// ---- normalizeWheel ---------------------------------------------------

test("P0-08b camera C3 PRD-9.7 wheel: deltaMode 0/1/2 give the same zoom for the same on-screen distance", () => {
  for (let i = 0; i < N; i++) {
    const px = between(-500, 500); // a "px-equivalent" magnitude, signed
    const a = normalizeWheel({
      deltaX: 0,
      deltaY: px,
      deltaMode: 0,
      ctrlKey: false,
      shiftKey: false,
    });
    const b = normalizeWheel({
      deltaX: 0,
      deltaY: px / 40,
      deltaMode: 1,
      ctrlKey: false,
      shiftKey: false,
    });
    const c = normalizeWheel({
      deltaX: 0,
      deltaY: px / 800,
      deltaMode: 2,
      ctrlKey: false,
      shiftKey: false,
    });
    expect(b.zoomDelta).toBeCloseTo(a.zoomDelta, 9);
    expect(c.zoomDelta).toBeCloseTo(a.zoomDelta, 9);
  }
});

test("P0-08b camera C3 PRD-9.7 wheel: a 100px notch is exactly one ZOOM_STEP, smaller deltas zoom proportionally less", () => {
  const notch = normalizeWheel({
    deltaX: 0,
    deltaY: -100,
    deltaMode: 0,
    ctrlKey: false,
    shiftKey: false,
  });
  expect(notch.zoomDelta).toBeCloseTo(ZOOM_STEP, 9);

  const half = normalizeWheel({
    deltaX: 0,
    deltaY: -50,
    deltaMode: 0,
    ctrlKey: false,
    shiftKey: false,
  });
  expect(half.zoomDelta).toBeCloseTo(ZOOM_STEP / 2, 9);

  // Monotonic: strictly smaller magnitude (within the un-clamped [0, 100]px range)
  // strictly smaller zoom.
  for (let i = 0; i < N; i++) {
    const small = between(1, 99);
    const big = between(small, 100);
    const zSmall = Math.abs(
      normalizeWheel({ deltaX: 0, deltaY: -small, deltaMode: 0, ctrlKey: false, shiftKey: false })
        .zoomDelta,
    );
    const zBig = Math.abs(
      normalizeWheel({ deltaX: 0, deltaY: -big, deltaMode: 0, ctrlKey: false, shiftKey: false })
        .zoomDelta,
    );
    expect(zBig).toBeGreaterThanOrEqual(zSmall);
  }
});

test("P0-08b camera C3 PRD-9.7 wheel: one event never zooms more than one ZOOM_STEP, for any deltaY/deltaMode", () => {
  for (let i = 0; i < N; i++) {
    const deltaY = between(-1e7, 1e7);
    const deltaMode = [0, 1, 2][Math.floor(rnd() * 3)] ?? 0;
    const { zoomDelta } = normalizeWheel({
      deltaX: 0,
      deltaY,
      deltaMode,
      ctrlKey: false,
      shiftKey: false,
    });
    expect(Math.abs(zoomDelta)).toBeLessThanOrEqual(ZOOM_STEP + 1e-9);
  }
});

test("P0-08b camera C4 PRD-9.7 wheel: ctrlKey (trackpad pinch) always zooms and never pans, whatever deltaX carries", () => {
  for (let i = 0; i < N; i++) {
    const deltaY = between(-300, 300);
    const deltaX = between(-50, 50); // pinch sometimes carries jitter on deltaX
    const { panDx, panDy, zoomDelta } = normalizeWheel({
      deltaX,
      deltaY,
      deltaMode: 0,
      ctrlKey: true,
      shiftKey: false,
    });
    expect(panDx).toBe(0);
    expect(panDy).toBe(0);
    if (deltaY !== 0) expect(zoomDelta).not.toBe(0);
  }
});

test("P0-08b camera C5 PRD-9.7 wheel: horizontal intent (deltaX, or Shift + vertical) always pans and never zooms", () => {
  for (let i = 0; i < N; i++) {
    const d = between(-300, 300);
    const viaDeltaX = normalizeWheel({
      deltaX: d,
      deltaY: 0,
      deltaMode: 0,
      ctrlKey: false,
      shiftKey: false,
    });
    const viaShift = normalizeWheel({
      deltaX: 0,
      deltaY: d,
      deltaMode: 0,
      ctrlKey: false,
      shiftKey: true,
    });
    expect(viaDeltaX.zoomDelta).toBe(0);
    expect(viaShift.zoomDelta).toBe(0);
    if (d !== 0) {
      expect(viaDeltaX.panDx).not.toBe(0);
      expect(viaShift.panDx).not.toBe(0);
    }
    expect(viaDeltaX.panDy).toBe(0);
    expect(viaShift.panDy).toBe(0);
    // Both routes to "pan by d" agree (deltaX vs. shift+deltaY are equivalent inputs).
    expect(viaShift.panDx).toBeCloseTo(viaDeltaX.panDx, 9);
  }
});

test("P0-08b camera C5 PRD-9.7 wheel: a plain vertical wheel (no ctrl, no shift, no deltaX) zooms and never pans", () => {
  for (let i = 0; i < N; i++) {
    const deltaY = between(-300, 300);
    const { panDx, panDy, zoomDelta } = normalizeWheel({
      deltaX: 0,
      deltaY,
      deltaMode: 0,
      ctrlKey: false,
      shiftKey: false,
    });
    expect(panDx).toBe(0);
    expect(panDy).toBe(0);
    if (deltaY !== 0) expect(zoomDelta).not.toBe(0);
  }
});

// ---- zoomAt -------------------------------------------------------------

test("P0-08b camera C3/C4 PRD-9.7 zoomAt: the world point under the screen point (px, py) stays fixed (within 1e-6)", () => {
  for (let i = 0; i < N; i++) {
    const s: CameraState = {
      x: between(-2000, 2000),
      y: between(-2000, 2000),
      zoom: between(ZOOM_MIN, ZOOM_MAX),
    };
    const delta = between(-ZOOM_STEP, ZOOM_STEP);
    const px = between(-900, 900);
    const py = between(-600, 600);

    const worldXBefore = (px - s.x) / s.zoom;
    const worldYBefore = (py - s.y) / s.zoom;

    const next = zoomAt(s, delta, px, py);
    const worldXAfter = (px - next.x) / next.zoom;
    const worldYAfter = (py - next.y) / next.zoom;

    expect(worldXAfter).toBeCloseTo(worldXBefore, 6);
    expect(worldYAfter).toBeCloseTo(worldYBefore, 6);
  }
});

test("P0-08b camera C3 PRD-9.7 zoomAt: zoom stays clamped to [ZOOM_MIN, ZOOM_MAX] for any state/delta", () => {
  for (let i = 0; i < N; i++) {
    const s: CameraState = {
      x: between(-2000, 2000),
      y: between(-2000, 2000),
      zoom: between(ZOOM_MIN, ZOOM_MAX),
    };
    const delta = between(-10, 10);
    const next = zoomAt(s, delta, between(-900, 900), between(-600, 600));
    expect(next.zoom).toBeGreaterThanOrEqual(ZOOM_MIN);
    expect(next.zoom).toBeLessThanOrEqual(ZOOM_MAX);
  }
});

test("P0-08b camera C7 PRD-9.7 zoomAt: zooming about the stage centre (0, 0) from INITIAL_CAMERA leaves x/y at 0", () => {
  const next = zoomAt(INITIAL_CAMERA, ZOOM_STEP, 0, 0);
  expect(next.x).toBe(0);
  expect(next.y).toBe(0);
  expect(next.zoom).toBeCloseTo(1 + ZOOM_STEP, 9);
});
