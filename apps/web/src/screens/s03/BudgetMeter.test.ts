import { describe, expect, it } from "vitest";
import { meterGeometry } from "./BudgetMeter";

describe("FR-INT-08 S-03 budget meter geometry", () => {
  it("places the estimate band and the cap on one scale, with room past the larger end", () => {
    const g = meterGeometry(30, 45, 45);
    expect(g.bandLeft).toBeCloseTo((30 / (45 * 1.15)) * 100, 0);
    expect(g.bandLeft + g.bandWidth).toBeCloseTo((45 / (45 * 1.15)) * 100, 0);
    expect(g.capAt).toBeCloseTo((45 / (45 * 1.15)) * 100, 0);
    expect(g.bandLeft + g.bandWidth).toBeLessThan(100);
  });

  it("rescales when the cap goes past the estimate, and has no cap while it is invalid", () => {
    expect(meterGeometry(30, 45, 200).bandWidth).toBeLessThan(meterGeometry(30, 45, 45).bandWidth);
    expect(meterGeometry(30, 45, null).capAt).toBeNull();
  });

  it("never divides by zero", () => {
    const g = meterGeometry(0, 0, null);
    expect(Number.isFinite(g.bandLeft + g.bandWidth)).toBe(true);
  });
});
