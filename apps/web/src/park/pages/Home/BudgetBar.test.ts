// OLD-UI-OUT wave 1: the budget meter and the cap ceiling, ported from the retired S-03 tests
// (BudgetMeter.test.ts, capCeiling.test.ts) with the logic.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MAX_RUN_CREDITS } from "../../api/oneStep";
import { meterGeometry } from "./BudgetBar";

const metering = fileURLToPath(new URL("../../../../../../config/metering.yaml", import.meta.url));

describe("FR-INT-08 confirm card budget meter geometry", () => {
  it("places the estimate band and the cap on one scale, with room past the larger end", () => {
    const g = meterGeometry(30, 45, 45);
    expect(g.bandLeft).toBeCloseTo((30 / (45 * 1.15)) * 100, 0);
    expect(g.bandLeft + g.bandWidth).toBeCloseTo((45 / (45 * 1.15)) * 100, 0);
    expect(g.capAt).toBeCloseTo((45 / (45 * 1.15)) * 100, 0);
    expect(g.bandLeft + g.bandWidth).toBeLessThan(100);
  });

  it("rescales when the cap goes past the estimate, and has no cap while there is none", () => {
    expect(meterGeometry(30, 45, 200).bandWidth).toBeLessThan(meterGeometry(30, 45, 45).bandWidth);
    expect(meterGeometry(30, 45, null).capAt).toBeNull();
  });

  it("never divides by zero", () => {
    const g = meterGeometry(0, 0, null);
    expect(Number.isFinite(g.bandLeft + g.bandWidth)).toBe(true);
  });
});

describe("FR-INT-08 confirm card cap ceiling", () => {
  it("MAX_RUN_CREDITS equals caps.run_credits in config/metering.yaml", () => {
    const yaml = readFileSync(metering, "utf8");
    expect(Number(/^\s+run_credits:\s*(\d+)/m.exec(yaml)?.[1])).toBe(MAX_RUN_CREDITS);
  });
});
