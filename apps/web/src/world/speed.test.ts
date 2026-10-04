import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { MAX_SPEED, MIN_SPEED, parseSpeed, speedBadgeText } from "./speed";

describe("HR-6 replay speed: ?speed= is clamped and the badge is worded", () => {
  it("HR_6 no value, zero, negative and text mean the recorded pace", () => {
    for (const bad of [null, "", "0", "-5", "abc", "NaN", "-Infinity", "--1"]) {
      expect(parseSpeed(bad), String(bad)).toBe(1);
    }
  });

  it("HR_6 extreme values are clamped, never passed through (#43)", () => {
    expect(parseSpeed("1e308")).toBe(MAX_SPEED);
    expect(parseSpeed("1e400")).toBe(MAX_SPEED);
    expect(parseSpeed("Infinity")).toBe(MAX_SPEED);
    expect(parseSpeed("1e-300")).toBe(MIN_SPEED);
    expect(parseSpeed("0.000001")).toBe(MIN_SPEED);
  });

  it("HR_6 ordinary values pass through, rounded to two decimals", () => {
    expect(parseSpeed("20")).toBe(20);
    expect(parseSpeed("2.5")).toBe(2.5);
    expect(parseSpeed("1.23456")).toBe(1.23);
    expect(parseSpeed("1.001")).toBe(1);
  });

  it("HR_6 any input gives a finite speed in range, and its badge text has no exponent", () => {
    fc.assert(
      fc.property(fc.oneof(fc.double(), fc.string(), fc.integer()), (v) => {
        const speed = parseSpeed(String(v));
        expect(Number.isFinite(speed)).toBe(true);
        expect(speed === 1 || (speed >= MIN_SPEED && speed <= MAX_SPEED)).toBe(true);
        expect(speedBadgeText(speed) ?? "").not.toMatch(/e[+-]?\d/);
      }),
    );
  });

  it("HR_6 the badge says it in words, and says nothing at 1x", () => {
    expect(speedBadgeText(20)).toBe("Replay at 20× speed");
    expect(speedBadgeText(0.5)).toBe("Replay at 0.5× speed");
    expect(speedBadgeText(1)).toBeNull();
  });
});
