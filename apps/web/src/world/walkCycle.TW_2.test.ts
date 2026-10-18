import { describe, expect, it } from "vitest";
import {
  WALK_MAX_DURATION_S,
  WALK_MIN_DURATION_S,
  WALK_SPEED_PPS,
  WALK_STRIDE_MS,
  walkBob,
  walkDuration,
  walkStrides,
} from "./walkCycle";

describe("TW-2 walk cycle specification", () => {
  it("defines walk constants per PROMPT.md", () => {
    expect(WALK_STRIDE_MS).toBe(560);
    expect(WALK_SPEED_PPS).toBe(130);
    expect(WALK_MIN_DURATION_S).toBe(0.6);
    expect(WALK_MAX_DURATION_S).toBe(3.4);
  });

  it("calculates walk duration clamped to 0.6–3.4 s", () => {
    // Very short distance -> clamped to 0.6 s
    expect(walkDuration(10)).toBe(0.6);
    // Medium distance: 260 px / 130 px/s = 2.0 s
    expect(walkDuration(260)).toBeCloseTo(2.0, 5);
    // Very long distance -> clamped to 3.4 s
    expect(walkDuration(1000)).toBe(3.4);
  });

  it("returns 0.2 s under reduced motion (200 ms fade)", () => {
    expect(walkDuration(260, true)).toBe(0.2);
    expect(walkDuration(1000, true)).toBe(0.2);
  });

  it("calculates walk strides from duration", () => {
    // 0.56s = 1 stride
    expect(walkStrides(0.56)).toBe(1);
    // 1.12s = 2 strides
    expect(walkStrides(1.12)).toBe(2);
    // 1.68s = 3 strides
    expect(walkStrides(1.68)).toBe(3);
    // Minimum 1 stride
    expect(walkStrides(0.1)).toBe(1);
  });

  it("preserves walkBob helper with reduced motion support", () => {
    expect(walkBob(0.5, true)).toBe(0);
    expect(walkBob(0.5, false)).toBeCloseTo(0, 5);
    expect(walkBob(0.0625, false)).toBeGreaterThan(0);
  });
});
