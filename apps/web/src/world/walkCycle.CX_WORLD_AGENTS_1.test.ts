import { describe, expect, it } from "vitest";
import { walkBob } from "./walkCycle";

describe("CX_WORLD_AGENTS_1 event-driven walking", () => {
  it("bobs only during a recorded movement and stays still for reduced motion", () => {
    expect(walkBob(0, false)).toBe(0);
    expect(walkBob(0.0625, false)).toBeCloseTo(1.35);
    expect(walkBob(0.0625, true)).toBe(0);
    expect(walkBob(2, false)).toBeCloseTo(0);
  });
});
