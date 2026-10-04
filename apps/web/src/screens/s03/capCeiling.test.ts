import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CAP_RULE, MAX_BUDGET_CAP_CREDITS } from "./Approaches";

const metering = fileURLToPath(new URL("../../../../../config/metering.yaml", import.meta.url));

describe("AGW-04 S-03 budget cap ceiling", () => {
  it("FR-INT-08 S-03: MAX_BUDGET_CAP_CREDITS equals caps.run_credits in config/metering.yaml, and the rule text names it", () => {
    const yaml = readFileSync(metering, "utf8");
    expect(Number(/^\s+run_credits:\s*(\d+)/m.exec(yaml)?.[1])).toBe(MAX_BUDGET_CAP_CREDITS);
    expect(CAP_RULE).toContain(`to ${MAX_BUDGET_CAP_CREDITS} credits`);
  });
});
