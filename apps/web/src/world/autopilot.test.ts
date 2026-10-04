import { describe, expect, it } from "vitest";
import { isStopResult } from "../api/stop";
import { describeStop } from "./autopilot";

const result = (over: Partial<Parameters<typeof describeStop>[0]> = {}) => ({
  stopped: 0,
  already_l1: 0,
  confirmations: [],
  pending: 0,
  ...over,
});

describe("FR-HIL-07 S-15: the page says only what the stop's answer says (HR-1)", () => {
  it("says nothing needed stopping when the API found no rule", () => {
    expect(describeStop(result())).toBe(
      "No rule was running on its own, so nothing needed stopping.",
    );
  });

  it("counts the rules it stopped and the ones that already waited, with real plurals", () => {
    expect(describeStop(result({ stopped: 1 }))).toBe(
      "Stopped 1 rule: each now waits for you at level L1.",
    );
    expect(describeStop(result({ stopped: 3, already_l1: 2 }))).toBe(
      "Stopped 3 rules: each now waits for you at level L1. 2 rules already waited for you.",
    );
    expect(describeStop(result({ already_l1: 1 }))).toBe("1 rule already waited for you.");
  });

  it("says changes are still being recorded while the API answers 202", () => {
    expect(describeStop(result({ stopped: 2, pending: 1 }))).toContain(
      "1 change is still being recorded.",
    );
    expect(describeStop(result({ stopped: 2, pending: 4 }))).toContain(
      "4 changes are still being recorded.",
    );
  });

  it("only a body of the documented shape is a result", () => {
    expect(isStopResult(result({ confirmations: [{ channel: "web" }] }))).toBe(true);
    for (const bad of [
      null,
      "ok",
      {},
      result({ stopped: -1 }),
      result({ stopped: 1.5 }),
      { ...result(), confirmations: "web" },
      { ...result(), confirmations: [{ channel: 1 }] },
      { stopped: 1, already_l1: 0, pending: 0 },
    ]) {
      expect(isStopResult(bad)).toBe(false);
    }
  });
});
