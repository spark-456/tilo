import { describe, expect, it } from "vitest";
import { stageResolution } from "./resolution";

describe("FR-WLD-13 stageResolution", () => {
  it("FR-WLD-13 leaves desktop widths at the device pixel ratio", () => {
    expect(stageResolution(2, 1440)).toBe(2);
    expect(stageResolution(3, 1024)).toBe(3);
    expect(stageResolution(1, 1920)).toBe(1);
  });
  it("FR-WLD-13 caps a phone-width canvas so a 3x screen draws fewer pixels", () => {
    expect(stageResolution(3, 390)).toBeLessThan(3);
    expect(stageResolution(3, 390)).toBeGreaterThanOrEqual(1.5);
    expect(stageResolution(1, 390)).toBe(1);
  });
  it("FR-WLD-13 falls back to 1 for a missing or invalid ratio", () => {
    expect(stageResolution(0, 390)).toBe(1);
    expect(stageResolution(Number.NaN, 1440)).toBe(1);
  });
});
