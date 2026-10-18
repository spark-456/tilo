import { describe, expect, it } from "vitest";
import { CAMERA_TRANSITION_MS, type CameraState, easeCamera, easeW } from "./camera";

describe("TW-3 Camera motion and easing", () => {
  it("specifies 900 ms camera transition time", () => {
    expect(CAMERA_TRANSITION_MS).toBe(900);
  });

  it("calculates cubic-bezier(0.2, 0.8, 0.2, 1) curve", () => {
    expect(easeW(0)).toBe(0);
    expect(easeW(1)).toBe(1);
    expect(easeW(-0.1)).toBe(0);
    expect(easeW(1.1)).toBe(1);

    const mid = easeW(0.5);
    // Cubic bezier (.2, .8, .2, 1) has a steep initial rise, so at t=0.5 it should be significantly above 0.5
    expect(mid).toBeGreaterThan(0.7);
    expect(mid).toBeLessThan(0.95);

    // Monotonically non-decreasing
    let prev = 0;
    for (let i = 1; i <= 20; i++) {
      const curr = easeW(i / 20);
      expect(curr).toBeGreaterThanOrEqual(prev);
      prev = curr;
    }
  });

  it("interpolates camera state using easeW", () => {
    const from: CameraState = { x: 0, y: 0, zoom: 1 };
    const to: CameraState = { x: 200, y: 100, zoom: 1.5 };

    const start = easeCamera(from, to, 0);
    expect(start.x).toBeCloseTo(0);
    expect(start.y).toBeCloseTo(0);
    expect(start.zoom).toBeCloseTo(1);

    const end = easeCamera(from, to, 1);
    expect(end.x).toBe(200);
    expect(end.y).toBe(100);
    expect(end.zoom).toBe(1.5);

    const mid = easeCamera(from, to, 0.5);
    const expectedE = easeW(0.5);
    expect(mid.x).toBeCloseTo(from.x + (to.x - from.x) * expectedE);
    expect(mid.y).toBeCloseTo(from.y + (to.y - from.y) * expectedE);
    expect(mid.zoom).toBeCloseTo(from.zoom + (to.zoom - from.zoom) * expectedE);
  });
});
